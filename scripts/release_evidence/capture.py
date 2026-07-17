from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import tomllib
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

from pydantic import ValidationError

from rag_modules.interfaces.api.diagnostics_models import DiagnosticsResponseModel
from rag_modules.kernel.artifacts import ArtifactManifest, artifact_health
from scripts.gates import GateCheckResult, GateFailureType
from scripts.integration_gate.models import IntegrationGatePolicy
from scripts.integration_gate.reporter import render_integration_summary
from scripts.live_quality_gate.evaluator import evaluate_policy_thresholds
from scripts.live_quality_gate.models import LiveQualityGatePolicy
from scripts.live_quality_gate.reporter import render_live_quality_summary
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
_CAMEL_CASE_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_KEY_CHARACTER_RE = re.compile(r"[^A-Za-z0-9]+")
_SENSITIVE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "authorization",
        "auth_token",
        "aws_secret_access_key",
        "bearer_token",
        "client_secret",
        "credential",
        "credentials",
        "exception",
        "password",
        "passwd",
        "private_key",
        "raw_exception",
        "refresh_token",
        "secret_key",
        "session_token",
        "stack",
        "stack_trace",
        "token",
        "trace",
        "traceback",
    }
)
_SAFE_TOKEN_METRIC_KEYS = frozenset(
    {
        "cached_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "prompt_tokens",
        "reasoning_tokens",
        "token_count",
        "total_tokens",
    }
)
_SAFE_TOKEN_METRIC_PATH_RE = re.compile(
    r"^integration_gate/report\.json:\$\.cases\[\d+\]\.total_tokens$"
)
_SENSITIVE_KEY_SUFFIXES = (
    "_access_token",
    "_api_key",
    "_api_token",
    "_auth_token",
    "_bearer_token",
    "_client_secret",
    "_credential",
    "_credentials",
    "_private_key",
    "_password",
    "_passwd",
    "_refresh_token",
    "_raw_exception",
    "_secret_key",
    "_session_token",
    "_stack",
    "_stack_trace",
    "_token",
    "_trace",
    "_traceback",
    "_exception",
    "_authorization",
)
_BEARER_VALUE_RE = re.compile(r"\bBearer[ \t]+\S+", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"\bAuthorization\s*:", re.IGNORECASE)
_ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/]")
_ABSOLUTE_WINDOWS_UNC_PATH_RE = re.compile(r"(?:^|[\s\"'=(])\\\\[^\\/\s]+\\[^\\/\s]+")
_ABSOLUTE_FORWARD_UNC_PATH_RE = re.compile(r"(?:^|[\s\"'=(])//[^/\s]+/[^/\s]+")
_ABSOLUTE_UNIX_PATH_RE = re.compile(r"(?:^|[\s\"'=(])/(?!/)[^\s<>\"']+")
_URI_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+")
_TRACEBACK_RE = re.compile(
    r"Traceback\s+\(most recent call last\):|"
    r"(?:^|\n)\s*File\s+[\"'][^\"']+[\"'],\s+line\s+\d+|"
    r"(?:^|\n)\s*at\s+\S+\([^)]*:\d+\)",
    re.IGNORECASE,
)
_EXCEPTION_VALUE_RE = re.compile(
    r"\b[A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)(?::\s*\S|\s*\([^\r\n)]*\))",
    re.IGNORECASE,
)
_API_ROUTE_FIELD_KEYS = frozenset({"api_endpoint", "api_route", "endpoint", "route"})
_VERSIONED_API_ROUTE_RE = re.compile(r"^/v[0-9]+(?:/[A-Za-z0-9_~-][A-Za-z0-9._~-]*)+$")
_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_GATE_STATUSES = frozenset({"passed", "failed", "blocked"})
_GATE_CHECK_DETAIL_KEYS = frozenset(
    {
        "name",
        "status",
        "passed",
        "failure_type",
        "code",
        "expected",
        "actual",
        "duration_ms",
    }
)
_NON_BLOCKING_LIVE_QUALITY_CODES = frozenset(
    {"DETERMINISTIC_QUALITY_FAILED", "JUDGE_QUALITY_FAILED"}
)
_QUALITY_METRIC_CHECK_NAMES = (
    "case_count",
    "pass_rate",
    "deterministic_pass_rate",
    "judge_pass_rate",
    "recall_at_k",
    "mrr",
    "ndcg_at_k",
    "fallback_rate",
    "retrieval_degradation_rate",
    "p95_latency_ms",
    "estimated_cost_usd",
)
_CASE_RETRIEVAL_METRIC_NAMES = ("recall_at_k", "mrr", "ndcg_at_k")
_INTEGRATION_PROBE_CHECK_CODES = {
    "dependency.neo4j.recipe_count": "NEO4J_READY",
    "dependency.milvus.entity_count": "MILVUS_READY",
    "dependency.serving.ready": "SERVING_API_READY",
}
_INTEGRATION_CASE_CHECK_CODES = {
    "strategy": "STRATEGY_OK",
    "sources": "REQUIRED_SOURCES_OK",
    "evidence_count": "EVIDENCE_COUNT_OK",
    "fallback": "FALLBACK_OK",
    "retrieval_degradation": "RETRIEVAL_DEGRADATION_OK",
    "model_usage": "MODEL_USAGE_OK",
    "latency": "CASE_LATENCY_OK",
}
_INTEGRATION_AGGREGATE_CHECK_CODES = {
    "metrics.global_vector_coverage": "GLOBAL_VECTOR_COVERAGE_OK",
    "metrics.global_graph_coverage": "GLOBAL_GRAPH_COVERAGE_OK",
    "metrics.fallback_rate": "METRIC_WITHIN_THRESHOLD",
    "metrics.retrieval_degradation_rate": "METRIC_WITHIN_THRESHOLD",
    "metrics.p95_latency_ms": "METRIC_WITHIN_THRESHOLD",
    "metrics.estimated_cost_usd": "METRIC_WITHIN_THRESHOLD",
}
_LIVE_SLICE_FIELDS = {
    "by_query_type": ("query_type", False),
    "by_cuisine": ("cuisine", False),
    "by_constraint_type": ("constraint_types", True),
    "by_risk_tag": ("risk_tags", True),
    "by_response_mode": ("response_mode", False),
    "by_strategy": ("strategy", False),
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
_INTEGRATION_TARGET_KEYS = frozenset({"api_host", "neo4j_host", "milvus_host"})
_INTEGRATION_METRIC_KEYS = frozenset(
    {
        "check_count",
        "failed_count",
        "blocked_count",
        "case_count",
        "executed_case_count",
        "observation_count",
        "failure_type_counts",
        "total_estimated_cost_usd",
        "max_latency_ms",
    }
)
_INTEGRATION_CASE_KEYS = frozenset(
    {
        "case_id",
        "executed",
        "status",
        "has_observation",
        "evidence_count",
        "latency_ms",
        "total_tokens",
        "estimated_cost_usd",
        "check_codes",
    }
)
_INTEGRATION_ARTIFACT_KEYS = frozenset({"report_json", "summary_md"})
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
_LIVE_TARGET_KEYS = frozenset({"api_host", "judge_host"})
_LIVE_SUMMARY_KEYS = frozenset(
    {
        "case_count",
        "pass_rate",
        "deterministic_pass_rate",
        "judge_pass_rate",
        "recall_at_k",
        "mrr",
        "ndcg_at_k",
        "fallback_rate",
        "retrieval_degradation_rate",
        "p95_latency_ms",
        "estimated_cost_usd",
        "avg_judge_scores",
    }
)
_LIVE_METRIC_KEYS = _LIVE_SUMMARY_KEYS | frozenset(_LIVE_SLICE_FIELDS)
_LIVE_CASE_KEYS = frozenset(
    {
        "case_id",
        "query_type",
        "cuisine",
        "constraint_types",
        "risk_tags",
        "response_mode",
        "strategy",
        "passed",
        "deterministic_passed",
        "judge_passed",
        "judge_scores",
        "failures",
        "metrics",
        "manual_review",
        "answer_preview",
        "evidence",
    }
)
_LIVE_CASE_METRIC_KEYS = frozenset(_CASE_RETRIEVAL_METRIC_NAMES)
_LIVE_MANUAL_REVIEW_KEYS = frozenset({"owner", "sample"})
_LIVE_EVIDENCE_KEYS = frozenset({"recipe_name", "source", "snippet"})
_LIVE_ARTIFACT_KEYS = frozenset({"report_json", "summary_md", "manual_review_sample_jsonl"})
_MANUAL_REVIEW_SAMPLE_KEYS = frozenset(
    {
        "case_id",
        "owner",
        "query_type",
        "cuisine",
        "risk_tags",
        "constraint_types",
        "expected_response_mode",
        "query",
        "passed",
        "deterministic_passed",
        "judge_passed",
        "judge_scores",
        "failures",
        "answer_preview",
        "evidence",
    }
)


class ReleaseEvidenceCaptureError(RuntimeError):
    pass


class _DuplicateJsonKeyError(ValueError):
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


def _json_object_without_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise _DuplicateJsonKeyError(key)
        payload[key] = value
    return payload


def _parse_json(data: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except _DuplicateJsonKeyError as exc:
        raise ReleaseEvidenceCaptureError(
            f"release evidence JSON contains a duplicate key: {name}"
        ) from exc
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
    try:
        result = float(value)
    except OverflowError as exc:
        raise ReleaseEvidenceCaptureError(f"{name} is invalid") from exc
    if not math.isfinite(result):
        raise ReleaseEvidenceCaptureError(f"{name} is invalid")
    return result


def _detail_list(report: Mapping[str, Any], key: str, name: str) -> list[dict[str, Any]]:
    value = report.get(key)
    if not isinstance(value, list):
        raise ReleaseEvidenceCaptureError(f"{name} must be an array")
    if not value:
        raise ReleaseEvidenceCaptureError(f"{name} must not be empty")
    if not all(isinstance(item, dict) for item in value):
        raise ReleaseEvidenceCaptureError(f"{name} contains an invalid entry")
    return value


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: frozenset[str],
    name: str,
) -> None:
    if set(value) != expected:
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")


def _require_iso_timestamp(value: object, name: str) -> None:
    if not isinstance(value, str):
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid") from exc


def _validate_failure_counts(value: object, name: str) -> None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not key
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for key, count in value.items()
    ):
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")


def _validate_evidence_entries(
    value: object,
    name: str,
    *,
    maximum_items: int,
    maximum_snippet_length: int,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
    entries: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
        _require_exact_keys(item, _LIVE_EVIDENCE_KEYS, name)
        if (
            not isinstance(item["recipe_name"], str)
            or not isinstance(item["source"], str)
            or not isinstance(item["snippet"], str)
            or len(item["snippet"]) > maximum_snippet_length
        ):
            raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
        entries.append(item)
    return entries


def _validate_integration_report_schema(report: Mapping[str, Any]) -> None:
    _detail_list(report, "checks", "integration check details")
    _detail_list(report, "cases", "integration case details")
    _require_exact_keys(report, _INTEGRATION_REPORT_KEYS, "integration report")
    if report.get("schema_version") != 1 or not isinstance(report.get("passed"), bool):
        raise ReleaseEvidenceCaptureError("integration report schema is invalid")
    _require_iso_timestamp(report.get("generated_at"), "integration report")

    target = _require_mapping(report.get("target"), "integration target")
    _require_exact_keys(target, _INTEGRATION_TARGET_KEYS, "integration target")
    if any(not isinstance(target[key], str) for key in _INTEGRATION_TARGET_KEYS):
        raise ReleaseEvidenceCaptureError("integration target schema is invalid")

    metrics = _require_mapping(report.get("metrics"), "integration metrics")
    _require_exact_keys(metrics, _INTEGRATION_METRIC_KEYS, "integration metrics")
    _validate_failure_counts(metrics.get("failure_type_counts"), "integration metrics")

    artifacts = _require_mapping(report.get("artifacts"), "integration artifacts")
    _require_exact_keys(artifacts, _INTEGRATION_ARTIFACT_KEYS, "integration artifacts")
    if artifacts != {"report_json": "report.json", "summary_md": "summary.md"}:
        raise ReleaseEvidenceCaptureError("integration artifacts schema is invalid")

    for check in _detail_list(report, "checks", "integration check details"):
        _require_exact_keys(check, _GATE_CHECK_DETAIL_KEYS, "integration check details")
    for case in _detail_list(report, "cases", "integration case details"):
        _require_exact_keys(case, _INTEGRATION_CASE_KEYS, "integration case details")


def _validate_live_summary_schema(
    value: object,
    policy: LiveQualityGatePolicy,
    name: str,
) -> None:
    summary = _require_mapping(value, name)
    _require_exact_keys(summary, _LIVE_SUMMARY_KEYS, name)
    case_count = summary.get("case_count")
    if isinstance(case_count, bool) or not isinstance(case_count, int) or case_count < 0:
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
    for metric_name in _LIVE_SUMMARY_KEYS - {"case_count", "avg_judge_scores"}:
        metric_value = summary.get(metric_name)
        if metric_value is None and metric_name in {
            "judge_pass_rate",
            "recall_at_k",
            "mrr",
            "ndcg_at_k",
        }:
            continue
        projected = _require_float(metric_value, f"{name} {metric_name}")
        if (
            metric_name
            in {
                "pass_rate",
                "deterministic_pass_rate",
                "judge_pass_rate",
                "recall_at_k",
                "mrr",
                "ndcg_at_k",
                "fallback_rate",
                "retrieval_degradation_rate",
            }
            and not 0.0 <= projected <= 1.0
        ):
            raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
        if metric_name in {"p95_latency_ms", "estimated_cost_usd"} and projected < 0:
            raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
    scores = _require_mapping(summary.get("avg_judge_scores"), f"{name} avg judge scores")
    expected_scores = set(policy.judge.score_names) if policy.judge.required else set()
    if set(scores) != expected_scores:
        raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")
    for score_name, score_value in scores.items():
        score = _require_float(score_value, f"{name} avg judge score {score_name}")
        if not 0.0 <= score <= 1.0:
            raise ReleaseEvidenceCaptureError(f"{name} schema is invalid")


def _validate_live_report_schema(
    report: Mapping[str, Any],
    policy: LiveQualityGatePolicy,
) -> None:
    _detail_list(report, "checks", "live quality check details")
    _detail_list(report, "cases", "live quality case details")
    _require_exact_keys(report, _LIVE_REPORT_KEYS, "live quality report")
    top_k = report.get("top_k")
    if (
        report.get("schema_version") != 1
        or not isinstance(report.get("passed"), bool)
        or isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k <= 0
        or top_k != policy.top_k
    ):
        raise ReleaseEvidenceCaptureError("live quality report schema is invalid")
    _require_iso_timestamp(report.get("generated_at"), "live quality report")

    target = _require_mapping(report.get("target"), "live quality target")
    _require_exact_keys(target, _LIVE_TARGET_KEYS, "live quality target")
    if any(not isinstance(target[key], str) for key in _LIVE_TARGET_KEYS):
        raise ReleaseEvidenceCaptureError("live quality target schema is invalid")

    metrics = _require_mapping(report.get("metrics"), "live quality metrics")
    _require_exact_keys(metrics, _LIVE_METRIC_KEYS, "live quality metrics")
    _validate_live_summary_schema(
        {key: metrics[key] for key in _LIVE_SUMMARY_KEYS},
        policy,
        "live quality metrics",
    )
    for slice_name in _LIVE_SLICE_FIELDS:
        slices = _require_mapping(metrics.get(slice_name), f"live quality metric {slice_name}")
        if any(not isinstance(label, str) or not label for label in slices):
            raise ReleaseEvidenceCaptureError(f"live quality metric {slice_name} schema is invalid")
        for label, summary in slices.items():
            _validate_live_summary_schema(
                summary,
                policy,
                f"live quality metric {slice_name}.{label}",
            )

    _validate_failure_counts(report.get("failure_type_counts"), "live quality failures")
    artifacts = _require_mapping(report.get("artifacts"), "live quality artifacts")
    _require_exact_keys(artifacts, _LIVE_ARTIFACT_KEYS, "live quality artifacts")
    if artifacts != {
        "report_json": "report.json",
        "summary_md": "summary.md",
        "manual_review_sample_jsonl": "manual_review_sample.jsonl",
    }:
        raise ReleaseEvidenceCaptureError("live quality artifacts schema is invalid")

    for check in _detail_list(report, "checks", "live quality check details"):
        _require_exact_keys(check, _GATE_CHECK_DETAIL_KEYS, "live quality check details")
    for case in _detail_list(report, "cases", "live quality case details"):
        _require_exact_keys(case, _LIVE_CASE_KEYS, "live quality case details")
        case_metrics = _require_mapping(case.get("metrics"), "live quality case metrics")
        _require_exact_keys(case_metrics, _LIVE_CASE_METRIC_KEYS, "live quality case metrics")
        manual_review = _require_mapping(
            case.get("manual_review"),
            "live quality case manual review",
        )
        _require_exact_keys(
            manual_review,
            _LIVE_MANUAL_REVIEW_KEYS,
            "live quality case manual review",
        )
        if (
            not isinstance(manual_review.get("owner"), str)
            or not manual_review["owner"].strip()
            or not isinstance(manual_review.get("sample"), bool)
            or not isinstance(case.get("answer_preview"), str)
            or len(case["answer_preview"]) > 300
        ):
            raise ReleaseEvidenceCaptureError("live quality case schema is invalid")
        _validate_evidence_entries(
            case.get("evidence"),
            "live quality case evidence",
            maximum_items=5,
            maximum_snippet_length=160,
        )

    sample_count = report.get("manual_review_sample_count")
    samples = report.get("manual_review_sample")
    if (
        isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count < 0
        or not isinstance(samples, list)
    ):
        raise ReleaseEvidenceCaptureError("manual review sample schema is invalid")
    for sample in samples:
        if not isinstance(sample, dict):
            raise ReleaseEvidenceCaptureError("manual review sample schema is invalid")
        _require_exact_keys(sample, _MANUAL_REVIEW_SAMPLE_KEYS, "manual review sample")
        _validate_evidence_entries(
            sample.get("evidence"),
            "manual review sample evidence",
            maximum_items=6,
            maximum_snippet_length=240,
        )


def _parse_manual_review_jsonl(data: bytes, name: str) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError("manual review JSONL is not UTF-8") from exc
    if not text:
        return []

    def reject_non_finite(_: str) -> None:
        raise ValueError("non-finite JSON number")

    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise ReleaseEvidenceCaptureError(
                f"manual review JSONL contains a blank line: {name}:{line_number}"
            )
        try:
            row = json.loads(
                line,
                parse_constant=reject_non_finite,
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except _DuplicateJsonKeyError as exc:
            raise ReleaseEvidenceCaptureError(
                f"manual review JSONL contains a duplicate key: {name}:{line_number}"
            ) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ReleaseEvidenceCaptureError(
                f"manual review JSONL is invalid: {name}:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ReleaseEvidenceCaptureError(
                f"manual review JSONL row must be an object: {name}:{line_number}"
            )
        rows.append(row)
    return rows


def _validate_manual_review_binding(
    report: Mapping[str, Any],
    policy: LiveQualityGatePolicy,
    jsonl_rows: list[dict[str, Any]],
) -> None:
    report_rows = report.get("manual_review_sample")
    sample_count = report.get("manual_review_sample_count")
    if not isinstance(report_rows, list) or any(not isinstance(row, dict) for row in report_rows):
        raise ReleaseEvidenceCaptureError("manual review sample schema is invalid")
    try:
        canonical_report_rows = [_canonical_json(row) for row in report_rows]
        canonical_jsonl_rows = [_canonical_json(row) for row in jsonl_rows]
    except (TypeError, ValueError) as exc:
        raise ReleaseEvidenceCaptureError("manual review sample schema is invalid") from exc
    if (
        isinstance(sample_count, bool)
        or not isinstance(sample_count, int)
        or sample_count != len(report_rows)
        or sample_count != len(jsonl_rows)
        or canonical_report_rows != canonical_jsonl_rows
    ):
        raise ReleaseEvidenceCaptureError("manual review sample does not match JSONL")

    sampled_policies = [case for case in policy.cases if case.manual_review.sample]
    expected_case_ids = [case.case_id for case in sampled_policies]
    actual_case_ids = [row.get("case_id") for row in report_rows]
    if (
        not all(isinstance(case_id, str) for case_id in actual_case_ids)
        or actual_case_ids != expected_case_ids
        or len(actual_case_ids) != len(set(actual_case_ids))
    ):
        raise ReleaseEvidenceCaptureError("manual review sample does not match policy order")

    report_cases = report.get("cases")
    if not isinstance(report_cases, list) or any(
        not isinstance(case, dict) for case in report_cases
    ):
        raise ReleaseEvidenceCaptureError("manual review sample cannot be bound to report cases")
    cases_by_id = {case.get("case_id"): case for case in report_cases}
    for row, case_policy in zip(report_rows, sampled_policies, strict=True):
        _require_exact_keys(row, _MANUAL_REVIEW_SAMPLE_KEYS, "manual review sample")
        evidence = _validate_evidence_entries(
            row.get("evidence"),
            "manual review sample evidence",
            maximum_items=6,
            maximum_snippet_length=240,
        )
        judge_scores = row.get("judge_scores")
        failures = row.get("failures")
        answer_preview = row.get("answer_preview")
        expected_score_names = set(policy.judge.score_names) if policy.judge.required else set()
        if (
            row.get("case_id") != case_policy.case_id
            or row.get("owner") != case_policy.manual_review.owner
            or row.get("query_type") != case_policy.query_type
            or row.get("cuisine") != case_policy.cuisine
            or row.get("risk_tags") != case_policy.risk_tags
            or row.get("constraint_types") != case_policy.constraint_types
            or row.get("expected_response_mode") != case_policy.expected_response_mode.value
            or row.get("query") != case_policy.query
            or not isinstance(row.get("passed"), bool)
            or not isinstance(row.get("deterministic_passed"), bool)
            or (row.get("judge_passed") is not None and not isinstance(row["judge_passed"], bool))
            or not isinstance(judge_scores, dict)
            or set(judge_scores) != expected_score_names
            or not isinstance(failures, list)
            or not all(isinstance(failure, str) and failure for failure in failures)
            or failures != sorted(set(failures))
            or not isinstance(answer_preview, str)
            or len(answer_preview) > 500
        ):
            raise ReleaseEvidenceCaptureError("manual review sample does not match policy")
        for score_name, score_value in judge_scores.items():
            score = _require_float(score_value, f"manual review judge score {score_name}")
            if not 0.0 <= score <= 1.0:
                raise ReleaseEvidenceCaptureError("manual review sample schema is invalid")

        case = cases_by_id.get(case_policy.case_id)
        if not isinstance(case, dict):
            raise ReleaseEvidenceCaptureError("manual review sample case is unknown")
        if any(
            row[field_name] != case[field_name]
            for field_name in (
                "passed",
                "deterministic_passed",
                "judge_passed",
                "judge_scores",
                "failures",
            )
        ) or answer_preview[:300] != case.get("answer_preview"):
            raise ReleaseEvidenceCaptureError("manual review sample does not match report case")
        case_evidence = case.get("evidence")
        if not isinstance(case_evidence, list) or len(case_evidence) != min(len(evidence), 5):
            raise ReleaseEvidenceCaptureError("manual review sample does not match report case")
        for case_item, sample_item in zip(case_evidence, evidence[:5], strict=True):
            if (
                case_item.get("recipe_name") != sample_item["recipe_name"]
                or case_item.get("source") != sample_item["source"]
                or case_item.get("snippet") != sample_item["snippet"][:160]
            ):
                raise ReleaseEvidenceCaptureError("manual review sample does not match report case")


def _check_detail(
    value: Mapping[str, Any],
    name: str,
) -> tuple[str, str, str, str | None]:
    status = value.get("status")
    passed = value.get("passed")
    check_name = value.get("name")
    code = value.get("code")
    failure_type = value.get("failure_type")
    duration_ms = value.get("duration_ms")
    if (
        set(value) != _GATE_CHECK_DETAIL_KEYS
        or status not in _GATE_STATUSES
        or not isinstance(passed, bool)
        or passed is not (status == "passed")
        or not isinstance(check_name, str)
        or not check_name
        or not isinstance(code, str)
        or not code
        or (status == "failed" and not isinstance(failure_type, str))
        or (status != "failed" and failure_type is not None)
        or isinstance(duration_ms, bool)
        or not isinstance(duration_ms, int | float)
        or not math.isfinite(duration_ms)
        or duration_ms < 0
    ):
        raise ReleaseEvidenceCaptureError(f"{name} are invalid")
    return status, check_name, code, failure_type


def _float_matches(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)


def _evidence_value_matches(left: object, right: object) -> bool:
    if (
        not isinstance(left, bool)
        and not isinstance(right, bool)
        and isinstance(left, int | float)
        and isinstance(right, int | float)
    ):
        if isinstance(left, int) and isinstance(right, int):
            return left == right
        try:
            return _float_matches(float(left), float(right))
        except OverflowError:
            return False
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _evidence_value_matches(left[key], right[key]) for key in left
        )
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(
            _evidence_value_matches(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def _gate_check_matches(actual: Mapping[str, Any], expected: GateCheckResult) -> bool:
    expected_payload = expected.to_dict()
    return all(
        _evidence_value_matches(actual.get(field_name), expected_payload[field_name])
        for field_name in (
            "name",
            "status",
            "passed",
            "failure_type",
            "code",
            "expected",
            "actual",
        )
    )


def _integration_check_codes(policy: IntegrationGatePolicy) -> dict[str, str]:
    expected = dict(_INTEGRATION_PROBE_CHECK_CODES)
    for case in policy.live_cases:
        expected.update(
            {
                f"case.{case.case_id}.{suffix}": code
                for suffix, code in _INTEGRATION_CASE_CHECK_CODES.items()
            }
        )
    expected.update(_INTEGRATION_AGGREGATE_CHECK_CODES)
    return expected


def _nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    index = math.ceil(0.95 * len(ordered)) - 1
    return ordered[max(0, min(index, len(ordered) - 1))]


def _validate_integration_check_payloads(
    checks_by_name: Mapping[str, Mapping[str, Any]],
    cases_by_id: Mapping[str, Mapping[str, Any]],
    policy: IntegrationGatePolicy,
    *,
    total_estimated_cost: float,
    latencies: list[float],
) -> None:
    expected_checks: list[GateCheckResult] = []
    probe_minimums = (
        (
            "dependency.neo4j.recipe_count",
            "NEO4J_READY",
            policy.dependency_minimums.neo4j_recipe_count,
        ),
        (
            "dependency.milvus.entity_count",
            "MILVUS_READY",
            policy.dependency_minimums.milvus_entity_count,
        ),
    )
    for name, code, minimum in probe_minimums:
        actual = checks_by_name[name].get("actual")
        if isinstance(actual, bool) or not isinstance(actual, int) or actual < minimum:
            raise ReleaseEvidenceCaptureError("integration check details do not satisfy policy")
        expected_checks.append(
            GateCheckResult.pass_check(
                name,
                code=code,
                expected={"minimum": minimum},
                actual=actual,
            )
        )
    expected_checks.append(
        GateCheckResult.pass_check(
            "dependency.serving.ready",
            code="SERVING_API_READY",
            expected=True,
            actual=True,
        )
    )

    for case_policy in policy.live_cases:
        case = cases_by_id[case_policy.case_id]
        evidence_count = int(case["evidence_count"])
        total_tokens = int(case["total_tokens"])
        latency = float(case["latency_ms"])
        latency_name = f"case.{case_policy.case_id}.latency"
        latency_actual = _require_float(
            checks_by_name[latency_name].get("actual"),
            "integration check latency actual",
        )
        maximum_latency_ms = case_policy.timeout_seconds * 1000
        if (
            evidence_count < case_policy.minimum_evidence_count
            or (case_policy.generation_required and total_tokens <= 0)
            or latency_actual > maximum_latency_ms
            or not _float_matches(round(latency_actual, 3), latency)
        ):
            raise ReleaseEvidenceCaptureError("integration check details do not satisfy policy")
        prefix = f"case.{case_policy.case_id}"
        expected_checks.extend(
            (
                GateCheckResult.pass_check(
                    f"{prefix}.strategy",
                    code="STRATEGY_OK",
                    expected="[redacted]",
                    actual="[redacted]",
                ),
                GateCheckResult.pass_check(
                    f"{prefix}.sources",
                    code="REQUIRED_SOURCES_OK",
                    expected="[redacted]",
                    actual="[redacted]",
                ),
                GateCheckResult.pass_check(
                    f"{prefix}.evidence_count",
                    code="EVIDENCE_COUNT_OK",
                    expected={"minimum": case_policy.minimum_evidence_count},
                    actual=evidence_count,
                ),
                GateCheckResult.pass_check(
                    f"{prefix}.fallback",
                    code="FALLBACK_OK",
                    expected=False,
                    actual=False,
                ),
                GateCheckResult.pass_check(
                    f"{prefix}.retrieval_degradation",
                    code="RETRIEVAL_DEGRADATION_OK",
                    expected=False,
                    actual=False,
                ),
                GateCheckResult.pass_check(
                    f"{prefix}.model_usage",
                    code="MODEL_USAGE_OK",
                    expected={
                        "generation_required": case_policy.generation_required,
                        "minimum_tokens": 1,
                    },
                    actual=total_tokens,
                ),
                GateCheckResult.pass_check(
                    latency_name,
                    code="CASE_LATENCY_OK",
                    expected={"maximum_ms": maximum_latency_ms},
                    actual=latency_actual,
                ),
            )
        )

    expected_checks.extend(
        (
            GateCheckResult.pass_check(
                "metrics.global_vector_coverage",
                code="GLOBAL_VECTOR_COVERAGE_OK",
                expected=True,
                actual=True,
            ),
            GateCheckResult.pass_check(
                "metrics.global_graph_coverage",
                code="GLOBAL_GRAPH_COVERAGE_OK",
                expected=True,
                actual=True,
            ),
            GateCheckResult.pass_check(
                "metrics.fallback_rate",
                code="METRIC_WITHIN_THRESHOLD",
                expected={
                    "minimum": None,
                    "maximum": policy.thresholds.maximum_fallback_rate,
                },
                actual=0.0,
            ),
            GateCheckResult.pass_check(
                "metrics.retrieval_degradation_rate",
                code="METRIC_WITHIN_THRESHOLD",
                expected={
                    "minimum": None,
                    "maximum": policy.thresholds.maximum_retrieval_degradation_rate,
                },
                actual=0.0,
            ),
        )
    )
    p95_name = "metrics.p95_latency_ms"
    p95_actual = _require_float(
        checks_by_name[p95_name].get("actual"),
        "integration check p95 latency actual",
    )
    expected_p95 = _nearest_rank_p95(latencies)
    if p95_actual > policy.thresholds.maximum_p95_latency_ms or not _float_matches(
        round(p95_actual, 3), round(expected_p95, 3)
    ):
        raise ReleaseEvidenceCaptureError("integration check details do not satisfy policy")
    expected_checks.append(
        GateCheckResult.pass_check(
            p95_name,
            code="METRIC_WITHIN_THRESHOLD",
            expected={
                "minimum": None,
                "maximum": policy.thresholds.maximum_p95_latency_ms,
            },
            actual=p95_actual,
        )
    )
    cost_name = "metrics.estimated_cost_usd"
    cost_actual = _require_float(
        checks_by_name[cost_name].get("actual"),
        "integration check estimated cost actual",
    )
    cost_tolerance = (len(cases_by_id) + 1) * 0.5e-6 + 1e-12
    if cost_actual > policy.thresholds.maximum_estimated_cost_usd or not math.isclose(
        cost_actual,
        total_estimated_cost,
        rel_tol=0.0,
        abs_tol=cost_tolerance,
    ):
        raise ReleaseEvidenceCaptureError("integration check details do not satisfy policy")
    expected_checks.append(
        GateCheckResult.pass_check(
            cost_name,
            code="METRIC_WITHIN_THRESHOLD",
            expected={
                "minimum": None,
                "maximum": policy.thresholds.maximum_estimated_cost_usd,
            },
            actual=cost_actual,
        )
    )
    if any(
        not _gate_check_matches(checks_by_name[expected.name], expected)
        for expected in expected_checks
    ):
        raise ReleaseEvidenceCaptureError("integration check details do not match producer checks")


def _live_slice_summaries(cases: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, object]]]:
    result: dict[str, dict[str, dict[str, object]]] = {}
    for metric_name, (field_name, multi_value) in _LIVE_SLICE_FIELDS.items():
        grouped_passes: dict[str, list[bool]] = {}
        for case in cases:
            values = case[field_name] if multi_value else [case[field_name]]
            for value in values:
                grouped_passes.setdefault(value, []).append(case["passed"])
        result[metric_name] = {
            label: {
                "case_count": len(passes),
                "pass_rate": sum(passes) / len(passes),
            }
            for label, passes in grouped_passes.items()
        }
    return result


def _validate_live_slice_summaries(
    report_metrics: Mapping[str, Any],
    expected_groups: Mapping[str, Mapping[str, Mapping[str, object]]],
) -> None:
    for metric_name, expected_group in expected_groups.items():
        reported_group = report_metrics.get(metric_name)
        if not isinstance(reported_group, Mapping) or set(reported_group) != set(expected_group):
            raise ReleaseEvidenceCaptureError("live quality case details do not match aggregate")
        for label, expected_summary in expected_group.items():
            reported_summary = reported_group.get(label)
            if not isinstance(reported_summary, Mapping):
                raise ReleaseEvidenceCaptureError(
                    "live quality case details do not match aggregate"
                )
            reported_count = _require_int(
                reported_summary.get("case_count"),
                f"live quality slice {metric_name}.{label} case_count",
            )
            reported_rate = _require_float(
                reported_summary.get("pass_rate"),
                f"live quality slice {metric_name}.{label} pass_rate",
            )
            if reported_count != expected_summary["case_count"] or not _float_matches(
                reported_rate,
                float(expected_summary["pass_rate"]),
            ):
                raise ReleaseEvidenceCaptureError(
                    "live quality case details do not match aggregate"
                )


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


def _validate_integration_details(
    report: Mapping[str, Any],
    policy: IntegrationGatePolicy,
    metrics: IntegrationMetrics,
) -> None:
    _validate_integration_report_schema(report)
    checks = _detail_list(report, "checks", "integration check details")
    check_details = [_check_detail(check, "integration check details") for check in checks]
    checks_by_name: dict[str, dict[str, Any]] = {}
    for check, detail in zip(checks, check_details, strict=True):
        check_name = detail[1]
        if check_name in checks_by_name:
            raise ReleaseEvidenceCaptureError("integration check details contain a duplicate")
        checks_by_name[check_name] = check
    expected_check_codes = _integration_check_codes(policy)
    statuses = [detail[0] for detail in check_details]
    failure_counts = Counter(
        detail[3] for detail in check_details if detail[0] == "failed" and detail[3] is not None
    )
    report_metrics = _require_mapping(report.get("metrics"), "integration metrics")
    if (
        len(checks) != metrics.check_count
        or statuses.count("failed") != metrics.failed_count
        or statuses.count("blocked") != metrics.blocked_count
        or any(status != "passed" for status in statuses)
        or report_metrics.get("failure_type_counts") != dict(failure_counts)
        or set(checks_by_name) != set(expected_check_codes)
        or any(
            checks_by_name[check_name].get("code") != code
            for check_name, code in expected_check_codes.items()
        )
    ):
        raise ReleaseEvidenceCaptureError("integration check details do not match aggregate")

    cases = _detail_list(report, "cases", "integration case details")
    expected_case_ids = [case.case_id for case in policy.live_cases]
    expected_case_id_set = set(expected_case_ids)
    case_ids: list[str] = []
    cases_by_id: dict[str, dict[str, Any]] = {}
    executed_count = 0
    observation_count = 0
    estimated_costs: list[float] = []
    latencies: list[float] = []
    for case in cases:
        case_id = case.get("case_id")
        executed = case.get("executed")
        status = case.get("status")
        has_observation = case.get("has_observation")
        evidence_count = case.get("evidence_count")
        total_tokens = case.get("total_tokens")
        check_codes = case.get("check_codes")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id not in expected_case_id_set
            or not isinstance(executed, bool)
            or status not in _GATE_STATUSES
            or not isinstance(has_observation, bool)
            or isinstance(evidence_count, bool)
            or not isinstance(evidence_count, int)
            or evidence_count < 0
            or isinstance(total_tokens, bool)
            or not isinstance(total_tokens, int)
            or total_tokens < 0
            or check_codes != list(_INTEGRATION_CASE_CHECK_CODES.values())
        ):
            raise ReleaseEvidenceCaptureError("integration case details are invalid")
        latency = _require_float(case.get("latency_ms"), "integration case latency")
        estimated_cost = _require_float(
            case.get("estimated_cost_usd"),
            "integration case estimated cost",
        )
        if latency < 0 or estimated_cost < 0:
            raise ReleaseEvidenceCaptureError("integration case details are invalid")
        case_ids.append(case_id)
        cases_by_id[case_id] = case
        executed_count += int(executed)
        observation_count += int(has_observation)
        latencies.append(latency)
        estimated_costs.append(estimated_cost)
        if not executed or status != "passed" or not has_observation:
            raise ReleaseEvidenceCaptureError("integration case details did not pass")
        expected_actuals = {
            "evidence_count": evidence_count,
            "fallback": False,
            "retrieval_degradation": False,
            "model_usage": total_tokens,
        }
        if any(
            not _evidence_value_matches(
                checks_by_name[f"case.{case_id}.{suffix}"].get("actual"),
                actual,
            )
            for suffix, actual in expected_actuals.items()
        ):
            raise ReleaseEvidenceCaptureError("integration check details do not match case details")
    total_estimated_cost = _require_float(
        report_metrics.get("total_estimated_cost_usd"),
        "integration total estimated cost",
    )
    max_latency = _require_float(
        report_metrics.get("max_latency_ms"),
        "integration max latency",
    )
    if (
        len(cases) != metrics.case_count
        or executed_count != metrics.executed_case_count
        or observation_count != metrics.observation_count
        or len(case_ids) != len(set(case_ids))
        or case_ids != expected_case_ids
        or not _float_matches(total_estimated_cost, round(sum(estimated_costs), 6))
        or not _float_matches(max_latency, round(max(latencies), 3))
    ):
        raise ReleaseEvidenceCaptureError("integration case details do not match aggregate")
    _validate_integration_check_payloads(
        checks_by_name,
        cases_by_id,
        policy,
        total_estimated_cost=total_estimated_cost,
        latencies=latencies,
    )


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
    _validate_integration_details(report, policy, projected)
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


def _validate_live_quality_details(
    report: Mapping[str, Any],
    policy: LiveQualityGatePolicy,
    metrics: QualityMetrics,
) -> None:
    _validate_live_report_schema(report, policy)
    checks = _detail_list(report, "checks", "live quality check details")
    checks_by_name: dict[str, dict[str, Any]] = {}
    failure_counts: Counter[str] = Counter()
    for check in checks:
        status, check_name, code, failure_type = _check_detail(
            check,
            "live quality check details",
        )
        if check_name in checks_by_name:
            raise ReleaseEvidenceCaptureError("live quality check details contain a duplicate")
        checks_by_name[check_name] = check
        if status == "failed" and failure_type is not None:
            failure_counts[failure_type] += 1
        non_blocking = (
            status == "failed"
            and check_name.startswith("case.")
            and code in _NON_BLOCKING_LIVE_QUALITY_CODES
            and failure_type == "quality-regression"
        )
        if status != "passed" and not non_blocking:
            raise ReleaseEvidenceCaptureError(
                "live quality check details contain a blocking failure"
            )
    reported_counts = report.get("failure_type_counts")
    if not isinstance(reported_counts, dict) or reported_counts != dict(failure_counts):
        raise ReleaseEvidenceCaptureError("live quality check details do not match aggregate")

    projected_metrics = metrics.model_dump()
    report_metrics = _require_mapping(report.get("metrics"), "live quality metrics")

    cases = _detail_list(report, "cases", "live quality case details")
    policies_by_id = {case.case_id: case for case in policy.cases}
    case_ids: list[str] = []
    passed_count = 0
    deterministic_passed_count = 0
    judge_results: list[bool] = []
    expected_case_checks: list[GateCheckResult] = []
    normalized_cases: list[dict[str, Any]] = []
    retrieval_metrics: dict[str, list[float]] = {name: [] for name in _CASE_RETRIEVAL_METRIC_NAMES}
    for case in cases:
        case_id = case.get("case_id")
        passed = case.get("passed")
        deterministic_passed = case.get("deterministic_passed")
        judge_passed = case.get("judge_passed")
        judge_scores = case.get("judge_scores")
        failures = case.get("failures")
        case_metrics = case.get("metrics")
        query_type = case.get("query_type")
        cuisine = case.get("cuisine")
        constraint_types = case.get("constraint_types")
        risk_tags = case.get("risk_tags")
        response_mode = case.get("response_mode")
        strategy = case.get("strategy")
        manual_review = case.get("manual_review")
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id not in policies_by_id
            or not isinstance(passed, bool)
            or not isinstance(deterministic_passed, bool)
            or not isinstance(failures, list)
            or not all(isinstance(failure, str) and failure for failure in failures)
            or failures != sorted(set(failures))
            or not isinstance(case_metrics, dict)
            or (judge_passed is not None and not isinstance(judge_passed, bool))
            or (policy.judge.required and not isinstance(judge_passed, bool))
            or not isinstance(query_type, str)
            or not isinstance(cuisine, str)
            or not isinstance(constraint_types, list)
            or not all(isinstance(value, str) for value in constraint_types)
            or not isinstance(risk_tags, list)
            or not all(isinstance(value, str) for value in risk_tags)
            or not isinstance(response_mode, str)
            or not isinstance(strategy, str)
            or not strategy
            or not isinstance(manual_review, dict)
            or case.get("status") in {"failed", "blocked", "error"}
        ):
            raise ReleaseEvidenceCaptureError("live quality case details are invalid")

        case_policy = policies_by_id[case_id]
        if (
            query_type != case_policy.query_type
            or cuisine != case_policy.cuisine
            or constraint_types != case_policy.constraint_types
            or risk_tags != case_policy.risk_tags
            or response_mode != case_policy.expected_response_mode.value
            or manual_review
            != {
                "owner": case_policy.manual_review.owner,
                "sample": case_policy.manual_review.sample,
            }
            or ("strategy_mismatch" in failures) == (strategy in case_policy.allowed_strategies)
        ):
            raise ReleaseEvidenceCaptureError("live quality case details are invalid")

        if not isinstance(judge_scores, dict):
            raise ReleaseEvidenceCaptureError("live quality case details are invalid")
        if policy.judge.required:
            if set(judge_scores) != set(policy.judge.score_names):
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
            normalized_scores = {
                name: _require_float(
                    judge_scores[name],
                    f"live quality judge score {name}",
                )
                for name in policy.judge.score_names
            }
            if any(not 0.0 <= score <= 1.0 for score in normalized_scores.values()) or (
                judge_passed is True
                and any(score < policy.judge.minimum_score for score in normalized_scores.values())
            ):
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
        else:
            if judge_passed is not None or judge_scores:
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
            normalized_scores = {}

        grounded_case = not case_policy.expected_response_mode.is_abstention
        for metric_name in _CASE_RETRIEVAL_METRIC_NAMES:
            if metric_name not in case_metrics:
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
            value = case_metrics[metric_name]
            if not grounded_case:
                if value is not None:
                    raise ReleaseEvidenceCaptureError("live quality case details are invalid")
                continue
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
            projected_value = _require_float(
                value,
                f"live quality case metric {metric_name}",
            )
            if not 0.0 <= projected_value <= 1.0:
                raise ReleaseEvidenceCaptureError("live quality case details are invalid")
            retrieval_metrics[metric_name].append(projected_value)
        expected_deterministic = not failures
        expected_passed = expected_deterministic and (
            judge_passed if judge_passed is not None else True
        )
        if deterministic_passed is not expected_deterministic or passed is not expected_passed:
            raise ReleaseEvidenceCaptureError("live quality case details do not match aggregate")
        deterministic_name = f"case.{case_id}.deterministic"
        if deterministic_passed:
            expected_case_checks.append(
                GateCheckResult.pass_check(
                    deterministic_name,
                    code="DETERMINISTIC_QUALITY_OK",
                )
            )
        else:
            expected_case_checks.append(
                GateCheckResult.fail_check(
                    deterministic_name,
                    failure_type=GateFailureType.QUALITY_REGRESSION,
                    code="DETERMINISTIC_QUALITY_FAILED",
                    actual=list(failures),
                )
            )
        if policy.judge.required:
            judge_name = f"case.{case_id}.judge"
            judge_expected = {"minimum_score": policy.judge.minimum_score}
            if judge_passed:
                expected_case_checks.append(
                    GateCheckResult.pass_check(
                        judge_name,
                        code="JUDGE_QUALITY_OK",
                        expected=judge_expected,
                        actual=normalized_scores,
                    )
                )
            else:
                expected_case_checks.append(
                    GateCheckResult.fail_check(
                        judge_name,
                        failure_type=GateFailureType.QUALITY_REGRESSION,
                        code="JUDGE_QUALITY_FAILED",
                        expected=judge_expected,
                        actual=normalized_scores,
                    )
                )
        case_ids.append(case_id)
        passed_count += int(passed)
        deterministic_passed_count += int(deterministic_passed)
        if judge_passed is not None:
            judge_results.append(judge_passed)
        normalized_cases.append(
            {
                "query_type": query_type,
                "cuisine": cuisine,
                "constraint_types": constraint_types,
                "risk_tags": risk_tags,
                "response_mode": response_mode,
                "strategy": strategy,
                "passed": passed,
            }
        )

    case_count = len(cases)
    expected_judge_rate = sum(judge_results) / len(judge_results) if judge_results else 0.0
    if (
        case_count != metrics.case_count
        or len(case_ids) != len(set(case_ids))
        or case_ids != [case.case_id for case in policy.cases]
        or not _float_matches(metrics.pass_rate, passed_count / case_count)
        or not _float_matches(
            metrics.deterministic_pass_rate,
            deterministic_passed_count / case_count,
        )
        or not _float_matches(metrics.judge_pass_rate, expected_judge_rate)
        or any(
            not values
            or not _float_matches(
                projected_metrics[metric_name],
                sum(values) / len(values),
            )
            for metric_name, values in retrieval_metrics.items()
        )
    ):
        raise ReleaseEvidenceCaptureError("live quality case details do not match aggregate")

    slice_summaries = _live_slice_summaries(normalized_cases)
    _validate_live_slice_summaries(report_metrics, slice_summaries)
    evaluation_metrics = dict(report_metrics)
    evaluation_metrics.update(projected_metrics)
    evaluation_metrics.update(slice_summaries)
    expected_checks = expected_case_checks + list(
        evaluate_policy_thresholds(policy, evaluation_metrics)
    )
    expected_checks_by_name = {check.name: check for check in expected_checks}
    if len(expected_checks_by_name) != len(expected_checks) or set(checks_by_name) != set(
        expected_checks_by_name
    ):
        raise ReleaseEvidenceCaptureError("live quality check details do not match producer checks")
    if any(
        not _gate_check_matches(checks_by_name[name], expected)
        for name, expected in expected_checks_by_name.items()
    ):
        raise ReleaseEvidenceCaptureError("live quality check details do not match producer checks")


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
    _validate_live_quality_details(report, policy, projected)
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


def _normalized_target_hostname(value: object) -> str:
    if not isinstance(value, str):
        raise ReleaseEvidenceCaptureError("gate target hostname is invalid")
    try:
        TargetIdentity(api_host=value, judge_host="judge.example.com")
    except ValidationError as exc:
        raise ReleaseEvidenceCaptureError("gate target hostname is invalid") from exc
    text = value.casefold()
    if text.startswith("["):
        parsed = urlsplit(f"//{text}")
        return str(ip_address(parsed.hostname or ""))
    try:
        return str(ip_address(text))
    except ValueError:
        pass
    if text.count(":") == 1:
        hostname, port_text = text.rsplit(":", 1)
        if port_text.isdecimal() and 1 <= int(port_text) <= 65535:
            try:
                return str(ip_address(hostname))
            except ValueError:
                return hostname
    return text


def _require_same_gate_target(
    integration_target: Mapping[str, Any],
    live_target: Mapping[str, Any],
) -> None:
    integration_hostname = _normalized_target_hostname(
        integration_target.get("api_host"),
    )
    live_hostname = _normalized_target_hostname(
        live_target.get("api_host"),
    )
    if integration_hostname != live_hostname:
        raise ReleaseEvidenceCaptureError(
            "integration and live quality gate target hostnames differ"
        )


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


def _normalized_key(value: str) -> str:
    separated = _CAMEL_CASE_BOUNDARY_RE.sub("_", value)
    return _NON_KEY_CHARACTER_RE.sub("_", separated).strip("_").casefold()


def _is_sensitive_key(value: str) -> bool:
    normalized = _normalized_key(value)
    return (
        normalized in _SAFE_TOKEN_METRIC_KEYS
        or normalized in _SENSITIVE_KEYS
        or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)
    )


def _is_safe_token_metric(path: str, key: str, value: object) -> bool:
    return (
        _normalized_key(key) in _SAFE_TOKEN_METRIC_KEYS
        and _SAFE_TOKEN_METRIC_PATH_RE.fullmatch(path) is not None
        and not isinstance(value, bool)
        and isinstance(value, int | float)
        and (isinstance(value, int) or math.isfinite(value))
        and value >= 0
    )


def _is_allowed_api_route(value: str, field_name: str | None) -> bool:
    return (
        field_name is not None
        and _normalized_key(field_name) in _API_ROUTE_FIELD_KEYS
        and _VERSIONED_API_ROUTE_RE.fullmatch(value) is not None
    )


def _credential_url_present(value: str) -> bool:
    for match in _URI_RE.finditer(value):
        url = match.group(0).rstrip(".,);]")
        try:
            parsed = urlsplit(url)
            if parsed.username is not None or parsed.password is not None:
                return True
            if parsed.scheme.casefold() == "file":
                return True
            if any(
                _is_sensitive_key(key) for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
            ):
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
        or _ABSOLUTE_FORWARD_UNC_PATH_RE.search(value)
        or _ABSOLUTE_UNIX_PATH_RE.search(value)
        or _credential_url_present(value)
        or _TRACEBACK_RE.search(value)
        or _EXCEPTION_VALUE_RE.search(value)
    )


def _scan_json(
    value: object,
    path: str = "$",
    *,
    field_name: str | None = None,
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            item_path = f"{path}.{key_text}"
            if _is_sensitive_key(key_text) and not _is_safe_token_metric(
                item_path,
                key_text,
                item,
            ):
                raise ReleaseEvidenceCaptureError(f"sensitive release evidence key at {item_path}")
            _scan_json(item, item_path, field_name=key_text)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _scan_json(item, f"{path}[{index}]")
        return
    if (
        isinstance(value, str)
        and not _is_allowed_api_route(value, field_name)
        and _sensitive_text_present(value)
    ):
        raise ReleaseEvidenceCaptureError(f"sensitive release evidence value at {path}")


def _scan_source(name: str, data: bytes) -> None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseEvidenceCaptureError(f"release evidence text is invalid: {name}") from exc
    if name.endswith(".json"):
        try:
            payload = json.loads(
                text,
                object_pairs_hook=_json_object_without_duplicate_keys,
            )
        except _DuplicateJsonKeyError as exc:
            raise ReleaseEvidenceCaptureError(
                f"release evidence JSON contains a duplicate key: {name}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise ReleaseEvidenceCaptureError(f"release evidence JSON is invalid: {name}") from exc
        _scan_json(payload, f"{name}:$")
        return
    if name.endswith(".jsonl"):
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(
                    line,
                    object_pairs_hook=_json_object_without_duplicate_keys,
                )
            except _DuplicateJsonKeyError as exc:
                raise ReleaseEvidenceCaptureError(
                    f"release evidence JSONL contains a duplicate key: {name}:{line_number}"
                ) from exc
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

    _scan_json(integration_report, "integration_gate/report.json:$")
    _scan_json(live_report, "live_quality_gate/report.json:$")

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
    manual_review_rows = _parse_manual_review_jsonl(
        manual_review_bytes,
        "live_quality_gate/manual_review_sample.jsonl",
    )
    for line_number, row in enumerate(manual_review_rows, start=1):
        _scan_json(row, f"live_quality_gate/manual_review_sample.jsonl:{line_number}")

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
        integration_target = _require_mapping(
            integration_report.get("target"),
            "integration target",
        )
        _require_same_gate_target(integration_target, target)
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
    _validate_manual_review_binding(live_report, live_policy, manual_review_rows)
    if len(manual_review_rows) != quality.manual_review_sample_count:
        raise ReleaseEvidenceCaptureError("manual review sample count does not match JSONL")
    if integration_summary_bytes != render_integration_summary(integration_report):
        raise ReleaseEvidenceCaptureError("integration summary does not match validated report")
    if live_summary_bytes != render_live_quality_summary(live_report):
        raise ReleaseEvidenceCaptureError("live quality summary does not match validated report")

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

    already_scanned = {
        "integration_gate/report.json",
        "live_quality_gate/report.json",
        "live_quality_gate/manual_review_sample.jsonl",
    }
    for name, data in source_entries.items():
        if name in already_scanned:
            continue
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
