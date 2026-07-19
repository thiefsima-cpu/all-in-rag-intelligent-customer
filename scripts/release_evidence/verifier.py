from __future__ import annotations

import hashlib
import json
import math
import re
import stat
import subprocess
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from pydantic import ValidationError

from scripts.integration_gate.models import IntegrationGatePolicy
from scripts.integration_gate.reporter import render_integration_summary
from scripts.live_quality_gate.models import LiveQualityGatePolicy
from scripts.live_quality_gate.reporter import render_live_quality_summary
from scripts.validate_release_tag import parse_release_tag

from .models import (
    MANIFEST_SCHEMA_VERSION,
    GitHubArtifactMetadata,
    KnowledgeBaseIdentity,
    ReleaseEvidenceManifest,
    RuntimeIdentity,
)

MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_SOURCE_BYTES = 50 * 1024 * 1024
MAX_BUNDLE_BYTES = MAX_BUNDLE_SOURCE_BYTES + 1024 * 1024
_MAX_REPORT_AGE = timedelta(minutes=180)
_MAX_REPORT_FUTURE_SKEW = timedelta(minutes=5)
_READ_CHUNK_BYTES = 1024 * 1024
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_GATE_STATUSES = frozenset({"passed", "failed", "blocked"})
_ARTIFACT_NAMES = {
    "checksums.json": "checksums",
    "integration_gate/report.json": "integration_report",
    "integration_gate/summary.md": "integration_summary",
    "live_quality_gate/manual_review_sample.jsonl": "manual_review_sample",
    "live_quality_gate/report.json": "live_quality_report",
    "live_quality_gate/summary.md": "live_quality_summary",
    "policies/integration_gate.json": "integration_policy",
    "policies/live_quality_gate.json": "live_quality_policy",
    "runtime/artifact_manifest.json": "knowledge_artifact",
    "runtime/diagnostics.json": "runtime_diagnostics",
}
_INTEGRATION_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "generated_at",
        "passed",
        "target",
        "metrics",
        "checks",
        "cases",
        "artifacts",
    }
)
_LIVE_REPORT_KEYS = frozenset(
    {
        "schema_version",
        "generated_at",
        "passed",
        "target",
        "top_k",
        "metrics",
        "failure_type_counts",
        "checks",
        "cases",
        "manual_review_sample_count",
        "manual_review_sample",
        "artifacts",
    }
)


class ReleaseEvidenceVerificationError(RuntimeError):
    pass


class _DuplicateJsonKeyError(ValueError):
    pass


@dataclass(frozen=True)
class VerifyInputs:
    repository_root: Path
    manifest_path: Path
    release_commit: str
    tag: str
    bundle_path: Path
    artifact_metadata_path: Path


def release_manifest_path(repository_root: Path, package_version: str) -> Path:
    return (
        repository_root
        / "quality-evidence"
        / "releases"
        / package_version
        / "evidence-manifest.json"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJsonKeyError(key)
        payload[key] = value
    return payload


def _reject_non_finite(_: str) -> None:
    raise ValueError("non-finite JSON number")


def _parse_json_object(value: bytes, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            value.decode("utf-8"),
            parse_constant=_reject_non_finite,
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except _DuplicateJsonKeyError as exc:
        raise ReleaseEvidenceVerificationError(f"{name} contains a duplicate JSON key") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseEvidenceVerificationError(f"{name} is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ReleaseEvidenceVerificationError(f"{name} must be a JSON object")
    return payload


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_limited_file(path: Path, *, maximum: int, name: str) -> bytes:
    try:
        if path.stat().st_size > maximum:
            raise ReleaseEvidenceVerificationError(f"{name} is too large")
        chunks: list[bytes] = []
        captured = 0
        with path.open("rb") as source:
            while chunk := source.read(_READ_CHUNK_BYTES):
                captured += len(chunk)
                if captured > maximum:
                    raise ReleaseEvidenceVerificationError(f"{name} is too large")
                chunks.append(chunk)
    except ReleaseEvidenceVerificationError:
        raise
    except OSError as exc:
        raise ReleaseEvidenceVerificationError(f"{name} could not be read") from exc
    return b"".join(chunks)


def _git(
    repository_root: Path,
    *args: str,
    allowed_returncodes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed") from exc
    allowed = allowed_returncodes or {0}
    if completed.returncode not in allowed:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed")
    return completed


def _git_bytes(
    repository_root: Path,
    *args: str,
) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed") from exc
    if completed.returncode != 0:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed")
    return completed.stdout


def _git_clean_object_id(
    repository_root: Path,
    relative_path: str,
    value: bytes,
) -> str:
    try:
        completed = subprocess.run(
            ["git", "hash-object", f"--path={relative_path}", "--stdin"],
            cwd=repository_root,
            input=value,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed") from exc
    if completed.returncode != 0:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed")
    try:
        return completed.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed") from exc


def _committed_blob(
    repository_root: Path,
    commit: str,
    relative_path: str,
) -> bytes:
    entry = _git(repository_root, "ls-tree", commit, "--", relative_path).stdout.rstrip("\n")
    try:
        metadata, listed_path = entry.split("\t", 1)
        mode, object_type, object_id = metadata.split()
    except ValueError as exc:
        raise ReleaseEvidenceVerificationError(
            f"committed evidence source is invalid: {relative_path}"
        ) from exc
    if listed_path != relative_path or mode not in {"100644", "100755"} or object_type != "blob":
        raise ReleaseEvidenceVerificationError(
            f"committed evidence source is invalid: {relative_path}"
        )
    try:
        blob_size = int(_git(repository_root, "cat-file", "-s", object_id).stdout.strip())
    except ValueError as exc:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed") from exc
    if blob_size > MAX_MEMBER_BYTES:
        raise ReleaseEvidenceVerificationError(
            f"committed evidence source is too large: {relative_path}"
        )
    value = _git_bytes(repository_root, "cat-file", "blob", object_id)
    if len(value) != blob_size:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed")
    return value


def _expected_manifest_relative(manifest: ReleaseEvidenceManifest) -> str:
    return (
        Path("quality-evidence")
        / "releases"
        / manifest.release.package_version
        / "evidence-manifest.json"
    ).as_posix()


def _verify_git(
    inputs: VerifyInputs,
    manifest: ReleaseEvidenceManifest,
    manifest_bytes: bytes,
) -> None:
    if not _GIT_SHA_RE.fullmatch(inputs.release_commit):
        raise ReleaseEvidenceVerificationError("release commit is invalid")
    _git(inputs.repository_root, "cat-file", "-e", f"{inputs.release_commit}^{{commit}}")
    _git(
        inputs.repository_root,
        "cat-file",
        "-e",
        f"{manifest.provenance.evaluated_commit}^{{commit}}",
    )
    ancestor = _git(
        inputs.repository_root,
        "merge-base",
        "--is-ancestor",
        manifest.provenance.evaluated_commit,
        inputs.release_commit,
        allowed_returncodes={0, 1},
    )
    if ancestor.returncode != 0:
        raise ReleaseEvidenceVerificationError(
            "evaluated commit is not an ancestor of release commit"
        )

    expected_relative = _expected_manifest_relative(manifest)
    try:
        actual_relative = (
            inputs.manifest_path.resolve().relative_to(inputs.repository_root.resolve()).as_posix()
        )
    except ValueError as exc:
        raise ReleaseEvidenceVerificationError("release manifest path is invalid") from exc
    if actual_relative != expected_relative:
        raise ReleaseEvidenceVerificationError("release manifest path is invalid")
    try:
        _committed_blob(
            inputs.repository_root,
            inputs.release_commit,
            expected_relative,
        )
    except ReleaseEvidenceVerificationError as exc:
        raise ReleaseEvidenceVerificationError(
            "release manifest is missing from release commit"
        ) from exc
    committed_object_id = _git(
        inputs.repository_root,
        "rev-parse",
        f"{inputs.release_commit}:{expected_relative}",
    ).stdout.strip()
    if (
        _git_clean_object_id(
            inputs.repository_root,
            expected_relative,
            manifest_bytes,
        )
        != committed_object_id
    ):
        raise ReleaseEvidenceVerificationError("release manifest does not match release commit")

    changed = [
        line
        for line in _git(
            inputs.repository_root,
            "diff",
            "--name-status",
            "--no-renames",
            f"{manifest.provenance.evaluated_commit}..{inputs.release_commit}",
            "--",
        ).stdout.splitlines()
        if line
    ]
    if changed != [f"A\t{expected_relative}"]:
        raise ReleaseEvidenceVerificationError(
            f"unexpected files changed after evaluation: {sorted(changed)}"
        )


def _project_version(pyproject_bytes: bytes) -> str:
    try:
        payload = tomllib.loads(pyproject_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseEvidenceVerificationError("committed pyproject is invalid") from exc
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ReleaseEvidenceVerificationError("committed pyproject is invalid")
    return project["version"]


def _verify_release_identity(
    inputs: VerifyInputs,
    manifest: ReleaseEvidenceManifest,
) -> None:
    parsed = parse_release_tag(inputs.tag)
    if manifest.release.tag != inputs.tag:
        raise ReleaseEvidenceVerificationError("manifest tag does not match release tag")
    if manifest.release.package_version != parsed.package_version:
        raise ReleaseEvidenceVerificationError(
            "manifest package version does not match release tag"
        )
    pyproject_bytes = _committed_blob(
        inputs.repository_root,
        inputs.release_commit,
        "pyproject.toml",
    )
    if _project_version(pyproject_bytes) != manifest.release.package_version:
        raise ReleaseEvidenceVerificationError("manifest package version does not match pyproject")
    expected_artifact_name = f"graph-rag-c9-{manifest.release.package_version}-quality-evidence"
    if manifest.transport.artifact_name != expected_artifact_name:
        raise ReleaseEvidenceVerificationError("artifact name does not match release")
    if manifest.bundle.name != f"{expected_artifact_name}.zip":
        raise ReleaseEvidenceVerificationError("bundle name does not match release")


def _verify_transport(
    manifest: ReleaseEvidenceManifest,
    metadata_path: Path,
) -> None:
    metadata_bytes = _read_limited_file(
        metadata_path,
        maximum=MAX_MEMBER_BYTES,
        name="artifact metadata",
    )
    metadata = GitHubArtifactMetadata.model_validate(
        _parse_json_object(metadata_bytes, "artifact metadata")
    )
    transport = manifest.transport
    if metadata.expired:
        raise ReleaseEvidenceVerificationError("GitHub Actions artifact is expired")
    comparisons = {
        "artifact id": (metadata.id, transport.artifact_id),
        "artifact name": (metadata.name, transport.artifact_name),
        "artifact digest": (metadata.digest, transport.artifact_digest),
        "workflow run id": (metadata.workflow_run.id, transport.workflow_run_id),
        "workflow head sha": (
            metadata.workflow_run.head_sha,
            transport.workflow_head_sha,
        ),
    }
    for name, (actual, expected) in comparisons.items():
        if actual != expected:
            raise ReleaseEvidenceVerificationError(f"{name} does not match manifest")
    if transport.workflow_head_sha != manifest.provenance.evaluated_commit:
        raise ReleaseEvidenceVerificationError("transport head does not match evaluated commit")


def _unsafe_zip_member(info: zipfile.ZipInfo) -> bool:
    name = info.filename
    path = PurePosixPath(name)
    unix_mode = (info.external_attr >> 16) & 0xFFFF
    unsafe_unix_type = (
        info.create_system == 3 and unix_mode != 0 and stat.S_IFMT(unix_mode) != stat.S_IFREG
    )
    return (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or info.is_dir()
        or bool(info.flag_bits & 0x1)
        or unsafe_unix_type
    )


def _verify_checksums(entries: Mapping[str, bytes]) -> None:
    checksums = _parse_json_object(entries["checksums.json"], "bundle checksums")
    expected_names = set(entries) - {"checksums.json"}
    if set(checksums) != expected_names:
        raise ReleaseEvidenceVerificationError("bundle checksums are inconsistent")
    for name, data in entries.items():
        if name == "checksums.json":
            continue
        identity = checksums.get(name)
        if not isinstance(identity, dict) or set(identity) != {"bytes", "sha256"}:
            raise ReleaseEvidenceVerificationError("bundle checksums are inconsistent")
        byte_count = identity.get("bytes")
        digest = identity.get("sha256")
        if (
            isinstance(byte_count, bool)
            or not isinstance(byte_count, int)
            or byte_count != len(data)
            or not isinstance(digest, str)
            or digest != _sha256(data)
        ):
            raise ReleaseEvidenceVerificationError("bundle checksums are inconsistent")


def _verify_bundle(
    manifest: ReleaseEvidenceManifest,
    bundle_path: Path,
) -> dict[str, bytes]:
    bundle_bytes = _read_limited_file(
        bundle_path,
        maximum=MAX_BUNDLE_BYTES,
        name="release evidence bundle",
    )
    if len(bundle_bytes) != manifest.bundle.bytes:
        raise ReleaseEvidenceVerificationError("bundle byte count does not match manifest")
    if _sha256(bundle_bytes) != manifest.bundle.sha256:
        raise ReleaseEvidenceVerificationError("bundle sha256 does not match manifest")
    if bundle_path.name != manifest.bundle.name:
        raise ReleaseEvidenceVerificationError("bundle name does not match manifest")

    expected = {item.path: item for item in manifest.artifacts}
    if set(expected) != set(_ARTIFACT_NAMES):
        raise ReleaseEvidenceVerificationError("bundle artifacts do not match allowed members")
    if any(expected[path].name != name for path, name in _ARTIFACT_NAMES.items()):
        raise ReleaseEvidenceVerificationError("bundle artifact identities are invalid")

    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ReleaseEvidenceVerificationError("bundle contains duplicate members")
            if set(names) != set(_ARTIFACT_NAMES):
                raise ReleaseEvidenceVerificationError(
                    "bundle members do not match allowed members"
                )
            if any(_unsafe_zip_member(info) for info in infos):
                raise ReleaseEvidenceVerificationError("bundle contains an unsafe member")
            if any(info.file_size > MAX_MEMBER_BYTES for info in infos):
                raise ReleaseEvidenceVerificationError("bundle member is too large")
            source_size = sum(info.file_size for info in infos if info.filename != "checksums.json")
            if source_size > MAX_BUNDLE_SOURCE_BYTES:
                raise ReleaseEvidenceVerificationError("bundle contents are too large")
            for info in infos:
                data = archive.read(info)
                if len(data) != info.file_size:
                    raise ReleaseEvidenceVerificationError("bundle member size is inconsistent")
                entries[info.filename] = data
    except ReleaseEvidenceVerificationError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise ReleaseEvidenceVerificationError("bundle is unreadable") from exc

    for name, data in entries.items():
        identity = expected[name]
        if len(data) != identity.bytes or _sha256(data) != identity.sha256:
            raise ReleaseEvidenceVerificationError(f"bundle member does not match manifest: {name}")
    _verify_checksums(entries)
    return entries


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseEvidenceVerificationError(f"{name} must be an object")
    return value


def _require_list(value: object, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ReleaseEvidenceVerificationError(f"{name} must be a list")
    return value


def _report_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ReleaseEvidenceVerificationError(f"{name} timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseEvidenceVerificationError(f"{name} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseEvidenceVerificationError(f"{name} timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _verify_report_timestamps(
    integration_report: Mapping[str, Any],
    live_report: Mapping[str, Any],
    manifest: ReleaseEvidenceManifest,
) -> None:
    capture_reference = _report_timestamp(
        manifest.provenance.generated_at,
        "manifest provenance",
    )
    integration_time = _report_timestamp(
        integration_report.get("generated_at"),
        "integration report",
    )
    live_time = _report_timestamp(
        live_report.get("generated_at"),
        "live quality report",
    )
    for name, report_time in (
        ("integration report", integration_time),
        ("live quality report", live_time),
    ):
        if capture_reference - report_time > _MAX_REPORT_AGE:
            raise ReleaseEvidenceVerificationError(f"{name} is more than 180 minutes old")
        if report_time - capture_reference > _MAX_REPORT_FUTURE_SKEW:
            raise ReleaseEvidenceVerificationError(f"{name} is more than 5 minutes in the future")
    if integration_time > live_time:
        raise ReleaseEvidenceVerificationError("gate report execution order is invalid")


def _summary_value_matches(actual: object, expected: object) -> bool:
    if isinstance(expected, bool):
        return isinstance(actual, bool) and actual is expected
    if isinstance(expected, int):
        return isinstance(actual, int) and not isinstance(actual, bool) and actual == expected
    if isinstance(expected, float):
        return (
            isinstance(actual, int | float)
            and not isinstance(actual, bool)
            and math.isfinite(float(actual))
            and float(actual) == expected
        )
    return type(actual) is type(expected) and actual == expected


def _verify_metric_summary(
    report_metrics: Mapping[str, Any],
    manifest_metrics: Mapping[str, Any],
    name: str,
) -> None:
    for metric_name, expected in manifest_metrics.items():
        if not _summary_value_matches(report_metrics.get(metric_name), expected):
            raise ReleaseEvidenceVerificationError(
                f"{name} metric does not match manifest: {metric_name}"
            )


def _verify_integration_details(
    report: Mapping[str, Any],
    policy: IntegrationGatePolicy,
    manifest: ReleaseEvidenceManifest,
) -> None:
    metrics = manifest.integration.metrics
    if metrics.failed_count or metrics.blocked_count:
        raise ReleaseEvidenceVerificationError(
            "integration report contains failed or blocked checks"
        )
    if not (metrics.case_count == metrics.executed_case_count == metrics.observation_count):
        raise ReleaseEvidenceVerificationError("integration cases were not all executed")
    if metrics.case_count != len(policy.live_cases):
        raise ReleaseEvidenceVerificationError(
            "integration policy case count does not match manifest"
        )

    checks = _require_list(report.get("checks"), "integration checks")
    statuses: list[str] = []
    for value in checks:
        check = _require_mapping(value, "integration check")
        status = check.get("status")
        passed = check.get("passed")
        if status not in _GATE_STATUSES or not isinstance(passed, bool):
            raise ReleaseEvidenceVerificationError("integration check details are invalid")
        if passed is not (status == "passed"):
            raise ReleaseEvidenceVerificationError("integration check details are invalid")
        statuses.append(status)
    if (
        len(checks) != metrics.check_count
        or statuses.count("failed") != metrics.failed_count
        or statuses.count("blocked") != metrics.blocked_count
        or any(status != "passed" for status in statuses)
    ):
        raise ReleaseEvidenceVerificationError(
            "integration check details do not match manifest counts"
        )

    cases = _require_list(report.get("cases"), "integration cases")
    expected_case_ids = [case.case_id for case in policy.live_cases]
    actual_case_ids: list[object] = []
    executed_count = 0
    observation_count = 0
    for value in cases:
        case = _require_mapping(value, "integration case")
        actual_case_ids.append(case.get("case_id"))
        executed = case.get("executed")
        observed = case.get("has_observation")
        executed_count += int(executed is True)
        observation_count += int(observed is True)
        if executed is not True or observed is not True or case.get("status") != "passed":
            raise ReleaseEvidenceVerificationError("integration cases were not all executed")
    if (
        len(cases) != metrics.case_count
        or executed_count != metrics.executed_case_count
        or observation_count != metrics.observation_count
        or actual_case_ids != expected_case_ids
        or len(set(actual_case_ids)) != len(actual_case_ids)
    ):
        raise ReleaseEvidenceVerificationError(
            "integration case details do not match manifest counts"
        )


def _parse_manual_review_jsonl(value: bytes) -> list[dict[str, Any]]:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceVerificationError("manual review JSONL is not UTF-8") from exc
    if not text:
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ReleaseEvidenceVerificationError(
                f"manual review JSONL contains a blank line: {line_number}"
            )
        rows.append(
            _parse_json_object(
                line.encode("utf-8"),
                f"manual review JSONL row {line_number}",
            )
        )
    return rows


def _verify_quality_details(
    report: Mapping[str, Any],
    policy: LiveQualityGatePolicy,
    manifest: ReleaseEvidenceManifest,
    sample_bytes: bytes,
) -> None:
    case_count = manifest.quality.metrics.case_count
    if case_count != len(policy.cases) or case_count != manifest.dataset.case_count:
        raise ReleaseEvidenceVerificationError("dataset case count does not match manifest")
    cases = _require_list(report.get("cases"), "live quality cases")
    actual_case_ids = [_require_mapping(case, "live quality case").get("case_id") for case in cases]
    if len(cases) != case_count or actual_case_ids != [case.case_id for case in policy.cases]:
        raise ReleaseEvidenceVerificationError(
            "live quality case details do not match manifest count"
        )
    sample_count = report.get("manual_review_sample_count")
    report_rows = _require_list(report.get("manual_review_sample"), "manual review sample")
    jsonl_rows = _parse_manual_review_jsonl(sample_bytes)
    if (
        isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count != manifest.quality.manual_review_sample_count
        or sample_count != len(report_rows)
        or sample_count != len(jsonl_rows)
        or [_canonical_json(row) for row in report_rows]
        != [_canonical_json(row) for row in jsonl_rows]
    ):
        raise ReleaseEvidenceVerificationError(
            "manual review sample does not match manifest and JSONL"
        )
    sampled_cases = [case for case in policy.cases if case.manual_review.sample]
    if [row.get("case_id") for row in jsonl_rows] != [case.case_id for case in sampled_cases]:
        raise ReleaseEvidenceVerificationError("manual review sample does not match policy")


def _merge_nested(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        if isinstance(value, Mapping):
            child = target.get(key_text)
            if not isinstance(child, dict):
                child = {}
                target[key_text] = child
            _merge_nested(child, value)
        else:
            target[key_text] = value


def _parse_profile(value: bytes, name: str) -> dict[str, Any]:
    try:
        payload = tomllib.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseEvidenceVerificationError(f"committed profile is invalid: {name}") from exc
    if not isinstance(payload, dict):
        raise ReleaseEvidenceVerificationError(f"committed profile is invalid: {name}")
    return payload


def _verify_profile(
    manifest: ReleaseEvidenceManifest,
    repository_root: Path,
) -> None:
    profile = manifest.runtime.profile
    if not _PROFILE_NAME_RE.fullmatch(profile.name):
        raise ReleaseEvidenceVerificationError("profile name is invalid")
    expected_path = (
        "profiles/base.toml" if profile.name == "base" else f"profiles/{profile.name}.toml"
    )
    if profile.path != expected_path:
        raise ReleaseEvidenceVerificationError("profile path does not match manifest")
    evaluated_commit = manifest.provenance.evaluated_commit
    base_bytes = _committed_blob(repository_root, evaluated_commit, "profiles/base.toml")
    selected_bytes = (
        base_bytes
        if expected_path == "profiles/base.toml"
        else _committed_blob(repository_root, evaluated_commit, expected_path)
    )
    resolved: dict[str, Any] = {}
    _merge_nested(resolved, _parse_profile(base_bytes, "profiles/base.toml"))
    if expected_path != "profiles/base.toml":
        _merge_nested(resolved, _parse_profile(selected_bytes, expected_path))
    resolved_sha256 = _sha256(
        json.dumps(resolved, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    if resolved_sha256 != profile.resolved_sha256:
        raise ReleaseEvidenceVerificationError(
            "resolved profile hash does not match evaluated commit"
        )


def _verify_semantics(
    manifest: ReleaseEvidenceManifest,
    entries: dict[str, bytes],
    repository_root: Path,
) -> None:
    integration_report = _parse_json_object(
        entries["integration_gate/report.json"],
        "integration report",
    )
    live_report = _parse_json_object(
        entries["live_quality_gate/report.json"],
        "live quality report",
    )
    if set(integration_report) != _INTEGRATION_REPORT_KEYS:
        raise ReleaseEvidenceVerificationError("integration report schema is invalid")
    if set(live_report) != _LIVE_REPORT_KEYS:
        raise ReleaseEvidenceVerificationError("live quality report schema is invalid")
    if (
        manifest.schema_version != MANIFEST_SCHEMA_VERSION
        or live_report.get("schema_version") != 2
        or manifest.quality.report_schema_version != 2
    ):
        raise ReleaseEvidenceVerificationError("live quality report schema is invalid")
    _verify_report_timestamps(integration_report, live_report, manifest)
    integration_policy_payload = _parse_json_object(
        entries["policies/integration_gate.json"],
        "integration policy",
    )
    live_policy_payload = _parse_json_object(
        entries["policies/live_quality_gate.json"],
        "live quality policy",
    )
    integration_policy = IntegrationGatePolicy.model_validate(integration_policy_payload)
    live_policy = LiveQualityGatePolicy.model_validate(live_policy_payload)

    if manifest.integration.passed is not True:
        raise ReleaseEvidenceVerificationError("manifest integration passed must be true")
    if manifest.quality.passed is not True:
        raise ReleaseEvidenceVerificationError("manifest quality passed must be true")
    for name, report, expected in (
        ("integration", integration_report, manifest.integration.passed),
        ("quality", live_report, manifest.quality.passed),
    ):
        report_passed = report.get("passed")
        if not isinstance(report_passed, bool) or report_passed is not expected:
            raise ReleaseEvidenceVerificationError(
                f"bundle contains a failed gate report: {name} passed does not match manifest"
            )
        if report_passed is not True:
            raise ReleaseEvidenceVerificationError("bundle contains a failed gate report")

    integration_metrics = _require_mapping(
        integration_report.get("metrics"),
        "integration metrics",
    )
    quality_metrics = _require_mapping(live_report.get("metrics"), "live quality metrics")
    _verify_metric_summary(
        integration_metrics,
        manifest.integration.metrics.model_dump(),
        "integration",
    )
    _verify_metric_summary(
        quality_metrics,
        manifest.quality.metrics.model_dump(),
        "live quality",
    )
    if integration_report.get("schema_version") != manifest.integration.report_schema_version:
        raise ReleaseEvidenceVerificationError("integration schema version does not match manifest")
    if integration_report.get("generated_at") != manifest.integration.generated_at:
        raise ReleaseEvidenceVerificationError("integration timestamp does not match manifest")
    if live_report.get("schema_version") != manifest.quality.report_schema_version:
        raise ReleaseEvidenceVerificationError(
            "live quality schema version does not match manifest"
        )
    if live_report.get("generated_at") != manifest.quality.generated_at:
        raise ReleaseEvidenceVerificationError("live quality timestamp does not match manifest")
    if live_report.get("top_k") != live_policy.top_k:
        raise ReleaseEvidenceVerificationError("live quality top_k does not match policy")

    _verify_integration_details(integration_report, integration_policy, manifest)
    _verify_quality_details(
        live_report,
        live_policy,
        manifest,
        entries["live_quality_gate/manual_review_sample.jsonl"],
    )
    evaluated_commit = manifest.provenance.evaluated_commit
    if entries["policies/integration_gate.json"] != _committed_blob(
        repository_root,
        evaluated_commit,
        "eval/integration_gate.json",
    ):
        raise ReleaseEvidenceVerificationError("integration policy does not match evaluated commit")
    if entries["policies/live_quality_gate.json"] != _committed_blob(
        repository_root,
        evaluated_commit,
        "eval/live_quality_gate.json",
    ):
        raise ReleaseEvidenceVerificationError(
            "live quality policy does not match evaluated commit"
        )
    if live_policy.schema_version != manifest.dataset.schema_version:
        raise ReleaseEvidenceVerificationError("dataset schema version does not match manifest")
    if len(live_policy.cases) != manifest.dataset.case_count:
        raise ReleaseEvidenceVerificationError("dataset case count does not match manifest")
    if _sha256(entries["policies/live_quality_gate.json"]) != manifest.dataset.sha256:
        raise ReleaseEvidenceVerificationError("dataset sha256 does not match manifest")

    if entries["integration_gate/summary.md"] != render_integration_summary(integration_report):
        raise ReleaseEvidenceVerificationError("integration summary does not match report")
    if entries["live_quality_gate/summary.md"] != render_live_quality_summary(live_report):
        raise ReleaseEvidenceVerificationError("live quality summary does not match report")

    runtime = RuntimeIdentity.model_validate(
        _parse_json_object(entries["runtime/diagnostics.json"], "runtime identity")
    )
    knowledge = KnowledgeBaseIdentity.model_validate(
        _parse_json_object(
            entries["runtime/artifact_manifest.json"],
            "knowledge-base identity",
        )
    )
    if runtime != manifest.runtime:
        raise ReleaseEvidenceVerificationError("runtime identity does not match manifest")
    if knowledge != manifest.knowledge_base:
        raise ReleaseEvidenceVerificationError("knowledge-base identity does not match manifest")
    live_target = _require_mapping(live_report.get("target"), "live quality target")
    integration_target = _require_mapping(
        integration_report.get("target"),
        "integration target",
    )
    if live_target != runtime.target.model_dump():
        raise ReleaseEvidenceVerificationError("runtime target does not match live report")
    if integration_target.get("api_host") != runtime.target.api_host:
        raise ReleaseEvidenceVerificationError("runtime target does not match integration report")
    _verify_profile(manifest, repository_root)


def verify_release_evidence(inputs: VerifyInputs) -> ReleaseEvidenceManifest:
    try:
        manifest_bytes = _read_limited_file(
            inputs.manifest_path,
            maximum=MAX_MEMBER_BYTES,
            name="release manifest",
        )
        manifest = ReleaseEvidenceManifest.model_validate(
            _parse_json_object(manifest_bytes, "release manifest")
        )
        if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
            raise ReleaseEvidenceVerificationError("release manifest schema is invalid")
        _verify_git(inputs, manifest, manifest_bytes)
        _verify_release_identity(inputs, manifest)
        _verify_transport(manifest, inputs.artifact_metadata_path)
        entries = _verify_bundle(manifest, inputs.bundle_path)
        _verify_semantics(manifest, entries, inputs.repository_root)
        return manifest
    except ReleaseEvidenceVerificationError:
        raise
    except (KeyError, OSError, TypeError, ValueError, ValidationError) as exc:
        raise ReleaseEvidenceVerificationError(
            "release evidence verification input is invalid"
        ) from exc
