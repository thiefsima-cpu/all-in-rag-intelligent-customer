# Release Quality Evidence Traceability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add machine-verifiable release quality evidence that binds successful live gates to an
evaluated commit, runtime profile, model suite, dataset, knowledge-base artifact, complete report
bundle, and durable draft GitHub Release assets.

**Architecture:** A new `scripts.release_evidence` package validates existing integration and live
quality reports, creates a deterministic complete ZIP, finalizes a compact Git manifest after the
ZIP is uploaded to GitHub Actions, and verifies Git, artifact, and bundle provenance before release.
A manual pre-release workflow performs capture or pre-tag verification; the tag workflow retrieves
the selected artifact, reruns verification, and creates or updates a draft GitHub Release.

**Tech Stack:** Python 3.11, Pydantic 2, standard-library `hashlib`, `json`, `subprocess`,
`tomllib`, and `zipfile`, Requests, pytest, Git, GitHub Actions, GitHub CLI, TOML, JSON, YAML, and
Markdown.

## Global Constraints

- Python must remain `>=3.11,<3.12`; run all Python checks with Python 3.11.
- Use test-driven development: every behavior change starts with a focused failing test.
- Add no runtime or development dependency; do not edit generated lock files.
- Keep the integration, live quality, and deterministic offline release gates independent.
- Do not add or extend a production API endpoint.
- Do not commit complete gate reports or generated evidence ZIP files.
- Only `quality-evidence/releases/<package-version>/evidence-manifest.json` counts as release
  success evidence.
- Reject `case_count=0`, failed reports, missing judge metrics, non-ready knowledge artifacts,
  missing signatures, non-finite metrics, and mismatched hashes.
- Store only safe host identities, stable labels, repository-relative paths, aggregate metrics,
  signatures, counts, and digests in Git.
- Never retain API keys, bearer tokens, Authorization headers, passwords, raw exceptions,
  credential-bearing URLs, customer data, or absolute workstation paths.
- The current repository uses 40-character SHA-1 Git object IDs.
- The tagged release tree may differ from `evaluated_commit` only by the selected compact manifest.
- Use the existing `actions/checkout@v7`, `actions/setup-python@v6`, and
  `actions/upload-artifact@v7` majors.
- Release evidence capture uses the maximum repository-supported Actions artifact retention window.
- A published tag and its selected manifest are immutable; corrections require a new version or an
  explicit erratum.

## File Structure

Create:

- `scripts/release_evidence/__init__.py`: supported public exports.
- `scripts/release_evidence/__main__.py`: `python -m scripts.release_evidence` entrypoint.
- `scripts/release_evidence/models.py`: strict source, capture, final-manifest, and GitHub artifact
  models.
- `scripts/release_evidence/capture.py`: source validation, safe projection, hashing, and
  deterministic ZIP creation.
- `scripts/release_evidence/finalize.py`: bind capture output to immutable Actions metadata.
- `scripts/release_evidence/verifier.py`: Git, artifact metadata, ZIP, report, policy, profile, and
  knowledge-summary verification.
- `scripts/release_evidence/cli.py`: `capture`, `finalize`, and `verify` commands.
- `tests/release_evidence_fixtures.py`: reusable temporary repository and report builders.
- `tests/test_release_evidence_models.py`: strict schema tests.
- `tests/test_release_evidence_capture.py`: capture and deterministic bundle tests.
- `tests/test_release_evidence_finalize.py`: transport binding tests.
- `tests/test_release_evidence_verifier.py`: Git, remote metadata, and bundle verification tests.
- `tests/test_release_evidence_cli.py`: CLI error and output tests.
- `tests/test_release_evidence_workflows.py`: workflow ordering and release-publication contracts.
- `.github/workflows/release-evidence.yml`: manual capture and pre-tag verification workflow.
- `quality-evidence/README.md`: discovery and historical-attempt semantics.

Modify:

- `pyproject.toml`: register `graph-rag-release-evidence`.
- `tests/test_entrypoints.py`: enforce the console and module entrypoints.
- `.github/workflows/release.yml`: verify evidence and create/update a draft Release.
- `tests/test_enterprise_governance.py`: enforce release workflow and documentation requirements.
- `.env.example`: document the artifact-manifest path used by capture runners.
- `docs/live_quality_gate.md`: document evidence capture.
- `docs/release_process.md`: make pre-tag verification and Release assets mandatory.

---

### Task 1: Define Strict Evidence Contracts And Test Fixtures

**Files:**
- Create: `scripts/release_evidence/models.py`
- Create: `scripts/release_evidence/__init__.py`
- Create: `tests/release_evidence_fixtures.py`
- Create: `tests/test_release_evidence_models.py`

**Interfaces:**
- Consumes: JSON-compatible source reports and finalized manifest payloads.
- Produces: `CaptureReceipt`, `ReleaseEvidenceManifest`, `GitHubArtifactMetadata`,
  `load_capture_receipt(path)`, `load_release_evidence_manifest(path)`, and
  `write_evidence_model(model, path)`.

- [ ] **Step 1: Add reusable fixture builders**

Create `tests/release_evidence_fixtures.py` with:

```python
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rag_modules.configuration.profiles import load_profile
from rag_modules.kernel.artifacts import ArtifactManifest


@dataclass(frozen=True)
class ReleaseEvidenceFixture:
    repository_root: Path
    evaluated_commit: str
    integration_policy: Path
    live_quality_policy: Path
    integration_report: Path
    live_quality_report: Path
    diagnostics: Path
    artifact_manifest: Path
    output_dir: Path


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def git(repository_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def make_release_evidence_fixture(tmp_path: Path) -> ReleaseEvidenceFixture:
    repository_root = tmp_path / "repository"
    inputs_root = tmp_path / "inputs"
    output_dir = tmp_path / "output"
    profiles_dir = repository_root / "profiles"
    eval_dir = repository_root / "eval"
    profiles_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)

    (repository_root / "pyproject.toml").write_text(
        '[project]\nname = "graph-rag-c9"\nversion = "0.4.0rc1"\n',
        encoding="utf-8",
    )
    (profiles_dir / "base.toml").write_text(
        "[api]\nauth_enabled = true\n",
        encoding="utf-8",
    )
    (profiles_dir / "eval_quality.toml").write_text(
        "[retrieval]\ntop_k = 6\n",
        encoding="utf-8",
    )

    integration_policy = write_json(
        eval_dir / "integration_gate.json",
        {
            "schema_version": 1,
            "dependency_minimums": {
                "neo4j_recipe_count": 1,
                "milvus_entity_count": 1,
            },
            "timeouts": {"probe_seconds": 10.0, "request_seconds": 90.0},
            "thresholds": {
                "maximum_fallback_rate": 0.0,
                "maximum_retrieval_degradation_rate": 0.0,
                "maximum_p95_latency_ms": 60000.0,
                "maximum_estimated_cost_usd": 1.0,
            },
            "live_cases": [
                {
                    "case_id": "vector_recipe_lookup",
                    "question": "How do I make mapo tofu?",
                    "allowed_strategies": ["hybrid_traditional"],
                    "required_sources": ["vector"],
                    "minimum_evidence_count": 1,
                    "generation_required": True,
                    "timeout_seconds": 60.0,
                }
            ],
        },
    )
    live_quality_policy = write_json(
        eval_dir / "live_quality_gate.json",
        {
            "schema_version": 1,
            "top_k": 6,
            "timeouts": {"request_seconds": 90.0, "judge_seconds": 45.0},
            "judge": {
                "required": True,
                "score_names": [
                    "faithfulness",
                    "answer_relevance",
                    "safety",
                    "completeness",
                ],
                "minimum_score": 0.8,
            },
            "thresholds": {
                "minimum_case_count": 1,
                "minimum_pass_rate": 0.85,
                "minimum_deterministic_pass_rate": 0.85,
                "minimum_judge_pass_rate": 0.85,
                "minimum_recall_at_k": 0.7,
                "minimum_mrr": 0.6,
                "minimum_ndcg_at_k": 0.7,
                "maximum_fallback_rate": 0.0,
                "maximum_retrieval_degradation_rate": 0.0,
                "maximum_p95_latency_ms": 60000.0,
                "maximum_estimated_cost_usd": 2.0,
            },
            "required_slice_coverage": {
                "risk_tags": {},
                "query_types": {},
                "cuisines": {},
                "constraint_types": {},
                "response_modes": {},
            },
            "slice_thresholds": {
                "risk_tags": {},
                "query_types": {},
                "cuisines": {},
                "constraint_types": {},
                "response_modes": {},
                "strategies": {},
            },
            "cases": [
                {
                    "case_id": "grounded_mapo_tofu",
                    "query": "How do I make mapo tofu?",
                    "query_type": "single_recipe",
                    "cuisine": "sichuan",
                    "constraint_types": [],
                    "risk_tags": [],
                    "expected_response_mode": "grounded_answer",
                    "allowed_strategies": ["hybrid_traditional"],
                    "required_sources": ["vector"],
                    "relevant_recipes": {"Mapo Tofu": 3.0},
                    "must_include_facts": ["tofu"],
                    "must_not_claim": ["palace secret recipe"],
                    "judge_rubric": {
                        "faithfulness": "Use only the evidence.",
                        "answer_relevance": "Answer the question.",
                        "safety": "Do not invent unsafe claims.",
                        "completeness": "Identify the dish.",
                    },
                    "manual_review": {
                        "owner": "business-quality",
                        "sample": True,
                    },
                }
            ],
        },
    )

    integration_dir = inputs_root / "integration_gate"
    live_dir = inputs_root / "live_quality_gate"
    write_json(
        integration_dir / "report.json",
        {
            "schema_version": 1,
            "generated_at": "2026-07-16T07:55:00+00:00",
            "passed": True,
            "target": {
                "api_host": "quality.example.com",
                "neo4j_host": "neo4j.example.com",
                "milvus_host": "milvus.example.com",
            },
            "metrics": {
                "check_count": 10,
                "failed_count": 0,
                "blocked_count": 0,
                "case_count": 1,
                "executed_case_count": 1,
                "observation_count": 1,
                "failure_type_counts": {},
                "total_estimated_cost_usd": 0.01,
                "max_latency_ms": 1000.0,
            },
            "checks": [],
            "cases": [],
            "artifacts": {
                "report_json": "report.json",
                "summary_md": "summary.md",
            },
        },
    )
    (integration_dir / "summary.md").write_text(
        "# Real-Dependency Integration Gate\n\nStatus: PASS\n",
        encoding="utf-8",
    )
    write_json(
        live_dir / "report.json",
        {
            "schema_version": 1,
            "generated_at": "2026-07-16T07:50:00+00:00",
            "passed": True,
            "target": {
                "api_host": "quality.example.com",
                "judge_host": "judge.example.com",
            },
            "top_k": 6,
            "metrics": {
                "case_count": 1,
                "pass_rate": 1.0,
                "deterministic_pass_rate": 1.0,
                "judge_pass_rate": 1.0,
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
                "fallback_rate": 0.0,
                "retrieval_degradation_rate": 0.0,
                "p95_latency_ms": 1000.0,
                "estimated_cost_usd": 0.02,
                "avg_judge_scores": {
                    "faithfulness": 1.0,
                    "answer_relevance": 1.0,
                },
                "by_query_type": {},
                "by_cuisine": {},
                "by_constraint_type": {},
                "by_risk_tag": {},
                "by_response_mode": {},
                "by_strategy": {},
            },
            "failure_type_counts": {},
            "checks": [],
            "cases": [],
            "manual_review_sample_count": 1,
            "manual_review_sample": [],
            "artifacts": {
                "report_json": "report.json",
                "summary_md": "summary.md",
                "manual_review_sample_jsonl": "manual_review_sample.jsonl",
            },
        },
    )
    (live_dir / "summary.md").write_text(
        "# Live Quality Gate\n\nStatus: PASS\n",
        encoding="utf-8",
    )
    (live_dir / "manual_review_sample.jsonl").write_text(
        '{"case_id":"grounded_mapo_tofu","must_not_claim":"palace secret recipe"}\n',
        encoding="utf-8",
    )

    diagnostics = write_json(
        inputs_root / "diagnostics.json",
        {
            "diagnostics": {
                "mode": "serve",
                "llm_model": "qwen3.7-plus",
                "embedding_model": "qwen3-vl-embedding",
                "rerank_model": "qwen3-vl-rerank",
                "trace_enabled": True,
                "trace_path": "storage/traces/query_trace.jsonl",
                "trace_stats": {},
                "build_initialized": True,
                "serving_initialized": True,
                "artifacts_ready": True,
                "system_ready": True,
                "retrieval_engines_initialized": True,
                "manifest": {},
                "build_job_store": {},
            }
        },
    )

    profile = load_profile(profile="eval_quality", profiles_dir=profiles_dir)
    artifact_manifest = ArtifactManifest(
        manifest_version=7,
        stage="ready",
        published_at="2026-07-16T07:30:00+00:00",
        graph_signature="graph-signature",
        document_signature="document-signature",
        embedding_signature="embedding-signature",
        index_signature="index-signature",
        index_version="v000007",
        collection_name="cooking_knowledge__active",
        total_documents=323,
        total_chunks=1543,
        vector_rows=1543,
        build_metadata={
            "config_profile": {
                "name": profile.name,
                "path": profile.path,
                "hash": profile.profile_hash,
            }
        },
    )
    artifact_manifest_path = write_json(
        inputs_root / "artifact_manifest.json",
        artifact_manifest.to_dict(),
    )

    git(repository_root, "init")
    git(repository_root, "config", "user.email", "tests@example.com")
    git(repository_root, "config", "user.name", "Release Evidence Tests")
    git(repository_root, "add", ".")
    git(repository_root, "commit", "-m", "test: initialize release candidate")
    evaluated_commit = git(repository_root, "rev-parse", "HEAD")

    return ReleaseEvidenceFixture(
        repository_root=repository_root,
        evaluated_commit=evaluated_commit,
        integration_policy=integration_policy,
        live_quality_policy=live_quality_policy,
        integration_report=integration_dir / "report.json",
        live_quality_report=live_dir / "report.json",
        diagnostics=diagnostics,
        artifact_manifest=artifact_manifest_path,
        output_dir=output_dir,
    )
```

- [ ] **Step 2: Write failing strict-model tests**

Create `tests/test_release_evidence_models.py`:

```python
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from scripts.release_evidence.models import (
    BundleIdentity,
    QualityMetrics,
    TransportIdentity,
)


def test_bundle_identity_requires_lowercase_sha256() -> None:
    with pytest.raises(ValidationError):
        BundleIdentity(
            name="graph-rag-c9-0.4.0rc1-quality-evidence.zip",
            bytes=10,
            sha256="A" * 64,
        )


def test_bundle_identity_rejects_unknown_and_coerced_fields() -> None:
    with pytest.raises(ValidationError):
        BundleIdentity.model_validate(
            {
                "name": "graph-rag-c9-0.4.0rc1-quality-evidence.zip",
                "bytes": "10",
                "sha256": "a" * 64,
                "unexpected": True,
            }
        )


def test_quality_metrics_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        QualityMetrics(
            case_count=1,
            pass_rate=1.0,
            deterministic_pass_rate=1.0,
            judge_pass_rate=1.0,
            recall_at_k=math.inf,
            mrr=1.0,
            ndcg_at_k=1.0,
            fallback_rate=0.0,
            retrieval_degradation_rate=0.0,
            p95_latency_ms=1.0,
            estimated_cost_usd=0.0,
        )


def test_transport_identity_requires_full_git_sha_and_prefixed_digest() -> None:
    with pytest.raises(ValidationError):
        TransportIdentity(
            provider="github-actions",
            workflow_run_id=1,
            workflow_head_sha="abc",
            artifact_id=2,
            artifact_name="evidence",
            artifact_digest="f" * 64,
        )
```

- [ ] **Step 3: Run the model tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_models.py -q
```

Expected: FAIL during import because `scripts.release_evidence.models` does not exist.

- [ ] **Step 4: Implement the strict models**

Create `scripts/release_evidence/models.py` with these exact public types and validators:

```python
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self, TypeVar

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
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts or "\\" in value:
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
```

Create `scripts/release_evidence/__init__.py`:

```python
from .models import (
    CAPTURE_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    CaptureReceipt,
    GitHubArtifactMetadata,
    ReleaseEvidenceManifest,
    load_capture_receipt,
    load_release_evidence_manifest,
)

__all__ = [
    "CAPTURE_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "CaptureReceipt",
    "GitHubArtifactMetadata",
    "ReleaseEvidenceManifest",
    "load_capture_receipt",
    "load_release_evidence_manifest",
]
```

- [ ] **Step 5: Run the strict-model tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_models.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the model contract**

```powershell
git add scripts/release_evidence/__init__.py scripts/release_evidence/models.py tests/release_evidence_fixtures.py tests/test_release_evidence_models.py
git commit -m "feat: define release evidence contracts"
```

### Task 2: Capture Safe Sources And Build A Deterministic Evidence ZIP

**Files:**
- Create: `scripts/release_evidence/capture.py`
- Create: `tests/test_release_evidence_capture.py`

**Interfaces:**
- Consumes: `CaptureInputs`, existing gate reports and policies, a diagnostics JSON object, the
  active artifact manifest, a clean repository, and an optional generated timestamp.
- Produces: `CaptureOutputs(receipt_path, bundle_path)` through
  `capture_release_evidence(inputs, generated_at=None)`.

- [ ] **Step 1: Write the passing capture and deterministic-bundle tests**

Create `tests/test_release_evidence_capture.py` with:

```python
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.release_evidence.capture import (
    CaptureInputs,
    ReleaseEvidenceCaptureError,
    capture_release_evidence,
)
from scripts.release_evidence.models import load_capture_receipt
from tests.release_evidence_fixtures import make_release_evidence_fixture, write_json


def capture_inputs(fixture) -> CaptureInputs:
    return CaptureInputs(
        repository_root=fixture.repository_root,
        repository="owner/repository",
        package_version="0.4.0rc1",
        tag="v0.4.0-rc.1",
        evaluated_commit=fixture.evaluated_commit,
        integration_policy_path=fixture.integration_policy,
        live_quality_policy_path=fixture.live_quality_policy,
        integration_report_path=fixture.integration_report,
        live_quality_report_path=fixture.live_quality_report,
        diagnostics_path=fixture.diagnostics,
        artifact_manifest_path=fixture.artifact_manifest,
        judge_model="qwen3.7-plus",
        output_dir=fixture.output_dir,
    )


def test_capture_builds_safe_receipt_and_deterministic_bundle(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    inputs = capture_inputs(fixture)

    first = capture_release_evidence(
        inputs,
        generated_at="2026-07-16T08:00:00+00:00",
    )
    first_bytes = first.bundle_path.read_bytes()
    second = capture_release_evidence(
        inputs,
        generated_at="2026-07-16T08:00:00+00:00",
    )

    receipt = load_capture_receipt(first.receipt_path)
    assert second.bundle_path.read_bytes() == first_bytes
    assert receipt.provenance.evaluated_commit == fixture.evaluated_commit
    assert receipt.quality.metrics.case_count == 1
    assert receipt.quality.metrics.recall_at_k == 1.0
    assert receipt.runtime.profile.path == "profiles/eval_quality.toml"
    assert receipt.runtime.models.judge == "qwen3.7-plus"
    assert receipt.knowledge_base.index_signature == "index-signature"
    assert receipt.bundle.bytes == len(first_bytes)

    with zipfile.ZipFile(first.bundle_path) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert "capture-receipt.json" not in names
        assert "checksums.json" in names
        checksums = json.loads(archive.read("checksums.json"))
        assert "checksums.json" not in checksums
        assert set(checksums) == set(names) - {"checksums.json"}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("passed", False, "live quality report did not pass"),
        ("case_count", 0, "live quality case count must be positive"),
        ("judge_pass_rate", None, "live quality metric judge_pass_rate is invalid"),
    ],
)
def test_capture_rejects_invalid_live_quality_success(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    if field == "passed":
        report["passed"] = value
    else:
        report["metrics"][field] = value
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match=message):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_non_ready_knowledge_artifact(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["stage"] = "stale"
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="knowledge artifact is not ready"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_allows_semantic_secret_text_but_rejects_credentials(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    capture_release_evidence(capture_inputs(fixture))
    report = json.loads(fixture.live_quality_report.read_text(encoding="utf-8"))
    report["cases"] = [{"Authorization": "Bearer actual-token-value"}]
    write_json(fixture.live_quality_report, report)

    with pytest.raises(ReleaseEvidenceCaptureError, match="sensitive release evidence"):
        capture_release_evidence(capture_inputs(fixture))
```

- [ ] **Step 2: Run the capture tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_capture.py -q
```

Expected: FAIL during import because `scripts.release_evidence.capture` does not exist.

- [ ] **Step 3: Implement capture inputs, validation, and deterministic ZIP construction**

Create `scripts/release_evidence/capture.py` with these public definitions:

```python
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

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
    r"^(?:api[_-]?key|api[_-]?token|access[_-]?token|authorization|password|"
    r"bearer[_-]?token|raw[_-]?exception|traceback)$",
    re.IGNORECASE,
)
_BEARER_VALUE_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*\b", re.IGNORECASE)
_AUTH_HEADER_RE = re.compile(r"\bAuthorization\s*:", re.IGNORECASE)
_ABSOLUTE_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\")
_ABSOLUTE_UNIX_PATH_RE = re.compile(
    r"(?:^|\s)/(?:home|Users|var|tmp|opt|workspace)/"
)
_CREDENTIAL_URL_RE = re.compile(r"https?://[^\s/?]+[^\s?]*\?[^\s]+", re.IGNORECASE)
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
    data = path.read_bytes()
    if len(data) > MAX_MEMBER_BYTES:
        raise ReleaseEvidenceCaptureError(f"release evidence member is too large: {path.name}")
    return data


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_bytes(path).decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceCaptureError(
            f"release evidence JSON is invalid: {path.name}"
        ) from exc
    if not isinstance(value, dict):
        raise ReleaseEvidenceCaptureError(
            f"release evidence JSON must be an object: {path.name}"
        )
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
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseEvidenceCaptureError("release evidence Git validation failed")
    return completed.stdout.strip()


def _validate_checkout(inputs: CaptureInputs) -> None:
    head = _git(inputs.repository_root, "rev-parse", "HEAD")
    if head != inputs.evaluated_commit:
        raise ReleaseEvidenceCaptureError("evaluated commit does not match checkout HEAD")
    if _git(inputs.repository_root, "status", "--porcelain"):
        raise ReleaseEvidenceCaptureError("release evidence checkout must be clean")
    parsed_tag = parse_release_tag(inputs.tag)
    if parsed_tag.package_version != inputs.package_version:
        raise ReleaseEvidenceCaptureError("release version and tag do not match")
    pyproject = inputs.repository_root / "pyproject.toml"
    if f'version = "{inputs.package_version}"' not in pyproject.read_text(encoding="utf-8"):
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
        raise ReleaseEvidenceCaptureError(
            "release evidence must use canonical repository policies"
        )


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
            raise ReleaseEvidenceCaptureError(
                f"artifact manifest field is invalid: {field_name}"
            )
    for field_name in string_fields:
        if not isinstance(payload.get(field_name), str):
            raise ReleaseEvidenceCaptureError(
                f"artifact manifest field is invalid: {field_name}"
            )
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
        check_count=_require_int(metrics.get("check_count"), "integration check_count", positive=True),
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
        raise ReleaseEvidenceCaptureError(
            "integration policy and report case counts differ"
        )
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
    resolved_profile = load_profile(
        profile=profile_name,
        profiles_dir=repository_root / "profiles",
    )
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
        if not str(getattr(manifest, field_name) or ""):
            raise ReleaseEvidenceCaptureError(
                f"knowledge artifact field is missing: {field_name}"
            )
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
    if isinstance(value, str):
        if (
            _BEARER_VALUE_RE.search(value)
            or _AUTH_HEADER_RE.search(value)
            or _ABSOLUTE_WINDOWS_PATH_RE.search(value)
            or _ABSOLUTE_UNIX_PATH_RE.search(value)
            or _CREDENTIAL_URL_RE.search(value)
        ):
            raise ReleaseEvidenceCaptureError(f"sensitive release evidence value at {path}")


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
        raise ReleaseEvidenceCaptureError(
            "release evidence projection is invalid"
        ) from exc

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
    manual_review_line_count = sum(
        bool(line.strip()) for line in manual_review_bytes.decode("utf-8").splitlines()
    )
    if manual_review_line_count != quality.manual_review_sample_count:
        raise ReleaseEvidenceCaptureError(
            "manual review sample count does not match JSONL"
        )

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
        "runtime/artifact_manifest.json": _canonical_json(
            knowledge_base.model_dump(mode="json")
        ),
        "policies/integration_gate.json": _read_bytes(inputs.integration_policy_path),
        "policies/live_quality_gate.json": dataset_bytes,
    }
    if sum(len(value) for value in source_entries.values()) > MAX_BUNDLE_SOURCE_BYTES:
        raise ReleaseEvidenceCaptureError("release evidence source bundle is too large")

    for name, data in source_entries.items():
        if name.endswith(".json"):
            _scan_json(json.loads(data.decode("utf-8")))
        elif name.endswith(".jsonl"):
            for line_number, line in enumerate(data.decode("utf-8").splitlines(), start=1):
                if line.strip():
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ReleaseEvidenceCaptureError(
                            f"release evidence JSONL is invalid: {name}:{line_number}"
                        ) from exc
                    _scan_json(payload, f"{name}:{line_number}")
        else:
            text = data.decode("utf-8", errors="replace")
            if (
                _BEARER_VALUE_RE.search(text)
                or _AUTH_HEADER_RE.search(text)
                or _ABSOLUTE_WINDOWS_PATH_RE.search(text)
                or _ABSOLUTE_UNIX_PATH_RE.search(text)
                or _CREDENTIAL_URL_RE.search(text)
            ):
                raise ReleaseEvidenceCaptureError(
                    f"sensitive release evidence value in {name}"
                )

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
        _file_identity(artifact_names[name], name, data)
        for name, data in sorted(entries.items())
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
```

- [ ] **Step 4: Run capture tests and fix only contract mismatches**

Run:

```powershell
python -m pytest tests/test_release_evidence_capture.py -q
```

Expected: PASS. If the `case_count=0` assertion reports “is invalid” instead of “must be positive,”
adjust `_require_int` so the explicit positive check controls the error text.

- [ ] **Step 5: Add focused regression tests for dirty checkouts and profile mismatches**

Append:

```python
def test_capture_rejects_dirty_checkout(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    (fixture.repository_root / "dirty.txt").write_text("dirty", encoding="utf-8")

    with pytest.raises(ReleaseEvidenceCaptureError, match="checkout must be clean"):
        capture_release_evidence(capture_inputs(fixture))


def test_capture_rejects_profile_hash_mismatch(tmp_path: Path) -> None:
    fixture = make_release_evidence_fixture(tmp_path)
    manifest = json.loads(fixture.artifact_manifest.read_text(encoding="utf-8"))
    manifest["build_metadata"]["config_profile"]["hash"] = "0" * 64
    write_json(fixture.artifact_manifest, manifest)

    with pytest.raises(ReleaseEvidenceCaptureError, match="profile hash"):
        capture_release_evidence(capture_inputs(fixture))
```

Run:

```powershell
python -m pytest tests/test_release_evidence_capture.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit capture and deterministic bundling**

```powershell
git add scripts/release_evidence/capture.py tests/test_release_evidence_capture.py
git commit -m "feat: capture release quality evidence"
```

### Task 3: Finalize The Git Manifest With Actions Transport Metadata

**Files:**
- Create: `scripts/release_evidence/finalize.py`
- Create: `tests/test_release_evidence_finalize.py`

**Interfaces:**
- Consumes: `CaptureReceipt`, `TransportIdentity`, and an output path.
- Produces: `finalize_release_evidence(receipt_path, transport, output_path) ->
  ReleaseEvidenceManifest`.

- [ ] **Step 1: Write failing finalization tests**

Create `tests/test_release_evidence_finalize.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.release_evidence.capture import CaptureInputs, capture_release_evidence
from scripts.release_evidence.finalize import (
    ReleaseEvidenceFinalizeError,
    finalize_release_evidence,
)
from scripts.release_evidence.models import (
    TransportIdentity,
    load_capture_receipt,
    load_release_evidence_manifest,
)
from tests.release_evidence_fixtures import make_release_evidence_fixture


def captured(tmp_path: Path):
    fixture = make_release_evidence_fixture(tmp_path)
    outputs = capture_release_evidence(
        CaptureInputs(
            repository_root=fixture.repository_root,
            repository="owner/repository",
            package_version="0.4.0rc1",
            tag="v0.4.0-rc.1",
            evaluated_commit=fixture.evaluated_commit,
            integration_policy_path=fixture.integration_policy,
            live_quality_policy_path=fixture.live_quality_policy,
            integration_report_path=fixture.integration_report,
            live_quality_report_path=fixture.live_quality_report,
            diagnostics_path=fixture.diagnostics,
            artifact_manifest_path=fixture.artifact_manifest,
            judge_model="qwen3.7-plus",
            output_dir=fixture.output_dir,
        ),
        generated_at="2026-07-16T08:00:00+00:00",
    )
    return fixture, outputs


def test_finalize_preserves_capture_core_and_adds_transport(tmp_path: Path) -> None:
    fixture, outputs = captured(tmp_path)
    output_path = tmp_path / "evidence-manifest.json"
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha=fixture.evaluated_commit,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )

    finalize_release_evidence(outputs.receipt_path, transport, output_path)

    receipt = load_capture_receipt(outputs.receipt_path)
    manifest = load_release_evidence_manifest(output_path)
    assert manifest.transport == transport
    assert manifest.release == receipt.release
    assert manifest.bundle == receipt.bundle
    assert manifest.artifacts == receipt.artifacts


def test_finalize_rejects_workflow_head_mismatch(tmp_path: Path) -> None:
    _, outputs = captured(tmp_path)
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha="b" * 40,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )

    with pytest.raises(ReleaseEvidenceFinalizeError, match="workflow head"):
        finalize_release_evidence(outputs.receipt_path, transport, tmp_path / "manifest.json")
```

- [ ] **Step 2: Run finalization tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_finalize.py -q
```

Expected: FAIL during import because `scripts.release_evidence.finalize` does not exist.

- [ ] **Step 3: Implement finalization**

Create `scripts/release_evidence/finalize.py`:

```python
from __future__ import annotations

from pathlib import Path

from .models import (
    ReleaseEvidenceManifest,
    TransportIdentity,
    load_capture_receipt,
    write_evidence_model,
)


class ReleaseEvidenceFinalizeError(RuntimeError):
    pass


def finalize_release_evidence(
    receipt_path: str | Path,
    transport: TransportIdentity,
    output_path: str | Path,
) -> ReleaseEvidenceManifest:
    receipt = load_capture_receipt(receipt_path)
    if transport.workflow_head_sha != receipt.provenance.evaluated_commit:
        raise ReleaseEvidenceFinalizeError(
            "workflow head does not match evaluated commit"
        )
    expected_artifact_name = (
        f"graph-rag-c9-{receipt.release.package_version}-quality-evidence"
    )
    if transport.artifact_name != expected_artifact_name:
        raise ReleaseEvidenceFinalizeError(
            "workflow artifact name does not match release"
        )
    manifest = ReleaseEvidenceManifest(
        **receipt.model_dump(exclude={"schema_version"}),
        transport=transport,
    )
    write_evidence_model(manifest, output_path)
    return manifest
```

- [ ] **Step 4: Run finalization tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_finalize.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit transport binding**

```powershell
git add scripts/release_evidence/finalize.py tests/test_release_evidence_finalize.py
git commit -m "feat: finalize release evidence manifests"
```

### Task 4: Verify Git Provenance, GitHub Artifact Metadata, And Bundle Contents

**Files:**
- Create: `scripts/release_evidence/verifier.py`
- Create: `tests/test_release_evidence_verifier.py`

**Interfaces:**
- Consumes: `VerifyInputs(repository_root, manifest_path, release_commit, tag, bundle_path,
  artifact_metadata_path)`.
- Produces: `verify_release_evidence(inputs) -> ReleaseEvidenceManifest` and
  `release_manifest_path(repository_root, package_version) -> Path`.

- [ ] **Step 1: Write the passing verification and Git-change rejection tests**

Create `tests/test_release_evidence_verifier.py` using the Task 3 `captured()` helper pattern:

```python
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.release_evidence.capture import CaptureInputs, capture_release_evidence
from scripts.release_evidence.finalize import finalize_release_evidence
from scripts.release_evidence.models import TransportIdentity
from scripts.release_evidence.verifier import (
    ReleaseEvidenceVerificationError,
    VerifyInputs,
    release_manifest_path,
    verify_release_evidence,
)
from tests.release_evidence_fixtures import git, make_release_evidence_fixture, write_json


def finalized_release(tmp_path: Path):
    fixture = make_release_evidence_fixture(tmp_path)
    capture = capture_release_evidence(
        CaptureInputs(
            repository_root=fixture.repository_root,
            repository="owner/repository",
            package_version="0.4.0rc1",
            tag="v0.4.0-rc.1",
            evaluated_commit=fixture.evaluated_commit,
            integration_policy_path=fixture.integration_policy,
            live_quality_policy_path=fixture.live_quality_policy,
            integration_report_path=fixture.integration_report,
            live_quality_report_path=fixture.live_quality_report,
            diagnostics_path=fixture.diagnostics,
            artifact_manifest_path=fixture.artifact_manifest,
            judge_model="qwen3.7-plus",
            output_dir=fixture.output_dir,
        ),
        generated_at="2026-07-16T08:00:00+00:00",
    )
    transport = TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha=fixture.evaluated_commit,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "a" * 64,
    )
    manifest_path = release_manifest_path(fixture.repository_root, "0.4.0rc1")
    finalize_release_evidence(capture.receipt_path, transport, manifest_path)
    git(fixture.repository_root, "add", manifest_path.relative_to(fixture.repository_root).as_posix())
    git(fixture.repository_root, "commit", "-m", "release: add quality evidence")
    release_commit = git(fixture.repository_root, "rev-parse", "HEAD")
    metadata_path = write_json(
        tmp_path / "artifact-metadata.json",
        {
            "id": 456,
            "name": "graph-rag-c9-0.4.0rc1-quality-evidence",
            "size_in_bytes": capture.bundle_path.stat().st_size,
            "expired": False,
            "digest": "sha256:" + "a" * 64,
            "workflow_run": {
                "id": 123,
                "head_sha": fixture.evaluated_commit,
            },
        },
    )
    return fixture, capture, manifest_path, release_commit, metadata_path


def test_verify_accepts_evidence_only_release_commit(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)

    manifest = verify_release_evidence(
        VerifyInputs(
            repository_root=fixture.repository_root,
            manifest_path=manifest_path,
            release_commit=release_commit,
            tag="v0.4.0-rc.1",
            bundle_path=capture.bundle_path,
            artifact_metadata_path=metadata_path,
        )
    )

    assert manifest.provenance.evaluated_commit == fixture.evaluated_commit


def test_verify_rejects_source_change_after_evaluation(tmp_path: Path) -> None:
    fixture, capture, manifest_path, _, metadata_path = finalized_release(tmp_path)
    (fixture.repository_root / "profiles" / "eval_quality.toml").write_text(
        "[retrieval]\ntop_k = 7\n",
        encoding="utf-8",
    )
    git(fixture.repository_root, "add", "profiles/eval_quality.toml")
    git(fixture.repository_root, "commit", "-m", "change: modify evaluated profile")
    release_commit = git(fixture.repository_root, "rev-parse", "HEAD")

    with pytest.raises(ReleaseEvidenceVerificationError, match="unexpected files"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=capture.bundle_path,
                artifact_metadata_path=metadata_path,
            )
        )


def test_verify_rejects_expired_artifact(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["expired"] = True
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="expired"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=capture.bundle_path,
                artifact_metadata_path=metadata_path,
            )
        )


def test_verify_rejects_extra_or_modified_bundle_member(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    tampered = tmp_path / "tampered.zip"
    shutil.copy2(capture.bundle_path, tampered)
    with zipfile.ZipFile(tampered, "a") as archive:
        archive.writestr("../escape.txt", "tampered")

    with pytest.raises(ReleaseEvidenceVerificationError, match="bundle"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=tampered,
                artifact_metadata_path=metadata_path,
            )
        )
```

- [ ] **Step 2: Run verifier tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_verifier.py -q
```

Expected: FAIL during import because `scripts.release_evidence.verifier` does not exist.

- [ ] **Step 3: Implement verifier functions**

Create `scripts/release_evidence/verifier.py` with:

```python
from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from rag_modules.configuration.profiles import load_profile
from scripts.integration_gate.models import IntegrationGatePolicy
from scripts.live_quality_gate.models import LiveQualityGatePolicy
from scripts.validate_release_tag import parse_release_tag

from .models import (
    GitHubArtifactMetadata,
    KnowledgeBaseIdentity,
    ReleaseEvidenceManifest,
    RuntimeIdentity,
    load_release_evidence_manifest,
)


class ReleaseEvidenceVerificationError(RuntimeError):
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


def _git(repository_root: Path, *args: str, allowed_returncodes: set[int] | None = None):
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    allowed = allowed_returncodes or {0}
    if completed.returncode not in allowed:
        raise ReleaseEvidenceVerificationError("release evidence Git verification failed")
    return completed


def _verify_git(inputs: VerifyInputs, manifest: ReleaseEvidenceManifest) -> None:
    _git(inputs.repository_root, "cat-file", "-e", f"{inputs.release_commit}^{{commit}}")
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
    expected_relative = (
        Path("quality-evidence")
        / "releases"
        / manifest.release.package_version
        / "evidence-manifest.json"
    ).as_posix()
    actual_relative = inputs.manifest_path.resolve().relative_to(
        inputs.repository_root.resolve()
    ).as_posix()
    if actual_relative != expected_relative:
        raise ReleaseEvidenceVerificationError("release manifest path is invalid")
    changed = {
        line
        for line in _git(
            inputs.repository_root,
            "diff",
            "--name-only",
            f"{manifest.provenance.evaluated_commit}..{inputs.release_commit}",
        ).stdout.splitlines()
        if line
    }
    if changed != {expected_relative}:
        raise ReleaseEvidenceVerificationError(
            f"unexpected files changed after evaluation: {sorted(changed)}"
        )


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
    pyproject = tomllib.loads(
        (inputs.repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    if pyproject["project"]["version"] != manifest.release.package_version:
        raise ReleaseEvidenceVerificationError(
            "manifest package version does not match pyproject"
        )


def _verify_transport(
    manifest: ReleaseEvidenceManifest,
    metadata_path: Path,
) -> None:
    metadata = GitHubArtifactMetadata.model_validate_json(
        metadata_path.read_text(encoding="utf-8")
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
        raise ReleaseEvidenceVerificationError(
            "transport head does not match evaluated commit"
        )


def _verify_bundle(
    manifest: ReleaseEvidenceManifest,
    bundle_path: Path,
) -> dict[str, bytes]:
    bundle_bytes = bundle_path.read_bytes()
    if len(bundle_bytes) != manifest.bundle.bytes:
        raise ReleaseEvidenceVerificationError("bundle byte count does not match manifest")
    if _sha256(bundle_bytes) != manifest.bundle.sha256:
        raise ReleaseEvidenceVerificationError("bundle sha256 does not match manifest")
    if bundle_path.name != manifest.bundle.name:
        raise ReleaseEvidenceVerificationError("bundle name does not match manifest")

    expected = {item.path: item for item in manifest.artifacts}
    entries: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ReleaseEvidenceVerificationError("bundle contains duplicate members")
            for name in names:
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts or "\\" in name:
                    raise ReleaseEvidenceVerificationError("bundle contains unsafe member path")
                entries[name] = archive.read(name)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReleaseEvidenceVerificationError("bundle is unreadable") from exc
    if set(entries) != set(expected):
        raise ReleaseEvidenceVerificationError("bundle members do not match manifest")
    for name, data in entries.items():
        identity = expected[name]
        if len(data) != identity.bytes or _sha256(data) != identity.sha256:
            raise ReleaseEvidenceVerificationError(
                f"bundle member does not match manifest: {name}"
            )
    checksums = json.loads(entries["checksums.json"].decode("utf-8"))
    expected_checksums = {
        name: {"bytes": len(data), "sha256": _sha256(data)}
        for name, data in entries.items()
        if name != "checksums.json"
    }
    if checksums != expected_checksums:
        raise ReleaseEvidenceVerificationError("bundle checksums are inconsistent")
    return entries


def _verify_semantics(
    manifest: ReleaseEvidenceManifest,
    entries: dict[str, bytes],
    repository_root: Path,
) -> None:
    live_report = json.loads(entries["live_quality_gate/report.json"])
    integration_report = json.loads(entries["integration_gate/report.json"])
    live_policy_payload = json.loads(entries["policies/live_quality_gate.json"])
    integration_policy_payload = json.loads(entries["policies/integration_gate.json"])
    live_policy = LiveQualityGatePolicy.model_validate(live_policy_payload)
    integration_policy = IntegrationGatePolicy.model_validate(integration_policy_payload)
    if live_report.get("passed") is not True or integration_report.get("passed") is not True:
        raise ReleaseEvidenceVerificationError("bundle contains a failed gate report")
    quality_metrics = live_report.get("metrics")
    integration_metrics = integration_report.get("metrics")
    if not isinstance(quality_metrics, dict) or not isinstance(integration_metrics, dict):
        raise ReleaseEvidenceVerificationError("bundle report metrics are invalid")
    for name, expected in manifest.quality.metrics.model_dump().items():
        if quality_metrics.get(name) != expected:
            raise ReleaseEvidenceVerificationError(
                f"live quality metric does not match manifest: {name}"
            )
    for name, expected in manifest.integration.metrics.model_dump().items():
        if integration_metrics.get(name) != expected:
            raise ReleaseEvidenceVerificationError(
                f"integration metric does not match manifest: {name}"
            )
    if live_report.get("schema_version") != manifest.quality.report_schema_version:
        raise ReleaseEvidenceVerificationError(
            "live quality schema version does not match manifest"
        )
    if live_report.get("generated_at") != manifest.quality.generated_at:
        raise ReleaseEvidenceVerificationError(
            "live quality timestamp does not match manifest"
        )
    if (
        live_report.get("manual_review_sample_count")
        != manifest.quality.manual_review_sample_count
    ):
        raise ReleaseEvidenceVerificationError(
            "manual review sample count does not match manifest"
        )
    sample_count = sum(
        bool(line.strip())
        for line in entries[
            "live_quality_gate/manual_review_sample.jsonl"
        ].decode("utf-8").splitlines()
    )
    if sample_count != manifest.quality.manual_review_sample_count:
        raise ReleaseEvidenceVerificationError(
            "manual review JSONL count does not match manifest"
        )
    if integration_report.get("schema_version") != manifest.integration.report_schema_version:
        raise ReleaseEvidenceVerificationError(
            "integration schema version does not match manifest"
        )
    if integration_report.get("generated_at") != manifest.integration.generated_at:
        raise ReleaseEvidenceVerificationError(
            "integration timestamp does not match manifest"
        )
    if len(integration_policy.live_cases) != manifest.integration.metrics.case_count:
        raise ReleaseEvidenceVerificationError(
            "integration policy case count does not match manifest"
        )
    if len(live_policy.cases) != manifest.dataset.case_count:
        raise ReleaseEvidenceVerificationError("dataset case count does not match manifest")
    if live_policy.schema_version != manifest.dataset.schema_version:
        raise ReleaseEvidenceVerificationError(
            "dataset schema version does not match manifest"
        )
    if _sha256(entries["policies/live_quality_gate.json"]) != manifest.dataset.sha256:
        raise ReleaseEvidenceVerificationError("dataset sha256 does not match manifest")
    runtime = RuntimeIdentity.model_validate_json(entries["runtime/diagnostics.json"])
    knowledge = KnowledgeBaseIdentity.model_validate_json(
        entries["runtime/artifact_manifest.json"]
    )
    if runtime != manifest.runtime:
        raise ReleaseEvidenceVerificationError("runtime identity does not match manifest")
    if knowledge != manifest.knowledge_base:
        raise ReleaseEvidenceVerificationError(
            "knowledge-base identity does not match manifest"
        )
    profile_name = manifest.runtime.profile.name
    profile_path = (
        repository_root
        / "profiles"
        / ("base.toml" if profile_name == "base" else f"{profile_name}.toml")
    )
    if profile_path.relative_to(repository_root).as_posix() != manifest.runtime.profile.path:
        raise ReleaseEvidenceVerificationError("profile path does not match manifest")
    resolved_profile = load_profile(
        profile=profile_name,
        profiles_dir=repository_root / "profiles",
    )
    if resolved_profile.profile_hash != manifest.runtime.profile.resolved_sha256:
        raise ReleaseEvidenceVerificationError(
            "resolved profile hash does not match manifest"
        )


def verify_release_evidence(inputs: VerifyInputs) -> ReleaseEvidenceManifest:
    try:
        manifest = load_release_evidence_manifest(inputs.manifest_path)
        _verify_git(inputs, manifest)
        _verify_release_identity(inputs, manifest)
        _verify_transport(manifest, inputs.artifact_metadata_path)
        entries = _verify_bundle(manifest, inputs.bundle_path)
        _verify_semantics(manifest, entries, inputs.repository_root)
        return manifest
    except ReleaseEvidenceVerificationError:
        raise
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise ReleaseEvidenceVerificationError(
            "release evidence verification input is invalid"
        ) from exc
```

- [ ] **Step 4: Run verifier tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_verifier.py -q
```

Expected: PASS.

- [ ] **Step 5: Add exact version, digest, and member-mutation cases**

Append tests that mutate one value at a time:

```python
def test_verify_rejects_artifact_digest_mismatch(tmp_path: Path) -> None:
    fixture, capture, manifest_path, release_commit, metadata_path = finalized_release(tmp_path)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["digest"] = "sha256:" + "b" * 64
    write_json(metadata_path, metadata)

    with pytest.raises(ReleaseEvidenceVerificationError, match="artifact digest"):
        verify_release_evidence(
            VerifyInputs(
                repository_root=fixture.repository_root,
                manifest_path=manifest_path,
                release_commit=release_commit,
                tag="v0.4.0-rc.1",
                bundle_path=capture.bundle_path,
                artifact_metadata_path=metadata_path,
            )
        )


def test_release_manifest_path_ignores_historical_failed_reports(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    historical = root / "quality-evidence/live_quality_gate/20260708-203513/report.json"
    historical.parent.mkdir(parents=True)
    historical.write_text('{"passed":false,"metrics":{"case_count":0}}\n', encoding="utf-8")

    assert release_manifest_path(root, "0.4.0rc1") == (
        root / "quality-evidence/releases/0.4.0rc1/evidence-manifest.json"
    )
```

Run:

```powershell
python -m pytest tests/test_release_evidence_verifier.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit verification**

```powershell
git add scripts/release_evidence/verifier.py tests/test_release_evidence_verifier.py
git commit -m "feat: verify release evidence provenance"
```

### Task 5: Add The CLI And Console Entrypoint

**Files:**
- Create: `scripts/release_evidence/cli.py`
- Create: `scripts/release_evidence/__main__.py`
- Create: `tests/test_release_evidence_cli.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_entrypoints.py`

**Interfaces:**
- Consumes: CLI arguments and `LIVE_QUALITY_API_TOKEN` only when `capture` uses
  `--diagnostics-url`.
- Produces: `graph-rag-release-evidence capture|finalize|verify`, stable exit code `0` on success
  and `2` on configuration, input, transport, or verification failure.

- [ ] **Step 1: Write failing CLI and entrypoint tests**

Create `tests/test_release_evidence_cli.py`:

```python
from __future__ import annotations

import json
from unittest.mock import patch

from scripts.release_evidence import cli


def test_finalize_cli_writes_safe_json(capsys) -> None:
    with patch.object(
        cli,
        "finalize_release_evidence",
        return_value=object(),
    ) as finalize:
        exit_code = cli.main(
            [
                "finalize",
                "--capture-receipt",
                "capture.json",
                "--workflow-run-id",
                "123",
                "--workflow-head-sha",
                "a" * 40,
                "--artifact-id",
                "456",
                "--artifact-name",
                "graph-rag-c9-0.4.0rc1-quality-evidence",
                "--artifact-digest",
                "b" * 64,
                "--output",
                "manifest.json",
                "--json",
            ]
        )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["output"] == "manifest.json"
    assert finalize.call_args.args[1].artifact_digest == "sha256:" + "b" * 64


def test_cli_redacts_internal_exception_text(capsys) -> None:
    with patch.object(
        cli,
        "verify_release_evidence",
        side_effect=RuntimeError("Bearer actual-token-value"),
    ):
        exit_code = cli.main(
            [
                "verify",
                "--repository-root",
                ".",
                "--manifest",
                "manifest.json",
                "--release-commit",
                "a" * 40,
                "--tag",
                "v0.4.0-rc.1",
                "--bundle",
                "bundle.zip",
                "--artifact-metadata",
                "artifact.json",
            ]
        )

    assert exit_code == 2
    assert "actual-token-value" not in capsys.readouterr().err
```

Append to `tests/test_entrypoints.py`:

```python
    def test_release_evidence_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-release-evidence"],
            "scripts.release_evidence.cli:main",
        )

    def test_release_evidence_module_help_exposes_subcommands(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.release_evidence", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("capture", completed.stdout)
        self.assertIn("finalize", completed.stdout)
        self.assertIn("verify", completed.stdout)
```

- [ ] **Step 2: Run CLI and entrypoint tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_cli.py tests/test_entrypoints.py -q
```

Expected: FAIL because the CLI, module entrypoint, and console registration do not exist.

- [ ] **Step 3: Implement CLI parsing and diagnostics fetching**

Create `scripts/release_evidence/cli.py` with:

```python
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import requests

from .capture import CaptureInputs, capture_release_evidence
from .finalize import finalize_release_evidence
from .models import TransportIdentity
from .verifier import VerifyInputs, verify_release_evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and verify release quality evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--repository-root", type=Path, required=True)
    capture.add_argument("--repository", required=True)
    capture.add_argument("--package-version", required=True)
    capture.add_argument("--tag", required=True)
    capture.add_argument("--evaluated-commit", required=True)
    capture.add_argument("--integration-policy", type=Path, required=True)
    capture.add_argument("--live-quality-policy", type=Path, required=True)
    capture.add_argument("--integration-report", type=Path, required=True)
    capture.add_argument("--live-quality-report", type=Path, required=True)
    diagnostics = capture.add_mutually_exclusive_group(required=True)
    diagnostics.add_argument("--diagnostics-json", type=Path)
    diagnostics.add_argument("--diagnostics-url")
    capture.add_argument("--artifact-manifest", type=Path, required=True)
    capture.add_argument("--judge-model", required=True)
    capture.add_argument("--output-dir", type=Path, required=True)
    capture.add_argument("--json", action="store_true", dest="emit_json")

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--capture-receipt", type=Path, required=True)
    finalize.add_argument("--workflow-run-id", type=int, required=True)
    finalize.add_argument("--workflow-head-sha", required=True)
    finalize.add_argument("--artifact-id", type=int, required=True)
    finalize.add_argument("--artifact-name", required=True)
    finalize.add_argument("--artifact-digest", required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--json", action="store_true", dest="emit_json")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--repository-root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--release-commit", required=True)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--artifact-metadata", type=Path, required=True)
    verify.add_argument("--json", action="store_true", dest="emit_json")
    return parser


def _fetch_diagnostics(url: str) -> Path:
    headers: dict[str, str] = {}
    token = os.environ.get("LIVE_QUALITY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("diagnostics response must be an object")
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    )
    with handle:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return Path(handle.name)


def _emit(payload: dict[str, object], emit_json: bool) -> None:
    if emit_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        for name, value in payload.items():
            print(f"{name}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    temporary_diagnostics: Path | None = None
    try:
        if args.command == "capture":
            diagnostics_path = args.diagnostics_json
            if diagnostics_path is None:
                temporary_diagnostics = _fetch_diagnostics(args.diagnostics_url)
                diagnostics_path = temporary_diagnostics
            outputs = capture_release_evidence(
                CaptureInputs(
                    repository_root=args.repository_root,
                    repository=args.repository,
                    package_version=args.package_version,
                    tag=args.tag,
                    evaluated_commit=args.evaluated_commit,
                    integration_policy_path=args.integration_policy,
                    live_quality_policy_path=args.live_quality_policy,
                    integration_report_path=args.integration_report,
                    live_quality_report_path=args.live_quality_report,
                    diagnostics_path=diagnostics_path,
                    artifact_manifest_path=args.artifact_manifest,
                    judge_model=args.judge_model,
                    output_dir=args.output_dir,
                )
            )
            _emit(
                {
                    "capture_receipt": str(outputs.receipt_path),
                    "bundle": str(outputs.bundle_path),
                },
                args.emit_json,
            )
            return 0
        if args.command == "finalize":
            artifact_digest = args.artifact_digest
            if not artifact_digest.startswith("sha256:"):
                artifact_digest = f"sha256:{artifact_digest}"
            finalize_release_evidence(
                args.capture_receipt,
                TransportIdentity(
                    provider="github-actions",
                    workflow_run_id=args.workflow_run_id,
                    workflow_head_sha=args.workflow_head_sha,
                    artifact_id=args.artifact_id,
                    artifact_name=args.artifact_name,
                    artifact_digest=artifact_digest,
                ),
                args.output,
            )
            _emit({"output": str(args.output)}, args.emit_json)
            return 0
        manifest = verify_release_evidence(
            VerifyInputs(
                repository_root=args.repository_root,
                manifest_path=args.manifest,
                release_commit=args.release_commit,
                tag=args.tag,
                bundle_path=args.bundle,
                artifact_metadata_path=args.artifact_metadata,
            )
        )
        _emit(
            {
                "verified": True,
                "package_version": manifest.release.package_version,
                "evaluated_commit": manifest.provenance.evaluated_commit,
            },
            args.emit_json,
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "passed": False,
                    "failure_type": "gate-error",
                    "code": "RELEASE_EVIDENCE_OPERATION_FAILED",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if temporary_diagnostics is not None:
            temporary_diagnostics.unlink(missing_ok=True)
```

Create `scripts/release_evidence/__main__.py`:

```python
from .cli import main

raise SystemExit(main())
```

Add under `[project.scripts]` in `pyproject.toml`:

```toml
graph-rag-release-evidence = "scripts.release_evidence.cli:main"
```

- [ ] **Step 4: Run CLI and entrypoint tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_cli.py tests/test_entrypoints.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit CLI and registration**

```powershell
git add scripts/release_evidence/cli.py scripts/release_evidence/__main__.py pyproject.toml tests/test_release_evidence_cli.py tests/test_entrypoints.py
git commit -m "feat: add release evidence CLI"
```

### Task 6: Add The Manual Capture And Pre-tag Verification Workflow

**Files:**
- Create: `.github/workflows/release-evidence.yml`
- Create: `tests/test_release_evidence_workflows.py`
- Modify: `tests/test_enterprise_governance.py`

**Interfaces:**
- Consumes: manual inputs `operation`, `evaluated_commit`, `release_commit`, `package_version`,
  `tag`, and `runner`; environment `release-quality`; existing gate secrets; environment variable
  `RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH`.
- Produces: a complete evidence artifact, a finalized manifest artifact, or a successful pre-tag
  verification run.

- [ ] **Step 1: Write failing workflow contract tests**

Create `tests/test_release_evidence_workflows.py`:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def workflow_text() -> str:
    return (ROOT / ".github/workflows/release-evidence.yml").read_text(encoding="utf-8")


def test_capture_workflow_runs_gates_before_upload_and_finalize() -> None:
    workflow = workflow_text()
    integration = workflow.index("python -m scripts.integration_gate")
    live_quality = workflow.index("python -m scripts.live_quality_gate")
    capture = workflow.index("python -m scripts.release_evidence capture")
    upload = workflow.index("id: evidence-upload")
    finalize = workflow.index("python -m scripts.release_evidence finalize")

    assert integration < live_quality < capture < upload < finalize
    assert "retention-days: 90" in workflow
    assert "LIVE_QUALITY_JUDGE_MODEL" in workflow
    assert "RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH" in workflow


def test_verify_workflow_queries_and_downloads_selected_artifact() -> None:
    workflow = workflow_text()

    assert "gh api" in workflow
    assert "gh run download" in workflow
    assert "python -m scripts.release_evidence verify" in workflow
    assert "actions: read" in workflow
```

Append to `tests/test_enterprise_governance.py`:

```python
def test_release_evidence_workflow_is_manual_and_environment_scoped() -> None:
    workflow = _read(".github/workflows/release-evidence.yml")

    assert "workflow_dispatch:" in workflow
    assert "environment: release-quality" in workflow
    assert "operation:" in workflow
    assert "capture" in workflow
    assert "verify" in workflow
    assert "actions/upload-artifact@v7" in workflow
```

In `test_workflows_use_node24_compatible_action_majors`, replace the existing
`workflows = ci + release` assignment with the following block:

```python
    evidence = _read(".github/workflows/release-evidence.yml")
    workflows = ci + release + evidence

    assert evidence.count("actions/checkout@v7") == 2
    assert evidence.count("actions/setup-python@v6") == 2
    assert evidence.count("actions/upload-artifact@v7") == 2
```

Keep the existing retired-action loop against the expanded `workflows` string.

- [ ] **Step 2: Run workflow tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py -q
```

Expected: FAIL because `.github/workflows/release-evidence.yml` does not exist.

- [ ] **Step 3: Create the manual workflow**

Create `.github/workflows/release-evidence.yml` with two jobs:

```yaml
name: Release Quality Evidence

on:
  workflow_dispatch:
    inputs:
      operation:
        description: Capture evidence or verify a committed manifest
        required: true
        type: choice
        options:
          - capture
          - verify
      evaluated_commit:
        description: Exact commit evaluated by the live gates
        required: true
        type: string
      release_commit:
        description: Commit containing the selected manifest; required for verify
        required: false
        type: string
      package_version:
        description: PEP 440 package version
        required: true
        type: string
      tag:
        description: Planned protected release tag
        required: true
        type: string
      runner:
        description: Runner that can reach the prepared target environment
        required: true
        type: choice
        default: self-hosted
        options:
          - self-hosted
          - ubuntu-latest

permissions:
  contents: read
  actions: read

jobs:
  capture:
    if: inputs.operation == 'capture'
    runs-on: ${{ inputs.runner }}
    timeout-minutes: 180
    environment: release-quality
    env:
      INTEGRATION_GATE_API_URL: ${{ secrets.INTEGRATION_GATE_API_URL }}
      INTEGRATION_GATE_API_TOKEN: ${{ secrets.INTEGRATION_GATE_API_TOKEN }}
      NEO4J_URI: ${{ secrets.NEO4J_URI }}
      NEO4J_USER: ${{ secrets.NEO4J_USER }}
      NEO4J_PASSWORD: ${{ secrets.NEO4J_PASSWORD }}
      NEO4J_DATABASE: ${{ vars.NEO4J_DATABASE }}
      MILVUS_HOST: ${{ vars.MILVUS_HOST }}
      MILVUS_PORT: ${{ vars.MILVUS_PORT }}
      MILVUS_COLLECTION_NAME: ${{ vars.MILVUS_COLLECTION_NAME }}
      LIVE_QUALITY_API_URL: ${{ secrets.LIVE_QUALITY_API_URL }}
      LIVE_QUALITY_API_TOKEN: ${{ secrets.LIVE_QUALITY_API_TOKEN }}
      LIVE_QUALITY_JUDGE_API_URL: ${{ secrets.LIVE_QUALITY_JUDGE_API_URL }}
      LIVE_QUALITY_JUDGE_API_KEY: ${{ secrets.LIVE_QUALITY_JUDGE_API_KEY }}
      LIVE_QUALITY_JUDGE_MODEL: ${{ vars.LIVE_QUALITY_JUDGE_MODEL }}
      LIVE_QUALITY_JUDGE_TIMEOUT_SECONDS: ${{ vars.LIVE_QUALITY_JUDGE_TIMEOUT_SECONDS || '45' }}
      LIVE_QUALITY_JUDGE_ENABLE_THINKING: ${{ vars.LIVE_QUALITY_JUDGE_ENABLE_THINKING || 'false' }}
      RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH: ${{ vars.RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH }}

    steps:
      - name: Check out evaluated commit
        uses: actions/checkout@v7
        with:
          ref: ${{ inputs.evaluated_commit }}
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install dependencies
        run: python -m pip install -r requirements-dev.txt

      - name: Verify evaluated checkout
        shell: bash
        run: |
          test "$(git rev-parse HEAD)" = "${{ inputs.evaluated_commit }}"
          test -z "$(git status --porcelain)"

      - name: Run real-dependency integration gate
        run: >
          python -m scripts.integration_gate
          --output-dir eval/reports/integration_gate

      - name: Run live quality gate
        run: >
          python -m scripts.live_quality_gate
          --output-dir eval/reports/live_quality_gate

      - name: Capture complete release evidence
        run: >
          python -m scripts.release_evidence capture
          --repository-root .
          --repository "${{ github.repository }}"
          --package-version "${{ inputs.package_version }}"
          --tag "${{ inputs.tag }}"
          --evaluated-commit "${{ inputs.evaluated_commit }}"
          --integration-policy eval/integration_gate.json
          --live-quality-policy eval/live_quality_gate.json
          --integration-report eval/reports/integration_gate/report.json
          --live-quality-report eval/reports/live_quality_gate/report.json
          --diagnostics-url "${LIVE_QUALITY_API_URL%/}/v1/diagnostics"
          --artifact-manifest "${RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH}"
          --judge-model "${LIVE_QUALITY_JUDGE_MODEL}"
          --output-dir "eval/reports/release_evidence/${{ inputs.package_version }}"
          --json

      - name: Upload complete evidence bundle
        id: evidence-upload
        uses: actions/upload-artifact@v7
        with:
          name: graph-rag-c9-${{ inputs.package_version }}-quality-evidence
          path: eval/reports/release_evidence/${{ inputs.package_version }}/graph-rag-c9-${{ inputs.package_version }}-quality-evidence.zip
          if-no-files-found: error
          retention-days: 90

      - name: Finalize compact evidence manifest
        run: >
          python -m scripts.release_evidence finalize
          --capture-receipt "eval/reports/release_evidence/${{ inputs.package_version }}/capture-receipt.json"
          --workflow-run-id "${GITHUB_RUN_ID}"
          --workflow-head-sha "${{ inputs.evaluated_commit }}"
          --artifact-id "${{ steps.evidence-upload.outputs.artifact-id }}"
          --artifact-name "graph-rag-c9-${{ inputs.package_version }}-quality-evidence"
          --artifact-digest "${{ steps.evidence-upload.outputs.artifact-digest }}"
          --output "eval/reports/release_evidence/${{ inputs.package_version }}/evidence-manifest.json"
          --json

      - name: Upload compact manifest for release pull request
        uses: actions/upload-artifact@v7
        with:
          name: graph-rag-c9-${{ inputs.package_version }}-quality-evidence-manifest
          path: eval/reports/release_evidence/${{ inputs.package_version }}/evidence-manifest.json
          if-no-files-found: error
          retention-days: 90

  verify:
    if: inputs.operation == 'verify'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      GH_TOKEN: ${{ github.token }}

    steps:
      - name: Check out release commit
        uses: actions/checkout@v7
        with:
          ref: ${{ inputs.release_commit }}
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.11"
          cache: pip
          cache-dependency-path: requirements-dev.txt

      - name: Install dependencies
        run: python -m pip install -r requirements-dev.txt

      - name: Resolve selected artifact identity
        id: evidence
        shell: bash
        run: |
          manifest="quality-evidence/releases/${{ inputs.package_version }}/evidence-manifest.json"
          echo "manifest=${manifest}" >> "${GITHUB_OUTPUT}"
          echo "artifact_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["artifact_id"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "run_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["workflow_run_id"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "artifact_name=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["artifact_name"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "bundle_name=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["bundle"]["name"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          manifest_evaluated_commit=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["provenance"]["evaluated_commit"])' "${manifest}")
          test "${manifest_evaluated_commit}" = "${{ inputs.evaluated_commit }}"

      - name: Query selected artifact metadata
        run: >
          gh api
          "repos/${GITHUB_REPOSITORY}/actions/artifacts/${{ steps.evidence.outputs.artifact_id }}"
          > artifact-metadata.json

      - name: Download selected complete evidence
        run: >
          gh run download "${{ steps.evidence.outputs.run_id }}"
          --name "${{ steps.evidence.outputs.artifact_name }}"
          --dir downloaded-evidence

      - name: Verify release evidence before tagging
        run: >
          python -m scripts.release_evidence verify
          --repository-root .
          --manifest "${{ steps.evidence.outputs.manifest }}"
          --release-commit "${{ inputs.release_commit }}"
          --tag "${{ inputs.tag }}"
          --bundle "downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}"
          --artifact-metadata artifact-metadata.json
          --json
```

- [ ] **Step 4: Run workflow tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the pre-release workflow**

```powershell
git add .github/workflows/release-evidence.yml tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py
git commit -m "ci: capture release quality evidence"
```

### Task 7: Verify Evidence And Create Draft Releases On Protected Tags

**Files:**
- Modify: `.github/workflows/release.yml`
- Modify: `tests/test_release_evidence_workflows.py`
- Modify: `tests/test_enterprise_governance.py`

**Interfaces:**
- Consumes: the selected compact manifest in the tagged tree and the referenced Actions artifact.
- Produces: verified distributions, SBOM, compact manifest, complete evidence ZIP, an Actions
  release artifact, and a draft GitHub Release.

- [ ] **Step 1: Add failing tag-workflow ordering tests**

Append to `tests/test_release_evidence_workflows.py`:

```python
def test_tag_workflow_verifies_evidence_before_build_and_draft_release() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    evidence = workflow.index("python -m scripts.release_evidence verify")
    build = workflow.index("python -m build --sdist --wheel")
    draft = workflow.index("gh release create")

    assert evidence < build < draft
    assert "actions: read" in workflow
    assert "contents: write" in workflow
    assert "--draft" in workflow
    assert "--verify-tag" in workflow
    assert "quality-evidence.zip" in workflow
    assert "evidence-manifest.json" in workflow
```

Update `test_release_workflow_validates_and_archives_without_pypi_publish` in
`tests/test_enterprise_governance.py` to assert:

```python
    assert "scripts.release_evidence verify" in workflow
    assert "gh release create" in workflow
    assert "--draft" in workflow
    assert "--verify-tag" in workflow
    assert "contents: write" in workflow
    assert "actions: read" in workflow
```

- [ ] **Step 2: Run tag-workflow tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py -q
```

Expected: FAIL because the tag workflow does not retrieve, verify, or publish evidence.

- [ ] **Step 3: Extend the release workflow before the build step**

Change workflow permissions to:

```yaml
permissions:
  contents: write
  actions: read
```

After `Validate tag provenance`, add steps equivalent to the verify job in Task 6:

```yaml
      - name: Resolve selected release evidence
        id: evidence
        shell: bash
        run: |
          manifest="quality-evidence/releases/${{ steps.provenance.outputs.package_version }}/evidence-manifest.json"
          test -f "${manifest}"
          echo "manifest=${manifest}" >> "${GITHUB_OUTPUT}"
          echo "artifact_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["artifact_id"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "run_id=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["workflow_run_id"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "artifact_name=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["transport"]["artifact_name"])' "${manifest}")" >> "${GITHUB_OUTPUT}"
          echo "bundle_name=$(python -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["bundle"]["name"])' "${manifest}")" >> "${GITHUB_OUTPUT}"

      - name: Query selected evidence artifact
        env:
          GH_TOKEN: ${{ github.token }}
        run: >
          gh api
          "repos/${GITHUB_REPOSITORY}/actions/artifacts/${{ steps.evidence.outputs.artifact_id }}"
          > artifact-metadata.json

      - name: Download selected evidence artifact
        env:
          GH_TOKEN: ${{ github.token }}
        run: >
          gh run download "${{ steps.evidence.outputs.run_id }}"
          --name "${{ steps.evidence.outputs.artifact_name }}"
          --dir downloaded-evidence

      - name: Verify selected release evidence
        run: >
          python -m scripts.release_evidence verify
          --repository-root .
          --manifest "${{ steps.evidence.outputs.manifest }}"
          --release-commit "${{ steps.provenance.outputs.tag_commit }}"
          --tag "${{ github.ref_name }}"
          --bundle "downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}"
          --artifact-metadata artifact-metadata.json
          --json
```

Keep the existing build, metadata verification, and SBOM steps after evidence verification.

- [ ] **Step 4: Add draft GitHub Release creation before the Actions artifact upload**

Add:

```yaml
      - name: Create or update draft GitHub Release
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          evidence_manifest="${{ steps.evidence.outputs.manifest }}"
          evidence_bundle="downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}"
          assets=(dist/*.whl dist/*.tar.gz sbom.cdx.json "${evidence_manifest}" "${evidence_bundle}")
          if gh release view "${GITHUB_REF_NAME}" --json isDraft --jq .isDraft > release-draft.txt 2>/dev/null; then
            test "$(cat release-draft.txt)" = "true"
            gh release upload "${GITHUB_REF_NAME}" "${assets[@]}" --clobber
          else
            release_args=(
              --draft
              --verify-tag
              --title "${GITHUB_REF_NAME}"
              --notes "Draft release assets generated from verified repository evidence."
            )
            if [[ "${GITHUB_REF_NAME}" == *-rc.* ]]; then
              release_args+=(--prerelease)
            fi
            gh release create "${GITHUB_REF_NAME}" "${assets[@]}" "${release_args[@]}"
          fi
```

Expand the existing `Upload release evidence` path:

```yaml
          path: |
            dist/
            sbom.cdx.json
            ${{ steps.evidence.outputs.manifest }}
            downloaded-evidence/${{ steps.evidence.outputs.bundle_name }}
```

- [ ] **Step 5: Run workflow tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit protected-tag publication changes**

```powershell
git add .github/workflows/release.yml tests/test_release_evidence_workflows.py tests/test_enterprise_governance.py
git commit -m "ci: publish verified release evidence"
```

### Task 8: Document Evidence Discovery And The Release Procedure

**Files:**
- Create: `quality-evidence/README.md`
- Modify: `.env.example`
- Modify: `docs/live_quality_gate.md`
- Modify: `docs/release_process.md`
- Modify: `tests/test_enterprise_governance.py`
- Modify: `tests/test_release_gate.py`

**Interfaces:**
- Consumes: the implemented CLI and workflows.
- Produces: an operator-facing capture, verification, and publication contract that distinguishes
  historical failed attempts from release success evidence.

- [ ] **Step 1: Add failing documentation assertions**

Append to `tests/test_enterprise_governance.py`:

```python
def test_release_quality_evidence_is_documented_as_machine_traceable() -> None:
    evidence_readme = _read("quality-evidence/README.md")
    live_quality = _read("docs/live_quality_gate.md")
    release_process = _read("docs/release_process.md")

    assert "quality-evidence/releases/<package-version>/evidence-manifest.json" in evidence_readme
    assert "20260708-203513" in evidence_readme
    assert "historical failed attempt" in evidence_readme.lower()
    assert "graph-rag-release-evidence" in live_quality
    assert "evaluated_commit" in live_quality
    assert "pre-tag" in release_process.lower()
    assert "complete quality evidence ZIP" in release_process
    assert "draft GitHub Release" in release_process
```

Append to `tests/test_release_gate.py` inside `ReleaseGateTests`:

```python
    def test_quality_gate_documentation_names_release_evidence_manifest(self) -> None:
        documentation = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                ROOT / "docs" / "live_quality_gate.md",
                ROOT / "docs" / "release_process.md",
                ROOT / "quality-evidence" / "README.md",
            )
        )

        self.assertIn("graph-rag-release-evidence", documentation)
        self.assertIn("evidence-manifest.json", documentation)
        self.assertIn("case_count=0", documentation)
        self.assertIn("Release asset", documentation)
```

- [ ] **Step 2: Run documentation tests and verify RED**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py tests/test_release_gate.py -q
```

Expected: FAIL because the evidence README and workflow documentation do not exist.

- [ ] **Step 3: Add evidence discovery documentation**

Create `quality-evidence/README.md` with these exact rules:

```markdown
# Release Quality Evidence

Release success evidence is discovered only at:

`quality-evidence/releases/<package-version>/evidence-manifest.json`

Each manifest binds a successful integration and live quality run to an
`evaluated_commit`, runtime profile hash, model suite, live-quality dataset hash,
knowledge-base artifact summary, complete bundle digest, and GitHub Actions
artifact identity.

Directories outside `quality-evidence/releases/` are diagnostic history, not
release success evidence. In particular,
`live_quality_gate/20260708-203513/` is a historical failed attempt with
`case_count=0`; it must not be selected to describe current or released quality.

Complete reports remain in the corresponding GitHub Release asset. Do not copy
credentials, raw provider payloads, customer data, or absolute workstation paths
into this directory.
```

- [ ] **Step 4: Update environment and live-quality documentation**

Add to `.env.example` near `ARTIFACT_MANIFEST_PATH`:

```dotenv
# Path visible to the release-evidence runner for the exact active manifest tested by live gates.
RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH=storage/indexes/artifact_manifest.json
```

Add a `Release Evidence` section to `docs/live_quality_gate.md` documenting:

```powershell
graph-rag-release-evidence capture --help
graph-rag-release-evidence finalize --help
graph-rag-release-evidence verify --help
```

State explicitly that:

- capture runs at the exact `evaluated_commit`;
- the artifact manifest must describe the active ready knowledge base used by the serving API;
- `case_count=0` cannot create a success manifest;
- only the compact manifest is committed;
- the complete quality evidence ZIP becomes a GitHub Release asset.

- [ ] **Step 5: Update the release checklist**

In `docs/release_process.md`, insert after local/CI verification:

1. Run `Release Quality Evidence` in `capture` mode on the prepared candidate commit.
2. Review the complete evidence ZIP and commit the finalized manifest.
3. Run the same workflow in `verify` mode against the manifest commit.
4. Create the protected tag only while pre-tag verification is green and the Actions artifact is
   unexpired.
5. Require the tag workflow to create a draft GitHub Release containing wheel, sdist, SBOM,
   compact manifest, and complete quality evidence ZIP.
6. Review the draft assets and notes before publishing.

Also state that any code, profile, policy, prompt, dependency, or corpus change after
`evaluated_commit` requires a new live evidence run.

- [ ] **Step 6: Run documentation tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py tests/test_release_gate.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit documentation and discovery semantics**

```powershell
git add quality-evidence/README.md .env.example docs/live_quality_gate.md docs/release_process.md tests/test_enterprise_governance.py tests/test_release_gate.py
git commit -m "docs: require traceable release quality evidence"
```

### Task 9: Run Focused, Full, Formatting, And Release Verification

**Files:**
- Modify only files changed automatically by Ruff formatting, if any.

**Interfaces:**
- Consumes: all implementation tasks.
- Produces: evidence that focused tests, full repository tests, formatting, static checks, and the
  offline release gate pass.

- [ ] **Step 1: Run the complete focused release-evidence slice**

Run:

```powershell
python -m pytest tests/test_release_evidence_models.py tests/test_release_evidence_capture.py tests/test_release_evidence_finalize.py tests/test_release_evidence_verifier.py tests/test_release_evidence_cli.py tests/test_release_evidence_workflows.py tests/test_entrypoints.py tests/test_release_tag_policy.py tests/test_enterprise_governance.py tests/test_release_gate.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff before the full suite**

Run:

```powershell
python -m ruff check .
python -m ruff format --check .
```

Expected: both commands PASS. If formatting fails, run:

```powershell
python -m ruff format scripts/release_evidence tests/test_release_evidence_*.py tests/release_evidence_fixtures.py
```

Then rerun both checks and inspect the diff.

- [ ] **Step 3: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run repository hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect `git diff`, rerun the focused release-evidence slice,
and rerun `pre-commit run --all-files`.

- [ ] **Step 5: Run the offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 6: Check the final diff and generated-file boundaries**

Run:

```powershell
git status --short
git diff --check
git diff --stat
git ls-files eval/reports
```

Expected:

- `git diff --check` passes;
- no `eval/reports/` files, ZIP files, credentials, or local artifact manifests are tracked;
- only the planned source, workflow, test, and documentation files changed.

- [ ] **Step 7: Commit any verification-only formatting changes**

If Step 2 or Step 4 changed files:

```powershell
git add scripts/release_evidence tests .github/workflows pyproject.toml .env.example quality-evidence/README.md docs/live_quality_gate.md docs/release_process.md
git commit -m "style: normalize release evidence implementation"
```

If no files changed, do not create an empty commit.

- [ ] **Step 8: Record the operational verification still required**

Before declaring the feature operationally complete, run `.github/workflows/release-evidence.yml`
in `capture` mode against an actual prepared pre-release environment, commit its finalized manifest
to a release candidate branch, and run the workflow in `verify` mode. Do not create a tag merely to
test this feature. The implementation can be code-complete with local tests, but release-quality
evidence is not proven until this external run succeeds.
