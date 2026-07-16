from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

from pydantic import ValidationError

from rag_modules.interfaces.api.diagnostics_models import DiagnosticsResponseModel
from rag_modules.kernel.artifacts import ArtifactManifest, artifact_health
from scripts.integration_gate.models import IntegrationGatePolicy
from scripts.live_quality_gate.models import LiveQualityGatePolicy
from scripts.validate_release_tag import parse_release_tag

from .models import (
    BundleIdentity,
    CaptureReceipt,
    DatasetIdentity,
    FileIdentity,
    IntegrationEvidence,
    IntegrationMetrics,
    KnowledgeBaseIdentity,
    ModelSuiteIdentity,
    ProfileIdentity,
    Provenance,
    QualityEvidence,
    QualityMetrics,
    ReleaseIdentity,
    RuntimeIdentity,
    TargetIdentity,
    write_evidence_model,
)

MAX_MEMBER_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_SOURCE_BYTES = 50 * 1024 * 1024
_READ_CHUNK_BYTES = 64 * 1024
_CREDENTIAL_KEY_RE = re.compile(
    r"^(?:api[_-]?(?:key|token)|access[_-]?token|refresh[_-]?token|session[_-]?token|"
    r"authorization|password|passwd|bearer[_-]?token|client[_-]?secret|secret[_-]?key|"
    r"private[_-]?key|aws[_-]?secret[_-]?access[_-]?key|credentials?|raw[_-]?exception|"
    r"traceback)$",
    re.IGNORECASE,
)
_BEARER_VALUE_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*\b", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"\bAuthorization\s*:", re.IGNORECASE)
_ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/]")
_ABSOLUTE_WINDOWS_UNC_PATH_RE = re.compile(r"(?:^|[\s\"'=(])\\\\[^\\/\s]+\\[^\\/\s]+")
_ABSOLUTE_UNIX_PATH_RE = re.compile(
    r"(?:^|[\s\"'=(])/(?:home|Users|var|tmp|opt|workspace|root|etc|srv|mnt)/"
)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


class ReleaseEvidenceCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureInputs:
    repository_root: Path
    repository: str
    package_version: str
    tag: str
    evaluated_commit: str
    integration_policy_path: Path
    live_quality_policy_path: Path
    integration_report_path: Path
    live_quality_report_path: Path
    diagnostics_path: Path
    artifact_manifest_path: Path
    judge_model: str
    output_dir: Path


@dataclass(frozen=True)
class CaptureOutputs:
    receipt_path: Path
    bundle_path: Path


class _SourceSnapshots:
    def __init__(self) -> None:
        self._by_path: dict[Path, bytes] = {}
        self._total_bytes = 0

    def read(self, path: Path) -> bytes:
        identity = path.resolve()
        cached = self._by_path.get(identity)
        if cached is not None:
            return cached
        data = _read_bytes(path)
        self._total_bytes += len(data)
        if self._total_bytes > MAX_BUNDLE_SOURCE_BYTES:
            raise ReleaseEvidenceCaptureError("release evidence source snapshot is too large")
        self._by_path[identity] = data
        return data


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        chunks: list[bytes] = []
        captured_bytes = 0
        with path.open("rb") as source:
            while captured_bytes <= MAX_MEMBER_BYTES:
                requested = min(
                    _READ_CHUNK_BYTES,
                    MAX_MEMBER_BYTES + 1 - captured_bytes,
                )
                chunk = source.read(requested)
                if not chunk:
                    break
                chunks.append(chunk)
                captured_bytes += len(chunk)
    except OSError as exc:
        raise ReleaseEvidenceCaptureError(
            f"release evidence member could not be read: {path.name}"
        ) from exc
    data = b"".join(chunks)
    if len(data) > MAX_MEMBER_BYTES:
        raise ReleaseEvidenceCaptureError(f"release evidence member is too large: {path.name}")
    return data


def _parse_json(data: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceCaptureError(f"release evidence JSON is invalid: {name}") from exc
    if not isinstance(value, dict):
        raise ReleaseEvidenceCaptureError(f"release evidence JSON must be an object: {name}")
    return value


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


def _git(repository_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed") from exc
    if completed.returncode != 0:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed")
    return completed.stdout.strip()


def _git_bytes(repository_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed") from exc
    if completed.returncode != 0:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed")
    return completed.stdout


def _project_version(pyproject_bytes: bytes) -> str:
    try:
        payload = tomllib.loads(pyproject_bytes.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseEvidenceCaptureError("package metadata is invalid") from exc
    project = payload.get("project")
    if not isinstance(project, dict) or not isinstance(project.get("version"), str):
        raise ReleaseEvidenceCaptureError("package metadata is invalid")
    return project["version"]


def _validate_checkout(inputs: CaptureInputs) -> None:
    head = _git(inputs.repository_root, "rev-parse", "HEAD")
    if head != inputs.evaluated_commit:
        raise ReleaseEvidenceCaptureError("evaluated commit does not match checkout HEAD")
    if _git(inputs.repository_root, "status", "--porcelain"):
        raise ReleaseEvidenceCaptureError("release evidence checkout must be clean")
    try:
        parsed_tag = parse_release_tag(inputs.tag)
    except ValueError as exc:
        raise ReleaseEvidenceCaptureError("release tag is invalid") from exc
    if parsed_tag.package_version != inputs.package_version:
        raise ReleaseEvidenceCaptureError("release version and tag do not match")
    canonical_policies = {
        inputs.integration_policy_path.resolve(): (
            inputs.repository_root / "eval" / "integration_gate.json"
        ).resolve(),
        inputs.live_quality_policy_path.resolve(): (
            inputs.repository_root / "eval" / "live_quality_gate.json"
        ).resolve(),
    }
    if any(actual != expected for actual, expected in canonical_policies.items()):
        raise ReleaseEvidenceCaptureError("release evidence must use canonical repository policies")


def _committed_regular_blob(
    repository_root: Path,
    evaluated_commit: str,
    relative_path: str,
) -> tuple[str, bytes]:
    tree_entry = _git(
        repository_root,
        "ls-tree",
        evaluated_commit,
        "--",
        relative_path,
    )
    try:
        metadata, listed_path = tree_entry.split("\t", 1)
        mode, object_type, object_id = metadata.split()
    except ValueError as exc:
        raise ReleaseEvidenceCaptureError(
            f"release evidence source is not an ordinary committed file: {relative_path}"
        ) from exc
    if listed_path != relative_path or mode not in {"100644", "100755"} or object_type != "blob":
        raise ReleaseEvidenceCaptureError(
            f"release evidence source is not an ordinary committed file: {relative_path}"
        )
    try:
        blob_size = int(_git(repository_root, "cat-file", "-s", object_id))
    except ValueError as exc:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed") from exc
    if blob_size > MAX_MEMBER_BYTES:
        raise ReleaseEvidenceCaptureError(
            f"release evidence member is too large: {PurePosixPath(relative_path).name}"
        )
    data = _git_bytes(repository_root, "cat-file", "blob", object_id)
    if len(data) != blob_size:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed")
    return object_id, data


def _git_clean_object_id(
    repository_root: Path,
    relative_path: str,
    data: bytes,
) -> str:
    try:
        completed = subprocess.run(
            ["git", "hash-object", f"--path={relative_path}", "--stdin"],
            cwd=repository_root,
            input=data,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed") from exc
    if completed.returncode != 0:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed")
    try:
        return completed.stdout.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed") from exc


def _bind_commit_source(
    inputs: CaptureInputs,
    snapshots: _SourceSnapshots,
    relative_path: str,
) -> bytes:
    object_id, committed = _committed_regular_blob(
        inputs.repository_root,
        inputs.evaluated_commit,
        relative_path,
    )
    working_path = inputs.repository_root / PurePosixPath(relative_path)
    if working_path.is_symlink():
        raise ReleaseEvidenceCaptureError(
            f"release evidence source is not an ordinary committed file: {relative_path}"
        )
    captured = snapshots.read(working_path)
    if captured != committed and (
        _git_clean_object_id(inputs.repository_root, relative_path, captured) != object_id
    ):
        raise ReleaseEvidenceCaptureError(
            f"release evidence source does not match evaluated commit: {relative_path}"
        )
    return committed


def _require_mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReleaseEvidenceCaptureError(f"{name} must be an object")
    return value


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ReleaseEvidenceCaptureError(f"{name} is invalid")
    return value


def _require_int(value: object, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReleaseEvidenceCaptureError(f"{name} is invalid")
    if positive and value <= 0:
        raise ReleaseEvidenceCaptureError(f"{name} must be positive")
    return value


def _require_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ReleaseEvidenceCaptureError(f"{name} is invalid")
    result = float(value)
    if not (float("-inf") < result < float("inf")):
        raise ReleaseEvidenceCaptureError(f"{name} is invalid")
    return result


def _report_member(report_path: Path, relative_name: object) -> Path:
    if not isinstance(relative_name, str) or not relative_name:
        raise ReleaseEvidenceCaptureError("report artifact name is invalid")
    candidate = (report_path.parent / relative_name).resolve()
    parent = report_path.parent.resolve()
    if candidate.parent != parent:
        raise ReleaseEvidenceCaptureError("report artifact escaped its output directory")
    if not candidate.is_file():
        raise ReleaseEvidenceCaptureError(f"report artifact is missing: {relative_name}")
    return candidate


def _load_artifact_manifest(payload: Mapping[str, Any]) -> ArtifactManifest:
    integer_fields = (
        "manifest_version",
        "total_documents",
        "total_chunks",
        "vector_rows",
    )
    string_fields = (
        "schema_version",
        "stage",
        "published_at",
        "graph_signature",
        "document_signature",
        "embedding_signature",
        "index_signature",
        "index_version",
        "collection_name",
    )
    for field_name in integer_fields:
        value = payload.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ReleaseEvidenceCaptureError(f"artifact manifest field is invalid: {field_name}")
    for field_name in string_fields:
        if not isinstance(payload.get(field_name), str):
            raise ReleaseEvidenceCaptureError(f"artifact manifest field is invalid: {field_name}")
    if not isinstance(payload.get("build_metadata"), dict):
        raise ReleaseEvidenceCaptureError("artifact manifest build_metadata is invalid")
    return ArtifactManifest.from_dict(payload)


def _project_integration(
    report: Mapping[str, Any],
    policy: IntegrationGatePolicy,
) -> IntegrationEvidence:
    if _require_bool(report.get("passed"), "integration passed") is not True:
        raise ReleaseEvidenceCaptureError("integration report did not pass")
    metrics = _require_mapping(report.get("metrics"), "integration metrics")
    projected = IntegrationMetrics(
        check_count=_require_int(
            metrics.get("check_count"), "integration check_count", positive=True
        ),
        failed_count=_require_int(metrics.get("failed_count"), "integration failed_count"),
        blocked_count=_require_int(metrics.get("blocked_count"), "integration blocked_count"),
        case_count=_require_int(metrics.get("case_count"), "integration case_count", positive=True),
        executed_case_count=_require_int(
            metrics.get("executed_case_count"),
            "integration executed_case_count",
            positive=True,
        ),
        observation_count=_require_int(
            metrics.get("observation_count"),
            "integration observation_count",
            positive=True,
        ),
    )
    if projected.failed_count or projected.blocked_count:
        raise ReleaseEvidenceCaptureError("integration report contains failed or blocked checks")
    if projected.case_count != projected.executed_case_count:
        raise ReleaseEvidenceCaptureError("integration cases were not all executed")
    if projected.case_count != len(policy.live_cases):
        raise ReleaseEvidenceCaptureError("integration policy and report case counts differ")
    return IntegrationEvidence(
        passed=True,
        report_schema_version=_require_int(
            report.get("schema_version"),
            "integration report schema_version",
            positive=True,
        ),
        generated_at=str(report.get("generated_at") or ""),
        metrics=projected,
    )


def _project_quality(
    report: Mapping[str, Any],
    policy: LiveQualityGatePolicy,
) -> QualityEvidence:
    if _require_bool(report.get("passed"), "live quality passed") is not True:
        raise ReleaseEvidenceCaptureError("live quality report did not pass")
    metrics = _require_mapping(report.get("metrics"), "live quality metrics")
    case_count = _require_int(
        metrics.get("case_count"),
        "live quality case count",
        positive=True,
    )
    if case_count < policy.thresholds.minimum_case_count:
        raise ReleaseEvidenceCaptureError("live quality case count is below policy minimum")
    if case_count != len(policy.cases):
        raise ReleaseEvidenceCaptureError("live quality policy and report case counts differ")

    def metric(name: str) -> float:
        return _require_float(metrics.get(name), f"live quality metric {name}")

    projected = QualityMetrics(
        case_count=case_count,
        pass_rate=metric("pass_rate"),
        deterministic_pass_rate=metric("deterministic_pass_rate"),
        judge_pass_rate=metric("judge_pass_rate"),
        recall_at_k=metric("recall_at_k"),
        mrr=metric("mrr"),
        ndcg_at_k=metric("ndcg_at_k"),
        fallback_rate=metric("fallback_rate"),
        retrieval_degradation_rate=metric("retrieval_degradation_rate"),
        p95_latency_ms=metric("p95_latency_ms"),
        estimated_cost_usd=metric("estimated_cost_usd"),
    )
    return QualityEvidence(
        passed=True,
        report_schema_version=_require_int(
            report.get("schema_version"),
            "live quality report schema_version",
            positive=True,
        ),
        generated_at=str(report.get("generated_at") or ""),
        metrics=projected,
        manual_review_sample_count=_require_int(
            report.get("manual_review_sample_count"),
            "manual review sample count",
        ),
    )


def _profile_path(repository_root: Path, profile_name: str) -> Path:
    if not _PROFILE_NAME_RE.fullmatch(profile_name):
        raise ReleaseEvidenceCaptureError("artifact profile name is invalid")
    filename = "base.toml" if profile_name == "base" else f"{profile_name}.toml"
    path = repository_root / "profiles" / filename
    if not path.is_file():
        raise ReleaseEvidenceCaptureError("artifact profile does not exist in repository")
    return path


def _merge_profile_payload(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        if isinstance(value, Mapping):
            child = target.get(key_text)
            if not isinstance(child, dict):
                child = {}
                target[key_text] = child
            _merge_profile_payload(child, value)
        else:
            target[key_text] = value


def _parse_profile(data: bytes, name: str) -> dict[str, Any]:
    try:
        payload = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseEvidenceCaptureError(f"artifact profile is invalid: {name}") from exc
    if not isinstance(payload, dict):
        raise ReleaseEvidenceCaptureError(f"artifact profile is invalid: {name}")
    return payload


def _resolved_profile_hash(
    base_bytes: bytes,
    selected_bytes: bytes,
    *,
    selected_is_base: bool,
) -> str:
    merged: dict[str, Any] = {}
    _merge_profile_payload(merged, _parse_profile(base_bytes, "base.toml"))
    if not selected_is_base:
        _merge_profile_payload(merged, _parse_profile(selected_bytes, "selected profile"))
    return _sha256_bytes(json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def _artifact_profile_identity(
    artifact_manifest: ArtifactManifest,
    repository_root: Path,
) -> tuple[str, Path, str]:
    profile_data = _require_mapping(
        artifact_manifest.build_metadata.get("config_profile"),
        "artifact config profile",
    )
    profile_name = str(profile_data.get("name") or "")
    profile_path = _profile_path(repository_root, profile_name)
    declared_path = profile_data.get("path")
    if not isinstance(declared_path, str) or not declared_path.strip():
        raise ReleaseEvidenceCaptureError("artifact profile path is invalid")
    declared_profile_path = Path(declared_path)
    if not declared_profile_path.is_absolute():
        declared_profile_path = repository_root / declared_profile_path
    if declared_profile_path.resolve() != profile_path.resolve():
        raise ReleaseEvidenceCaptureError("artifact profile path does not match repository")
    profile_hash = str(profile_data.get("hash") or "")
    return profile_name, profile_path, profile_hash


def _project_runtime(
    diagnostics_payload: Mapping[str, Any],
    *,
    judge_model: str,
    target: Mapping[str, Any],
    profile_name: str,
    profile_path: str,
    profile_hash: str,
) -> RuntimeIdentity:
    try:
        diagnostics = DiagnosticsResponseModel.model_validate(diagnostics_payload).diagnostics
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("runtime diagnostics are invalid") from exc
    if not (
        diagnostics.artifacts_ready
        and diagnostics.system_ready
        and diagnostics.retrieval_engines_initialized
    ):
        raise ReleaseEvidenceCaptureError("runtime diagnostics are not ready")
    return RuntimeIdentity(
        target=TargetIdentity(
            api_host=str(target.get("api_host") or ""),
            judge_host=str(target.get("judge_host") or ""),
        ),
        profile=ProfileIdentity(
            name=profile_name,
            path=profile_path,
            resolved_sha256=profile_hash,
        ),
        models=ModelSuiteIdentity(
            llm=diagnostics.llm_model,
            embedding=diagnostics.embedding_model,
            rerank=diagnostics.rerank_model,
            judge=judge_model,
        ),
    )


def _project_knowledge_base(manifest: ArtifactManifest) -> KnowledgeBaseIdentity:
    if not manifest.is_ready or artifact_health(manifest) != "ready":
        raise ReleaseEvidenceCaptureError("knowledge artifact is not ready")
    for field_name in (
        "graph_signature",
        "document_signature",
        "embedding_signature",
        "index_signature",
        "index_version",
        "collection_name",
        "published_at",
    ):
        if not str(getattr(manifest, field_name) or "").strip():
            raise ReleaseEvidenceCaptureError(f"knowledge artifact field is missing: {field_name}")
    return KnowledgeBaseIdentity(
        schema_version=manifest.schema_version,
        manifest_version=manifest.manifest_version,
        stage="ready",
        health="ready",
        published_at=manifest.published_at,
        index_version=manifest.index_version,
        collection_name=manifest.collection_name,
        graph_signature=manifest.graph_signature,
        document_signature=manifest.document_signature,
        embedding_signature=manifest.embedding_signature,
        index_signature=manifest.index_signature,
        total_documents=manifest.total_documents,
        total_chunks=manifest.total_chunks,
        vector_rows=manifest.vector_rows,
    )


def _credential_url_present(value: str) -> bool:
    for match in _URL_RE.finditer(value):
        url = match.group(0).rstrip(".,);]")
        try:
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None:
                return True
            if any(_CREDENTIAL_KEY_RE.fullmatch(key) for key, _ in parse_qsl(parsed.query)):
                return True
        except ValueError:
            continue
    return False


def _sensitive_text_present(value: str) -> bool:
    return bool(
        _BEARER_VALUE_RE.search(value)
        or _AUTH_HEADER_RE.search(value)
        or _ABSOLUTE_WINDOWS_PATH_RE.search(value)
        or _ABSOLUTE_WINDOWS_UNC_PATH_RE.search(value)
        or _ABSOLUTE_UNIX_PATH_RE.search(value)
        or _credential_url_present(value)
    )


def _scan_json(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            if _CREDENTIAL_KEY_RE.fullmatch(key_text):
                raise ReleaseEvidenceCaptureError(
                    f"sensitive release evidence key at {path}.{key_text}"
                )
            _scan_json(item, f"{path}.{key_text}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json(item, f"{path}[{index}]")
        return
    if isinstance(value, str) and _sensitive_text_present(value):
        raise ReleaseEvidenceCaptureError(f"sensitive release evidence value at {path}")


def _scan_source(name: str, data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError(f"release evidence text is invalid: {name}") from exc
    if name.endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ReleaseEvidenceCaptureError(f"release evidence JSON is invalid: {name}") from exc
        _scan_json(payload)
        return
    if name.endswith(".jsonl"):
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ReleaseEvidenceCaptureError(
                    f"release evidence JSONL is invalid: {name}:{line_number}"
                ) from exc
            _scan_json(payload, f"{name}:{line_number}")
        return
    if _sensitive_text_present(text):
        raise ReleaseEvidenceCaptureError(f"sensitive release evidence value in {name}")


def _file_identity(name: str, path: str, data: bytes) -> FileIdentity:
    return FileIdentity(name=name, path=path, bytes=len(data), sha256=_sha256_bytes(data))


def _write_deterministic_zip(path: Path, entries: Mapping[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in sorted(entries):
            pure_path = PurePosixPath(name)
            if pure_path.is_absolute() or ".." in pure_path.parts:
                raise ReleaseEvidenceCaptureError("invalid bundle member path")
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIMESTAMP)
            info.create_system = 3
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise ReleaseEvidenceCaptureError("release evidence bundle could not be read") from exc
    return digest.hexdigest()


def capture_release_evidence(
    inputs: CaptureInputs,
    *,
    generated_at: str | None = None,
) -> CaptureOutputs:
    _validate_checkout(inputs)
    snapshots = _SourceSnapshots()

    pyproject_bytes = _bind_commit_source(inputs, snapshots, "pyproject.toml")
    if _project_version(pyproject_bytes) != inputs.package_version:
        raise ReleaseEvidenceCaptureError("package version does not match checkout")
    integration_policy_bytes = _bind_commit_source(
        inputs,
        snapshots,
        "eval/integration_gate.json",
    )
    live_policy_bytes = _bind_commit_source(
        inputs,
        snapshots,
        "eval/live_quality_gate.json",
    )
    base_profile_bytes = _bind_commit_source(inputs, snapshots, "profiles/base.toml")

    integration_report_bytes = snapshots.read(inputs.integration_report_path)
    live_report_bytes = snapshots.read(inputs.live_quality_report_path)
    diagnostics_bytes = snapshots.read(inputs.diagnostics_path)
    artifact_bytes = snapshots.read(inputs.artifact_manifest_path)

    integration_report = _parse_json(
        integration_report_bytes,
        inputs.integration_report_path.name,
    )
    live_report = _parse_json(live_report_bytes, inputs.live_quality_report_path.name)
    integration_policy_payload = _parse_json(
        integration_policy_bytes,
        inputs.integration_policy_path.name,
    )
    live_policy_payload = _parse_json(
        live_policy_bytes,
        inputs.live_quality_policy_path.name,
    )
    diagnostics_payload = _parse_json(diagnostics_bytes, inputs.diagnostics_path.name)
    artifact_payload = _parse_json(artifact_bytes, inputs.artifact_manifest_path.name)

    integration_artifacts = _require_mapping(
        integration_report.get("artifacts"),
        "integration artifacts",
    )
    live_artifacts = _require_mapping(live_report.get("artifacts"), "live quality artifacts")
    if (
        _report_member(
            inputs.integration_report_path,
            integration_artifacts.get("report_json"),
        )
        != inputs.integration_report_path.resolve()
    ):
        raise ReleaseEvidenceCaptureError("integration report identity is invalid")
    if (
        _report_member(
            inputs.live_quality_report_path,
            live_artifacts.get("report_json"),
        )
        != inputs.live_quality_report_path.resolve()
    ):
        raise ReleaseEvidenceCaptureError("live quality report identity is invalid")
    integration_summary_bytes = snapshots.read(
        _report_member(
            inputs.integration_report_path,
            integration_artifacts.get("summary_md"),
        )
    )
    live_summary_bytes = snapshots.read(
        _report_member(
            inputs.live_quality_report_path,
            live_artifacts.get("summary_md"),
        )
    )
    manual_review_bytes = snapshots.read(
        _report_member(
            inputs.live_quality_report_path,
            live_artifacts.get("manual_review_sample_jsonl"),
        )
    )

    try:
        integration_policy = IntegrationGatePolicy.model_validate(integration_policy_payload)
        live_policy = LiveQualityGatePolicy.model_validate(live_policy_payload)
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("release evidence policy is invalid") from exc
    artifact_manifest = _load_artifact_manifest(artifact_payload)
    profile_name, profile_path, declared_profile_hash = _artifact_profile_identity(
        artifact_manifest,
        inputs.repository_root,
    )
    selected_profile_relative_path = profile_path.relative_to(inputs.repository_root).as_posix()
    selected_profile_bytes = (
        base_profile_bytes
        if selected_profile_relative_path == "profiles/base.toml"
        else _bind_commit_source(inputs, snapshots, selected_profile_relative_path)
    )
    resolved_profile_hash = _resolved_profile_hash(
        base_profile_bytes,
        selected_profile_bytes,
        selected_is_base=selected_profile_relative_path == "profiles/base.toml",
    )
    if not declared_profile_hash or declared_profile_hash != resolved_profile_hash:
        raise ReleaseEvidenceCaptureError("artifact profile hash does not match repository")

    try:
        integration = _project_integration(integration_report, integration_policy)
        quality = _project_quality(live_report, live_policy)
        target = _require_mapping(live_report.get("target"), "live quality target")
        runtime = _project_runtime(
            diagnostics_payload,
            judge_model=inputs.judge_model,
            target=target,
            profile_name=profile_name,
            profile_path=selected_profile_relative_path,
            profile_hash=resolved_profile_hash,
        )
        knowledge_base = _project_knowledge_base(artifact_manifest)
        dataset = DatasetIdentity(
            path="eval/live_quality_gate.json",
            schema_version=live_policy.schema_version,
            case_count=len(live_policy.cases),
            sha256=_sha256_bytes(live_policy_bytes),
        )
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("release evidence projection is invalid") from exc

    try:
        manual_review_text = manual_review_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError("manual review sample is not UTF-8") from exc
    manual_review_line_count = sum(bool(line.strip()) for line in manual_review_text.splitlines())
    if manual_review_line_count != quality.manual_review_sample_count:
        raise ReleaseEvidenceCaptureError("manual review sample count does not match JSONL")

    source_entries = {
        "integration_gate/report.json": integration_report_bytes,
        "integration_gate/summary.md": integration_summary_bytes,
        "live_quality_gate/report.json": live_report_bytes,
        "live_quality_gate/summary.md": live_summary_bytes,
        "live_quality_gate/manual_review_sample.jsonl": manual_review_bytes,
        "runtime/diagnostics.json": _canonical_json(runtime.model_dump(mode="json")),
        "runtime/artifact_manifest.json": _canonical_json(knowledge_base.model_dump(mode="json")),
        "policies/integration_gate.json": integration_policy_bytes,
        "policies/live_quality_gate.json": live_policy_bytes,
    }
    if sum(len(value) for value in source_entries.values()) > MAX_BUNDLE_SOURCE_BYTES:
        raise ReleaseEvidenceCaptureError("release evidence source bundle is too large")

    for name, data in source_entries.items():
        _scan_source(name, data)

    checksums = {
        name: {"bytes": len(data), "sha256": _sha256_bytes(data)}
        for name, data in sorted(source_entries.items())
    }
    entries = dict(source_entries)
    entries["checksums.json"] = _canonical_json(checksums)
    artifact_names = {
        "integration_gate/report.json": "integration_report",
        "integration_gate/summary.md": "integration_summary",
        "live_quality_gate/report.json": "live_quality_report",
        "live_quality_gate/summary.md": "live_quality_summary",
        "live_quality_gate/manual_review_sample.jsonl": "manual_review_sample",
        "runtime/diagnostics.json": "runtime_diagnostics",
        "runtime/artifact_manifest.json": "knowledge_artifact",
        "policies/integration_gate.json": "integration_policy",
        "policies/live_quality_gate.json": "live_quality_policy",
        "checksums.json": "checksums",
    }
    artifacts = [
        _file_identity(artifact_names[name], name, data) for name, data in sorted(entries.items())
    ]

    bundle_name = f"graph-rag-c9-{inputs.package_version}-quality-evidence.zip"
    bundle_path = inputs.output_dir / bundle_name
    _write_deterministic_zip(bundle_path, entries)
    try:
        bundle_size = bundle_path.stat().st_size
    except OSError as exc:
        raise ReleaseEvidenceCaptureError("release evidence bundle could not be read") from exc
    bundle_sha256 = _sha256_file(bundle_path)
    receipt = CaptureReceipt(
        release=ReleaseIdentity(
            package_version=inputs.package_version,
            tag=inputs.tag,
        ),
        provenance=Provenance(
            repository=inputs.repository,
            evaluated_commit=inputs.evaluated_commit,
            generated_at=generated_at or datetime.now(UTC).isoformat(),
        ),
        integration=integration,
        quality=quality,
        runtime=runtime,
        dataset=dataset,
        knowledge_base=knowledge_base,
        bundle=BundleIdentity(
            name=bundle_name,
            bytes=bundle_size,
            sha256=bundle_sha256,
        ),
        artifacts=artifacts,
    )
    receipt_path = inputs.output_dir / "capture-receipt.json"
    write_evidence_model(receipt, receipt_path)
    return CaptureOutputs(receipt_path=receipt_path, bundle_path=bundle_path)
