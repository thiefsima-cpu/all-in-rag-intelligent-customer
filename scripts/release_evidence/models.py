from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CAPTURE_SCHEMA_VERSION = "graph-rag-release-evidence-capture-v1"
MANIFEST_SCHEMA_VERSION = "graph-rag-release-evidence-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
PositiveInt = Annotated[int, Field(ge=1)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]
T = TypeVar("T", bound="StrictEvidenceModel")


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


def _validate_timestamp(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid ISO-8601 timestamp") from exc
    return value


class ReleaseIdentity(StrictEvidenceModel):
    package_version: str = Field(min_length=1)
    tag: str = Field(min_length=1)


class Provenance(StrictEvidenceModel):
    repository: str
    evaluated_commit: str
    generated_at: str = Field(min_length=1)

    @field_validator("repository")
    @classmethod
    def validate_repository(cls, value: str) -> str:
        if not _REPOSITORY_RE.fullmatch(value):
            raise ValueError("invalid repository identity")
        return value

    @field_validator("evaluated_commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if not _GIT_SHA_RE.fullmatch(value):
            raise ValueError("invalid evaluated commit")
        return value

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_timestamp(value)


class IntegrationMetrics(StrictEvidenceModel):
    check_count: PositiveInt
    failed_count: NonNegativeInt
    blocked_count: NonNegativeInt
    case_count: PositiveInt
    executed_case_count: PositiveInt
    observation_count: PositiveInt


class IntegrationEvidence(StrictEvidenceModel):
    passed: bool
    report_schema_version: int
    generated_at: str = Field(min_length=1)
    metrics: IntegrationMetrics

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_timestamp(value)


class QualityMetrics(StrictEvidenceModel):
    case_count: PositiveInt
    pass_rate: Rate
    deterministic_pass_rate: Rate
    judge_pass_rate: Rate
    recall_at_k: Rate
    mrr: Rate
    ndcg_at_k: Rate
    fallback_rate: Rate
    retrieval_degradation_rate: Rate
    p95_latency_ms: NonNegativeFloat
    estimated_cost_usd: NonNegativeFloat


class QualityEvidence(StrictEvidenceModel):
    passed: bool
    report_schema_version: int
    generated_at: str = Field(min_length=1)
    metrics: QualityMetrics
    manual_review_sample_count: NonNegativeInt

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: str) -> str:
        return _validate_timestamp(value)


class TargetIdentity(StrictEvidenceModel):
    api_host: str = Field(min_length=1)
    judge_host: str = Field(min_length=1)

    @field_validator("*")
    @classmethod
    def validate_safe_host(cls, value: str) -> str:
        if any(character in value for character in ("/", "@", "?", "#")):
            raise ValueError("invalid safe host identity")
        if any(character.isspace() for character in value):
            raise ValueError("invalid safe host identity")
        return value


class ProfileIdentity(StrictEvidenceModel):
    name: str = Field(min_length=1)
    path: str = Field(pattern=r"^profiles/[A-Za-z0-9_.-]+\.toml$")
    resolved_sha256: str

    @field_validator("resolved_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("invalid profile sha256")
        return value


class ModelSuiteIdentity(StrictEvidenceModel):
    llm: str
    embedding: str
    rerank: str
    judge: str

    @field_validator("*")
    @classmethod
    def validate_label(cls, value: str) -> str:
        if not _LABEL_RE.fullmatch(value):
            raise ValueError("invalid model label")
        return value


class RuntimeIdentity(StrictEvidenceModel):
    target: TargetIdentity
    profile: ProfileIdentity
    models: ModelSuiteIdentity


class DatasetIdentity(StrictEvidenceModel):
    path: Literal["eval/live_quality_gate.json"]
    schema_version: int
    case_count: PositiveInt
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("invalid dataset sha256")
        return value


class KnowledgeBaseIdentity(StrictEvidenceModel):
    schema_version: str = Field(min_length=1)
    manifest_version: PositiveInt
    stage: Literal["ready"]
    health: Literal["ready"]
    published_at: str = Field(min_length=1)
    index_version: str = Field(min_length=1)
    collection_name: str = Field(min_length=1)
    graph_signature: str = Field(min_length=1)
    document_signature: str = Field(min_length=1)
    embedding_signature: str = Field(min_length=1)
    index_signature: str = Field(min_length=1)
    total_documents: PositiveInt
    total_chunks: PositiveInt
    vector_rows: PositiveInt

    @field_validator("published_at")
    @classmethod
    def validate_published_at(cls, value: str) -> str:
        return _validate_timestamp(value)


class FileIdentity(StrictEvidenceModel):
    name: str
    path: str
    bytes: NonNegativeInt
    sha256: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not _LABEL_RE.fullmatch(value):
            raise ValueError("invalid artifact name")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        posix_candidate = PurePosixPath(value)
        windows_candidate = PureWindowsPath(value)
        if (
            not posix_candidate.parts
            or posix_candidate.root
            or posix_candidate.drive
            or windows_candidate.root
            or windows_candidate.drive
            or ".." in posix_candidate.parts
            or "\\" in value
        ):
            raise ValueError("invalid artifact path")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("invalid artifact sha256")
        return value


class BundleIdentity(StrictEvidenceModel):
    name: str = Field(pattern=r"^graph-rag-c9-[A-Za-z0-9.]+-quality-evidence\.zip$")
    bytes: PositiveInt
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("invalid bundle sha256")
        return value


class EvidenceCore(StrictEvidenceModel):
    release: ReleaseIdentity
    provenance: Provenance
    integration: IntegrationEvidence
    quality: QualityEvidence
    runtime: RuntimeIdentity
    dataset: DatasetIdentity
    knowledge_base: KnowledgeBaseIdentity
    bundle: BundleIdentity
    artifacts: list[FileIdentity] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_artifacts(self) -> Self:
        names = [artifact.name for artifact in self.artifacts]
        paths = [artifact.path for artifact in self.artifacts]
        if len(names) != len(set(names)) or len(paths) != len(set(paths)):
            raise ValueError("release evidence artifacts must be unique")
        return self


class CaptureReceipt(EvidenceCore):
    schema_version: Literal[CAPTURE_SCHEMA_VERSION] = CAPTURE_SCHEMA_VERSION


class TransportIdentity(StrictEvidenceModel):
    provider: Literal["github-actions"]
    workflow_run_id: PositiveInt
    workflow_head_sha: str
    artifact_id: PositiveInt
    artifact_name: str = Field(min_length=1)
    artifact_digest: str

    @field_validator("workflow_head_sha")
    @classmethod
    def validate_head_sha(cls, value: str) -> str:
        if not _GIT_SHA_RE.fullmatch(value):
            raise ValueError("invalid workflow head sha")
        return value

    @field_validator("artifact_digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not _ARTIFACT_DIGEST_RE.fullmatch(value):
            raise ValueError("invalid artifact digest")
        return value


class ReleaseEvidenceManifest(EvidenceCore):
    schema_version: Literal[MANIFEST_SCHEMA_VERSION] = MANIFEST_SCHEMA_VERSION
    transport: TransportIdentity


class GitHubWorkflowRun(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)

    id: PositiveInt
    head_sha: str

    @field_validator("head_sha")
    @classmethod
    def validate_head_sha(cls, value: str) -> str:
        if not _GIT_SHA_RE.fullmatch(value):
            raise ValueError("invalid workflow run head sha")
        return value


class GitHubArtifactMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)

    id: PositiveInt
    name: str = Field(min_length=1)
    size_in_bytes: NonNegativeInt
    expired: bool
    digest: str
    workflow_run: GitHubWorkflowRun

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        if not _ARTIFACT_DIGEST_RE.fullmatch(value):
            raise ValueError("invalid GitHub artifact digest")
        return value


def _load_model(path: str | Path, model: type[T]) -> T:
    return model.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_capture_receipt(path: str | Path) -> CaptureReceipt:
    return _load_model(path, CaptureReceipt)


def load_release_evidence_manifest(path: str | Path) -> ReleaseEvidenceManifest:
    return _load_model(path, ReleaseEvidenceManifest)


def write_evidence_model(model: StrictEvidenceModel, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(
            model.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_path
