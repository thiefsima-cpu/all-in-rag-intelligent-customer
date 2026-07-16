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

from rag_modules.configuration.profiles import load_profile
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


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ReleaseEvidenceCaptureError(
            f"release evidence member could not be read: {path.name}"
        ) from exc
    if len(data) > MAX_MEMBER_BYTES:
        raise ReleaseEvidenceCaptureError(f"release evidence member is too large: {path.name}")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceCaptureError(f"release evidence JSON is invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReleaseEvidenceCaptureError(f"release evidence JSON must be an object: {path.name}")
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


def _project_version(repository_root: Path) -> str:
    try:
        payload = tomllib.loads((repository_root / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
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
    if _project_version(inputs.repository_root) != inputs.package_version:
        raise ReleaseEvidenceCaptureError("package version does not match checkout")
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


def _project_runtime(
    diagnostics_payload: Mapping[str, Any],
    artifact_manifest: ArtifactManifest,
    *,
    repository_root: Path,
    judge_model: str,
    target: Mapping[str, Any],
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
    try:
        resolved_profile = load_profile(
            profile=profile_name,
            profiles_dir=repository_root / "profiles",
        )
    except (OSError, ValueError) as exc:
        raise ReleaseEvidenceCaptureError("artifact profile is invalid") from exc
    profile_hash = str(profile_data.get("hash") or "")
    if not profile_hash or profile_hash != resolved_profile.profile_hash:
        raise ReleaseEvidenceCaptureError("artifact profile hash does not match repository")
    return RuntimeIdentity(
        target=TargetIdentity(
            api_host=str(target.get("api_host") or ""),
            judge_host=str(target.get("judge_host") or ""),
        ),
        profile=ProfileIdentity(
            name=profile_name,
            path=profile_path.relative_to(repository_root).as_posix(),
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


def capture_release_evidence(
    inputs: CaptureInputs,
    *,
    generated_at: str | None = None,
) -> CaptureOutputs:
    _validate_checkout(inputs)
    integration_report = _read_json(inputs.integration_report_path)
    live_report = _read_json(inputs.live_quality_report_path)
    integration_policy_payload = _read_json(inputs.integration_policy_path)
    live_policy_payload = _read_json(inputs.live_quality_policy_path)
    diagnostics_payload = _read_json(inputs.diagnostics_path)
    artifact_payload = _read_json(inputs.artifact_manifest_path)
    try:
        integration_policy = IntegrationGatePolicy.model_validate(integration_policy_payload)
        live_policy = LiveQualityGatePolicy.model_validate(live_policy_payload)
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("release evidence policy is invalid") from exc
    artifact_manifest = _load_artifact_manifest(artifact_payload)

    try:
        integration = _project_integration(integration_report, integration_policy)
        quality = _project_quality(live_report, live_policy)
        target = _require_mapping(live_report.get("target"), "live quality target")
        runtime = _project_runtime(
            diagnostics_payload,
            artifact_manifest,
            repository_root=inputs.repository_root,
            judge_model=inputs.judge_model,
            target=target,
        )
        knowledge_base = _project_knowledge_base(artifact_manifest)
        dataset_bytes = _read_bytes(inputs.live_quality_policy_path)
        dataset = DatasetIdentity(
            path="eval/live_quality_gate.json",
            schema_version=live_policy.schema_version,
            case_count=len(live_policy.cases),
            sha256=_sha256_bytes(dataset_bytes),
        )
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("release evidence projection is invalid") from exc

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
    manual_review_bytes = _read_bytes(
        _report_member(
            inputs.live_quality_report_path,
            live_artifacts.get("manual_review_sample_jsonl"),
        )
    )
    try:
        manual_review_text = manual_review_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError("manual review sample is not UTF-8") from exc
    manual_review_line_count = sum(bool(line.strip()) for line in manual_review_text.splitlines())
    if manual_review_line_count != quality.manual_review_sample_count:
        raise ReleaseEvidenceCaptureError("manual review sample count does not match JSONL")

    source_entries = {
        "integration_gate/report.json": _read_bytes(inputs.integration_report_path),
        "integration_gate/summary.md": _read_bytes(
            _report_member(
                inputs.integration_report_path,
                integration_artifacts.get("summary_md"),
            )
        ),
        "live_quality_gate/report.json": _read_bytes(inputs.live_quality_report_path),
        "live_quality_gate/summary.md": _read_bytes(
            _report_member(inputs.live_quality_report_path, live_artifacts.get("summary_md"))
        ),
        "live_quality_gate/manual_review_sample.jsonl": manual_review_bytes,
        "runtime/diagnostics.json": _canonical_json(runtime.model_dump(mode="json")),
        "runtime/artifact_manifest.json": _canonical_json(knowledge_base.model_dump(mode="json")),
        "policies/integration_gate.json": _read_bytes(inputs.integration_policy_path),
        "policies/live_quality_gate.json": dataset_bytes,
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
    bundle_bytes = bundle_path.read_bytes()
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
            bytes=len(bundle_bytes),
            sha256=_sha256_bytes(bundle_bytes),
        ),
        artifacts=artifacts,
    )
    receipt_path = inputs.output_dir / "capture-receipt.json"
    write_evidence_model(receipt, receipt_path)
    return CaptureOutputs(receipt_path=receipt_path, bundle_path=bundle_path)
