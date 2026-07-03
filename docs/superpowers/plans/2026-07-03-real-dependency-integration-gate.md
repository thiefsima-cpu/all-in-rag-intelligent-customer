# Real-Dependency Integration Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a separate real-dependency integration gate that proves Neo4j, Milvus, serving API, and model-provider behavior while keeping the existing release gate deterministic and offline.

**Architecture:** Split the monolithic offline gate into an application-specific package over a small typed `scripts.gates` kernel. Build a separate `scripts.integration_gate` package with strict policy/environment models, injected dependency probes, typed live observations, deterministic evaluation, redacted reports, and a console entry point; delete the obsolete optional-quality compatibility path instead of preserving shims.

**Tech Stack:** Python 3.11, dataclasses and `StrEnum`, Pydantic 2, Requests, Neo4j Python driver, PyMilvus, pytest/unittest, Ruff, mypy, JSON policies, Markdown reports.

---

## File Structure

Create these focused modules:

- `scripts/gates/models.py`: shared typed check results, statuses, failure types, and aggregate evaluation.
- `scripts/gates/evaluation.py`: finite numeric threshold evaluation and check aggregation.
- `scripts/gates/reporting.py`: JSON-safe values, JSON report writes, and shared summary formatting.
- `scripts/offline_gate/policy.py`: offline policy loading and required quality-runner validation.
- `scripts/offline_gate/runners.py`: deterministic smoke-suite and offline-quality execution.
- `scripts/offline_gate/evaluator.py`: route/category/quality-specific offline checks.
- `scripts/offline_gate/reporter.py`: offline Markdown report rendering.
- `scripts/offline_gate/service.py`: offline gate orchestration.
- `scripts/integration_gate/models.py`: strict integration policy, runtime settings, and live observation models.
- `scripts/integration_gate/probes.py`: injected Neo4j, Milvus, and serving readiness probes.
- `scripts/integration_gate/live_cases.py`: debug-answer HTTP client, response normalization, and case checks.
- `scripts/integration_gate/evaluator.py`: aggregate source-coverage, fallback, degradation, latency, token, and cost checks.
- `scripts/integration_gate/reporter.py`: redacted integration JSON and Markdown reports.
- `scripts/integration_gate/service.py`: prerequisite-aware orchestration.
- `scripts/integration_gate/cli.py` and `__main__.py`: installed and `python -m` entry points.

Delete `scripts/release_policy.py` after its live responsibilities have moved. Keep
`scripts/release_gate.py` as the thin, backwards-current command path; do not retain removed CLI
arguments or imports.

## Task 1: Shared Typed Gate Kernel

**Files:**
- Create: `scripts/gates/__init__.py`
- Create: `scripts/gates/models.py`
- Create: `scripts/gates/evaluation.py`
- Create: `scripts/gates/reporting.py`
- Create: `tests/test_gate_kernel.py`

- [ ] **Step 1: Write failing model and threshold tests**

Create `tests/test_gate_kernel.py` with these contract tests:

```python
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

from scripts.gates.evaluation import aggregate_checks, numeric_threshold_check
from scripts.gates.models import GateCheckResult, GateCheckStatus, GateFailureType
from scripts.gates.reporting import write_json_report


def test_gate_check_factories_produce_stable_payloads() -> None:
    passed = GateCheckResult.pass_check("neo4j.recipe_count", expected=">=1", actual=12)
    failed = GateCheckResult.fail_check(
        "milvus.entity_count",
        failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
        code="MILVUS_COLLECTION_EMPTY",
        expected=">=1",
        actual=0,
    )
    blocked = GateCheckResult.block_check(
        "case.vector_recipe",
        code="PREREQUISITE_FAILED",
    )

    assert passed.to_dict()["status"] == "passed"
    assert failed.to_dict()["failure_type"] == "dependency-unavailable"
    assert blocked.to_dict()["status"] == "blocked"
    assert blocked.passed is False


def test_numeric_threshold_rejects_non_finite_values_and_aggregates_failures() -> None:
    checks = [
        numeric_threshold_check("latency", 20.0, maximum=20.0),
        numeric_threshold_check("cost", 1.01, maximum=1.0),
        numeric_threshold_check("tokens", math.inf, minimum=1.0),
    ]

    evaluation = aggregate_checks(checks)

    assert evaluation.passed is False
    assert evaluation.failure_type_counts == {"budget-regression": 2}
    assert checks[1].code == "METRIC_ABOVE_MAXIMUM"
    assert checks[2].code == "METRIC_NOT_FINITE"


def test_json_report_writer_serializes_enums_without_mutating_report() -> None:
    report = {
        "passed": False,
        "failure_type": GateFailureType.CONTRACT_REGRESSION,
        "checks": [GateCheckResult.block_check("case.graph", code="PREREQUISITE_FAILED")],
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        path = write_json_report(report, Path(temp_dir) / "report.json")
        payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["failure_type"] == "contract-regression"
    assert payload["checks"][0]["status"] == "blocked"
    assert isinstance(report["checks"][0], GateCheckResult)
```

- [ ] **Step 2: Run the kernel tests and verify RED**

Run:

```powershell
python -m pytest tests/test_gate_kernel.py -q
```

Expected: collection fails because `scripts.gates` does not exist.

- [ ] **Step 3: Implement the typed kernel**

In `scripts/gates/models.py`, implement the exact shared vocabulary:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GateCheckStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class GateFailureType(StrEnum):
    DEPENDENCY_UNAVAILABLE = "dependency-unavailable"
    CONTRACT_REGRESSION = "contract-regression"
    QUALITY_REGRESSION = "quality-regression"
    BUDGET_REGRESSION = "budget-regression"
    GATE_ERROR = "gate-error"


@dataclass(frozen=True)
class GateCheckResult:
    name: str
    status: GateCheckStatus
    failure_type: GateFailureType | None = None
    code: str = ""
    expected: Any = None
    actual: Any = None
    duration_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status is GateCheckStatus.PASSED

    @classmethod
    def pass_check(cls, name: str, **values: Any) -> "GateCheckResult":
        return cls(name=name, status=GateCheckStatus.PASSED, **values)

    @classmethod
    def fail_check(
        cls,
        name: str,
        *,
        failure_type: GateFailureType,
        code: str,
        **values: Any,
    ) -> "GateCheckResult":
        return cls(
            name=name,
            status=GateCheckStatus.FAILED,
            failure_type=failure_type,
            code=code,
            **values,
        )

    @classmethod
    def block_check(cls, name: str, *, code: str) -> "GateCheckResult":
        return cls(name=name, status=GateCheckStatus.BLOCKED, code=code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "status": self.status.value,
            "failure_type": self.failure_type.value if self.failure_type else None,
            "code": self.code,
            "expected": self.expected,
            "actual": self.actual,
            "duration_ms": round(self.duration_ms, 3),
        }


@dataclass(frozen=True)
class GateEvaluation:
    checks: tuple[GateCheckResult, ...]
    passed: bool
    failure_type_counts: dict[str, int]
```

In `scripts/gates/evaluation.py`, implement inclusive finite threshold checks and aggregation:

```python
def numeric_threshold_check(
    name: str,
    actual: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    failure_type: GateFailureType = GateFailureType.BUDGET_REGRESSION,
) -> GateCheckResult:
    if isinstance(actual, bool) or not isinstance(actual, (int, float)):
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_NOT_NUMERIC",
            expected={"minimum": minimum, "maximum": maximum},
            actual=actual,
        )
    value = float(actual)
    if not math.isfinite(value):
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_NOT_FINITE",
            expected={"minimum": minimum, "maximum": maximum},
            actual=str(actual),
        )
    if minimum is not None and value < minimum:
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_BELOW_MINIMUM",
            expected=f">={minimum}",
            actual=value,
        )
    if maximum is not None and value > maximum:
        return GateCheckResult.fail_check(
            name,
            failure_type=failure_type,
            code="METRIC_ABOVE_MAXIMUM",
            expected=f"<={maximum}",
            actual=value,
        )
    return GateCheckResult.pass_check(
        name,
        expected={"minimum": minimum, "maximum": maximum},
        actual=value,
    )


def aggregate_checks(checks: Iterable[GateCheckResult]) -> GateEvaluation:
    materialized = tuple(checks)
    counts = Counter(
        check.failure_type.value
        for check in materialized
        if check.status is GateCheckStatus.FAILED and check.failure_type is not None
    )
    return GateEvaluation(
        checks=materialized,
        passed=all(check.status is GateCheckStatus.PASSED for check in materialized),
        failure_type_counts=dict(sorted(counts.items())),
    )
```

In `scripts/gates/reporting.py`, recursively serialize supported values without mutation:

```python
def json_safe(value: object) -> object:
    if isinstance(value, StrEnum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        if hasattr(value, "to_dict"):
            return json_safe(value.to_dict())
        return json_safe(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]
    return value


def write_json_report(report: Mapping[str, object], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
```

Re-export only these public names from `scripts/gates/__init__.py`:

```python
from .evaluation import aggregate_checks, numeric_threshold_check
from .models import GateCheckResult, GateCheckStatus, GateEvaluation, GateFailureType
from .reporting import json_safe, write_json_report
```

- [ ] **Step 4: Run kernel tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_gate_kernel.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit the shared kernel**

```powershell
git add scripts/gates tests/test_gate_kernel.py
git commit -m "refactor: add typed gate kernel"
```

## Task 2: Replace the Offline Compatibility Gate With Required-Only Modules

**Files:**
- Create: `scripts/offline_gate/__init__.py`
- Create: `scripts/offline_gate/policy.py`
- Create: `scripts/offline_gate/runners.py`
- Create: `scripts/offline_gate/evaluator.py`
- Create: `scripts/offline_gate/reporter.py`
- Create: `scripts/offline_gate/service.py`
- Modify: `scripts/release_gate.py`
- Modify: `tests/test_release_gate.py`
- Delete: `scripts/release_policy.py`

- [ ] **Step 1: Rewrite tests around a required-only offline contract**

In `tests/test_release_gate.py`, keep the existing deterministic suite fixtures and threshold
coverage, but delete `_legacy_optional_policy()` and every test of `optional_stages`,
`INCLUDE_QUALITY_EVAL_ENV`, `_environment_flag`, or `--include-quality-eval`. Replace their CLI and
service tests with:

```python
def test_release_gate_cli_accepts_only_current_arguments() -> None:
    with (
        patch.object(sys, "argv", ["release_gate.py", "--include-quality-eval"]),
        patch("scripts.release_gate.run_release_gate") as run,
        pytest.raises(SystemExit) as raised,
    ):
        main()

    assert raised.value.code == 2
    run.assert_not_called()


def test_required_quality_runner_does_not_read_optional_stage() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    policy["optional_stages"] = {
        "quality_eval": {
            "runner": {"profile": "wrong", "top_k": 1, "generate": False}
        }
    }

    stage = required_quality_stage(policy)

    assert stage.runner.profile == "eval_quality"
    assert stage.runner.top_k == 6
    assert stage.runner.generate is True


def test_release_report_has_no_optional_stage_fields() -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("scripts.offline_gate.service.run_suites", return_value=_passing_reports_for_policy(policy)):
            report = run_release_gate(output_dir=temp_dir)

    assert "included_optional_stages" not in report
    assert report["quality_eval_required"] is True
```

Add a source-level retirement assertion:

```python
def test_optional_quality_compatibility_is_retired() -> None:
    current_sources = [
        ROOT / "scripts" / "release_gate.py",
        *sorted((ROOT / "scripts" / "offline_gate").glob("*.py")),
    ]
    retired = ("include-quality-eval", "INCLUDE_QUALITY_EVAL", "optional_stages")

    findings = [
        f"{path}:{token}"
        for path in current_sources
        for token in retired
        if token in path.read_text(encoding="utf-8")
    ]
    assert findings == []
```

- [ ] **Step 2: Run offline tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py -q
```

Expected: imports fail because `scripts.offline_gate` does not exist and current CLI still accepts
the retired flag.

- [ ] **Step 3: Split the offline implementation by responsibility**

Move code without compatibility wrappers using this exact ownership map:

```text
scripts/offline_gate/policy.py
  DEFAULT_POLICY_PATH, load_policy, validate_policy, QualityRunnerSettings,
  required_quality_stage

scripts/offline_gate/runners.py
  SUITE_RUNNERS, SuiteRunner, run_suites, run_quality_eval

scripts/offline_gate/evaluator.py
  evaluate_gate and all offline route/category/dimension/metric helper functions

scripts/offline_gate/reporter.py
  DEFAULT_OUTPUT_DIR, write_report and offline Markdown helpers

scripts/offline_gate/service.py
  run_release_gate
```

Define the required runner as a dataclass instead of a loose stage dictionary:

```python
@dataclass(frozen=True)
class QualityRunnerSettings:
    profile: str
    top_k: int
    generate: bool


def required_quality_stage(policy: Mapping[str, Any]) -> QualityRunnerSettings:
    runners = policy.get("suite_runners")
    configured = runners.get("quality_eval") if isinstance(runners, dict) else None
    if not isinstance(configured, dict):
        raise ValueError("Required release-gate suite has no runner: quality_eval")
    profile = configured.get("profile")
    top_k = configured.get("top_k")
    generate = configured.get("generate")
    if (
        not isinstance(profile, str)
        or not profile.strip()
        or isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k <= 0
        or not isinstance(generate, bool)
    ):
        raise ValueError("Required release-gate suite has invalid runner settings: quality_eval")
    return QualityRunnerSettings(profile=profile.strip(), top_k=top_k, generate=generate)
```

Replace string-marker exception classification in `run_suites()` with an explicit
`OfflineSuiteFailure` carrying `GateFailureType`; unexpected exceptions become `gate-error`. Keep
all existing successful suite report shapes so offline metric behavior does not change. Map the
old offline `metric-regression` and `suite-regression` outcomes to the single typed
`quality-regression`; map runner defects to `gate-error`. Update expected failure types in the
offline tests rather than retaining old string aliases.

- [ ] **Step 4: Delete compatibility and make the CLI thin**

Delete `scripts/release_policy.py`. In `scripts/release_gate.py`, accept only `--policy`,
`--output-dir`, and `--json`, then call:

```python
report = run_release_gate(policy_path=args.policy, output_dir=args.output_dir)
```

Remove `__all__` compatibility exports from the CLI module. Export the supported programmatic
surface from `scripts/offline_gate/__init__.py`:

```python
from .evaluator import evaluate_gate
from .policy import DEFAULT_POLICY_PATH, load_policy, required_quality_stage
from .reporter import DEFAULT_OUTPUT_DIR, write_report
from .runners import run_quality_eval, run_suites
from .service import run_release_gate
```

Update test imports to this package. Remove optional-stage fields from report construction and
Markdown output; print `quality_eval: required` directly.

- [ ] **Step 5: Run focused offline tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_gate_kernel.py tests/test_release_gate.py -q
```

Expected: all kernel and release-gate tests pass, including the source retirement assertion.

- [ ] **Step 6: Commit the offline refactor**

```powershell
git add scripts/release_gate.py scripts/offline_gate scripts/release_policy.py tests/test_release_gate.py
git commit -m "refactor: make offline gate required only"
```

## Task 3: Strict Integration Policy and Runtime Settings

**Files:**
- Create: `scripts/integration_gate/__init__.py`
- Create: `scripts/integration_gate/models.py`
- Create: `eval/integration_gate.json`
- Create: `tests/test_integration_gate_config.py`
- Modify: `.env.example`

- [ ] **Step 1: Write failing strict-config tests**

Create `tests/test_integration_gate_config.py`:

```python
from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from scripts.integration_gate.models import (
    DEFAULT_POLICY_PATH,
    IntegrationGateSettings,
    load_integration_policy,
)


def test_default_policy_has_three_unique_dependency_covering_cases() -> None:
    policy = load_integration_policy(DEFAULT_POLICY_PATH)

    assert [case.case_id for case in policy.live_cases] == [
        "vector_recipe_lookup",
        "graph_relationship_reasoning",
        "combined_constrained_recommendation",
    ]
    assert {source for case in policy.live_cases for source in case.required_sources} >= {
        "vector",
        "graph_rag",
    }
    assert all(case.generation_required for case in policy.live_cases)


def test_policy_rejects_duplicate_ids_and_non_positive_limits() -> None:
    policy = load_integration_policy(DEFAULT_POLICY_PATH)
    payload = policy.model_dump(mode="json")
    payload["live_cases"][1]["case_id"] = payload["live_cases"][0]["case_id"]
    payload["timeouts"]["probe_seconds"] = 0

    with pytest.raises(ValidationError):
        type(policy).model_validate(payload)


def test_settings_require_explicit_endpoints_and_keep_token_optional() -> None:
    environment = {
        "INTEGRATION_GATE_API_URL": "http://localhost:8000",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "localhost",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }
    settings = IntegrationGateSettings.from_environ(environment)

    assert settings.api_url == "http://localhost:8000"
    assert settings.api_token is None
    assert settings.safe_target_identity() == {
        "api_host": "localhost",
        "neo4j_host": "localhost",
        "milvus_host": "localhost",
    }

    environment.pop("NEO4J_PASSWORD")
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        IntegrationGateSettings.from_environ(environment)
```

- [ ] **Step 2: Run config tests and verify RED**

Run:

```powershell
python -m pytest tests/test_integration_gate_config.py -q
```

Expected: collection fails because integration models and policy do not exist.

- [ ] **Step 3: Implement strict Pydantic policy models**

In `scripts/integration_gate/models.py`, define `extra="forbid"` Pydantic models:

```python
class DependencyMinimums(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    neo4j_recipe_count: int = Field(ge=1)
    milvus_entity_count: int = Field(ge=1)


class GateTimeouts(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    probe_seconds: float = Field(gt=0)
    request_seconds: float = Field(gt=0)


class LiveCasePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    allowed_strategies: list[str] = Field(min_length=1)
    required_sources: list[str] = Field(min_length=1)
    minimum_evidence_count: int = Field(ge=1)
    generation_required: bool
    timeout_seconds: float = Field(gt=0)


class IntegrationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    maximum_fallback_rate: float = Field(ge=0, le=1)
    maximum_retrieval_degradation_rate: float = Field(ge=0, le=1)
    maximum_p95_latency_ms: float = Field(gt=0)
    maximum_estimated_cost_usd: float = Field(ge=0)


class IntegrationGatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    schema_version: Literal[1]
    dependency_minimums: DependencyMinimums
    timeouts: GateTimeouts
    thresholds: IntegrationThresholds
    live_cases: list[LiveCasePolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_cases(self) -> "IntegrationGatePolicy":
        case_ids = [case.case_id for case in self.live_cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Integration gate live case IDs must be unique.")
        return self
```

Add frozen `IntegrationGateSettings.from_environ()` with the eight required fields in the test and
optional `INTEGRATION_GATE_API_TOKEN`. Strip the API URL trailing slash. Use `urlsplit()` for safe
host identity and never expose userinfo, paths, or query strings.

- [ ] **Step 4: Add the default live policy and environment examples**

Create `eval/integration_gate.json` with schema version `1`, minimum counts of `1`, a 10-second
probe timeout, a 90-second request timeout, zero fallback/degradation, 60-second P95 latency, and a
USD 1.00 aggregate cost cap. Define these cases:

```json
[
  {
    "case_id": "vector_recipe_lookup",
    "question": "宫保鸡丁怎么做？",
    "allowed_strategies": ["hybrid_traditional", "combined"],
    "required_sources": ["vector"],
    "minimum_evidence_count": 1,
    "generation_required": true,
    "timeout_seconds": 60
  },
  {
    "case_id": "graph_relationship_reasoning",
    "question": "为什么宫保鸡丁里的花生和辣椒会影响整体风味，它们之间是什么关系？",
    "allowed_strategies": ["graph_rag", "combined"],
    "required_sources": ["graph_rag"],
    "minimum_evidence_count": 1,
    "generation_required": true,
    "timeout_seconds": 90
  },
  {
    "case_id": "combined_constrained_recommendation",
    "question": "推荐带豆腐、口味清淡的家常菜，并解释食材、风味和减脂条件之间的关系。",
    "allowed_strategies": ["combined"],
    "required_sources": ["vector", "graph_rag"],
    "minimum_evidence_count": 1,
    "generation_required": true,
    "timeout_seconds": 90
  }
]
```

Add to `.env.example` under endpoints/security:

```dotenv
INTEGRATION_GATE_API_URL=http://localhost:8000
INTEGRATION_GATE_API_TOKEN=
```

- [ ] **Step 5: Run config tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_integration_gate_config.py -q
```

Expected: all config tests pass.

- [ ] **Step 6: Commit config and policy**

```powershell
git add scripts/integration_gate eval/integration_gate.json tests/test_integration_gate_config.py .env.example
git commit -m "feat: define integration gate policy"
```

## Task 4: Real Dependency Probes With Typed Failures

**Files:**
- Create: `scripts/integration_gate/probes.py`
- Create: `tests/test_integration_gate_probes.py`

- [ ] **Step 1: Write failing probe tests with injected fakes**

Create fake clients exposing only the methods used by the probes. Cover success, authentication or
transport errors, missing/empty collections, unready APIs, and guaranteed close behavior. The core
success test must be:

```python
def test_dependency_probes_return_counts_and_readiness_without_secrets() -> None:
    neo4j = FakeNeo4jDriver(recipe_count=12)
    milvus = FakeMilvusClient(collections=["cooking_knowledge"], row_count=20)
    http = FakeHttpSession(
        get_responses={
            "/v1/health/ready": {"ready": True},
            "/v1/diagnostics": {
                "diagnostics": {
                    "artifacts_ready": True,
                    "retrieval_engines_initialized": True,
                    "system_ready": True,
                }
            },
        }
    )

    results = run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=lambda *_args, **_kwargs: neo4j,
        milvus_client_factory=lambda *_args, **_kwargs: milvus,
        http_session=http,
    )

    assert all(result.passed for result in results)
    assert {result.name: result.actual for result in results} == {
        "dependency.neo4j.recipe_count": 12,
        "dependency.milvus.entity_count": 20,
        "dependency.serving.ready": True,
    }
    assert neo4j.closed is True
```

Add focused assertions that failures use `NEO4J_UNAVAILABLE`, `MILVUS_UNAVAILABLE`,
`MILVUS_COLLECTION_MISSING`, `MILVUS_COLLECTION_EMPTY`, `SERVING_API_UNAVAILABLE`, or
`SERVING_API_NOT_READY`, all with `GateFailureType.DEPENDENCY_UNAVAILABLE` and no raw exception
text in `actual`.

- [ ] **Step 2: Run probe tests and verify RED**

Run:

```powershell
python -m pytest tests/test_integration_gate_probes.py -q
```

Expected: import fails because `probes.py` does not exist.

- [ ] **Step 3: Implement Neo4j and Milvus probes**

Use injectable factory protocols and production defaults `neo4j.GraphDatabase.driver` and
`pymilvus.MilvusClient`. Neo4j executes exactly:

```cypher
MATCH (recipe:Recipe) RETURN count(recipe) AS recipe_count
```

Milvus calls `list_collections()`, accepts the configured name as a physical collection or alias,
loads the resolved target, then reads `row_count` from `get_collection_stats()`. Always close the
driver/client when the object supports `close()`.

Wrap SDK exceptions at each boundary into the stable failed result; do not inspect exception text.
Record only the safe expected count and a boolean/zero actual value.

- [ ] **Step 4: Implement serving readiness probe**

Use `requests.Session.get()` with the bearer header only when a token exists. Require HTTP success
from both readiness and diagnostics endpoints, then require all three diagnostic booleans. Return
one aggregate result named `dependency.serving.ready`; never put response bodies or headers into a
failure result.

Expose:

```python
def run_dependency_probes(
    *,
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
    neo4j_driver_factory: Neo4jDriverFactory = GraphDatabase.driver,
    milvus_client_factory: MilvusClientFactory = MilvusClient,
    http_session: requests.Session | None = None,
) -> tuple[GateCheckResult, ...]:
    session = http_session or requests.Session()
    return (
        probe_neo4j(
            settings=settings,
            minimum_count=policy.dependency_minimums.neo4j_recipe_count,
            driver_factory=neo4j_driver_factory,
        ),
        probe_milvus(
            settings=settings,
            minimum_count=policy.dependency_minimums.milvus_entity_count,
            client_factory=milvus_client_factory,
        ),
        probe_serving(
            settings=settings,
            timeout_seconds=policy.timeouts.probe_seconds,
            http_session=session,
        ),
    )
```

- [ ] **Step 5: Run probe tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_integration_gate_probes.py -q
```

Expected: all probe tests pass without network access.

- [ ] **Step 6: Commit probes**

```powershell
git add scripts/integration_gate/probes.py tests/test_integration_gate_probes.py
git commit -m "feat: probe integration dependencies"
```

## Task 5: Live Debug-Answer Cases and Deterministic Evaluation

**Files:**
- Modify: `scripts/integration_gate/models.py`
- Create: `scripts/integration_gate/live_cases.py`
- Create: `scripts/integration_gate/evaluator.py`
- Create: `tests/test_integration_gate_live_cases.py`

- [ ] **Step 1: Write failing live-case normalization tests**

Build a valid debug response using `AnswerResponseModel.model_validate()` with route stages whose
`sources` contain `vector` and `graph_rag`, evidence documents, and a generation trace with positive
tokens. Assert this normalized observation:

```python
assert observation.case_id == "combined_constrained_recommendation"
assert observation.strategy == "combined"
assert observation.sources == frozenset({"vector", "graph_rag", "combined"})
assert observation.evidence_count == 2
assert observation.total_tokens == 120
assert observation.estimated_cost_usd == 0.03
assert observation.fallback_used is False
assert observation.retrieval_degraded is False
```

Add tests that invalid Pydantic response shape becomes `API_RESPONSE_CONTRACT_INVALID`, missing
sources becomes `REQUIRED_SOURCE_MISSING`, unexpected strategy becomes `STRATEGY_MISMATCH`, zero
tokens becomes `MODEL_USAGE_NOT_PROVEN`, and any summary/route/generation fallback becomes
`FALLBACK_USED`.

- [ ] **Step 2: Run live-case tests and verify RED**

Run:

```powershell
python -m pytest tests/test_integration_gate_live_cases.py -q
```

Expected: imports fail because live-case modules do not exist.

- [ ] **Step 3: Add the immutable live observation model**

In `models.py`, add:

```python
@dataclass(frozen=True)
class LiveCaseObservation:
    case_id: str
    strategy: str
    sources: frozenset[str]
    evidence_count: int
    fallback_used: bool
    retrieval_degraded: bool
    latency_ms: float
    total_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class LiveCaseRunResult:
    case_id: str
    observation: LiveCaseObservation | None
    checks: tuple[GateCheckResult, ...]
```

- [ ] **Step 4: Implement the debug-answer client and normalizer**

POST to `{api_url}/v1/debug/answers` with `{"question": case.question, "stream": false,
"explain_routing": true}`, `X-Request-ID: integration-gate-<uuid>`, bearer auth when configured,
and the smaller of the case timeout and global request timeout.

Parse with `rag_modules.interfaces.api.answer_models.AnswerResponseModel`. Build sources from both
`grounding.evidence_documents[*].source` and every positive count in
`traces.route_trace.stages[*].sources`. Build fallback from summary, route diagnostics, and
generation trace. Build degradation from public diagnostics and route diagnostics. Use summary
latency/cost plus generation-trace token count.

Return a typed failed check for transport/HTTP (`SERVING_API_REQUEST_FAILED`) or schema
(`API_RESPONSE_CONTRACT_INVALID`) without recording response content.

- [ ] **Step 5: Implement per-case and aggregate evaluation**

`evaluate_live_case(case, observation)` returns one result for each contract dimension:

```text
case.<id>.strategy
case.<id>.sources
case.<id>.evidence_count
case.<id>.fallback
case.<id>.retrieval_degradation
case.<id>.model_usage
```

Use `contract-regression` for response/strategy contract failures, `quality-regression` for source,
evidence, fallback, and degradation failures, and `budget-regression` for per-case timeout failures.

`evaluate_integration_metrics()` requires global vector and graph coverage, calculates fallback and
degradation rates over executed observations, calculates nearest-rank P95 latency, sums estimated
cost, and checks all four policy thresholds through the shared kernel.

- [ ] **Step 6: Run live-case tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_integration_gate_live_cases.py -q
```

Expected: all response, case, and metric tests pass.

- [ ] **Step 7: Commit live evaluation**

```powershell
git add scripts/integration_gate/models.py scripts/integration_gate/live_cases.py scripts/integration_gate/evaluator.py tests/test_integration_gate_live_cases.py
git commit -m "feat: evaluate live dependency cases"
```

## Task 6: Prerequisite-Aware Service, Redacted Reports, and CLI

**Files:**
- Create: `scripts/integration_gate/reporter.py`
- Create: `scripts/integration_gate/service.py`
- Create: `scripts/integration_gate/cli.py`
- Create: `scripts/integration_gate/__main__.py`
- Modify: `scripts/integration_gate/__init__.py`
- Create: `tests/test_integration_gate.py`
- Modify: `tests/test_entrypoints.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing orchestration and redaction tests**

Create `tests/test_integration_gate.py` with injected probe and case runners. Assert that a failed
probe produces three blocked case checks and zero case-runner calls; successful probes run every
case even if the first case fails. Assert report JSON/Markdown contain case IDs and stable error
codes but not question text, password, bearer token, full URL path/query, raw exception, or response
body.

Add CLI exit tests:

```python
@pytest.mark.parametrize(
    ("report", "expected"),
    [({"passed": True}, 0), ({"passed": False}, 1)],
)
def test_cli_maps_evaluated_status_to_exit_code(report: dict, expected: int) -> None:
    with (
        patch.object(sys, "argv", ["integration_gate", "--json"]),
        patch("scripts.integration_gate.cli.run_integration_gate", return_value=report),
    ):
        assert main() == expected


def test_cli_returns_two_for_configuration_error() -> None:
    with (
        patch.object(sys, "argv", ["integration_gate", "--json"]),
        patch(
            "scripts.integration_gate.cli.run_integration_gate",
            side_effect=IntegrationGateConfigurationError("invalid settings"),
        ),
    ):
        assert main() == 2
```

In `tests/test_entrypoints.py`, parse `pyproject.toml` and assert:

```python
assert scripts["graph-rag-integration-gate"] == "scripts.integration_gate.cli:main"
```

- [ ] **Step 2: Run orchestration tests and verify RED**

Run:

```powershell
python -m pytest tests/test_integration_gate.py tests/test_entrypoints.py -q
```

Expected: imports/entrypoint assertions fail because service, reporter, CLI, and command are absent.

- [ ] **Step 3: Implement service orchestration**

Expose this injectable API in `service.py`:

```python
def run_integration_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    environ: Mapping[str, str] | None = None,
    probe_runner: ProbeRunner = run_dependency_probes,
    case_runner: LiveCaseRunner = run_live_case,
) -> dict[str, Any]:
    try:
        policy = load_integration_policy(policy_path)
        settings = IntegrationGateSettings.from_environ(environ or os.environ)
    except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        raise IntegrationGateConfigurationError("Integration gate configuration is invalid.") from exc

    probe_checks = probe_runner(settings=settings, policy=policy)
    checks = list(probe_checks)
    case_results: list[LiveCaseRunResult] = []
    if all(check.passed for check in probe_checks):
        for case in policy.live_cases:
            result = case_runner(settings=settings, policy=policy, case=case)
            case_results.append(result)
            checks.extend(result.checks)
        observations = [
            result.observation
            for result in case_results
            if result.observation is not None
        ]
        checks.extend(evaluate_integration_metrics(policy, observations))
    else:
        for case in policy.live_cases:
            checks.append(
                GateCheckResult.block_check(
                    f"case.{case.case_id}",
                    code="PREREQUISITE_FAILED",
                )
            )

    evaluation = aggregate_checks(checks)
    report = build_integration_report(
        policy=policy,
        settings=settings,
        evaluation=evaluation,
        case_results=case_results,
    )
    write_integration_report(report, output_dir)
    return report
```

Load configuration first. Run probes. If any probe fails, append one blocked check per policy case
and do not call `case_runner`. Otherwise execute every case, preserving typed observations only for
successful HTTP/schema normalization and appending each case's deterministic checks. Aggregate all
checks, attach safe target identity and aggregate metrics, then write both reports.

Use `generated_at` in UTC ISO-8601, `schema_version: 1`, and report sections `target`, `metrics`,
`checks`, and `cases`. Case report rows contain IDs and numeric summaries only, never questions.

- [ ] **Step 4: Implement redacted JSON and Markdown reports**

Write to `eval/reports/integration_gate/report.json` and `summary.md`. The Markdown heading is
`# Real-Dependency Integration Gate`; include status, target hostnames, metric totals, failure type
counts, and a failed-check table containing name/code/expected/actual. Before serialization, apply
an allowlist projection rather than a blacklist so no client objects, settings credentials,
questions, headers, or exceptions can enter the report.

- [ ] **Step 5: Implement CLI and installed entry point**

`cli.py` accepts `--policy`, `--output-dir`, and `--json`, configures UTF-8 output, and maps exit
codes exactly as tested. Configuration/Pydantic/JSON errors print one safe `gate-error` payload to
stderr and return `2`; they do not print exception repr or environment values.

`__main__.py` contains:

```python
from .cli import main

raise SystemExit(main())
```

Add to `[project.scripts]`:

```toml
graph-rag-integration-gate = "scripts.integration_gate.cli:main"
```

- [ ] **Step 6: Run orchestration tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_integration_gate.py tests/test_entrypoints.py -q
```

Expected: all orchestration, redaction, CLI, and entrypoint tests pass.

- [ ] **Step 7: Commit service and CLI**

```powershell
git add scripts/integration_gate tests/test_integration_gate.py tests/test_entrypoints.py pyproject.toml
git commit -m "feat: add integration gate command"
```

## Task 7: Operator Documentation, Retirement Audit, and Full Verification

**Files:**
- Create: `docs/real_dependency_integration_gate.md`
- Modify: `docs/offline_evaluation_release_gate.md`
- Modify: `README.md`
- Modify: `tests/test_release_gate.py`

- [ ] **Step 1: Add a failing documentation contract test**

Add to `tests/test_release_gate.py`:

```python
def test_gate_docs_define_two_layers_and_no_retired_switches() -> None:
    paths = [
        ROOT / "README.md",
        ROOT / "docs" / "offline_evaluation_release_gate.md",
        ROOT / "docs" / "real_dependency_integration_gate.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in paths)

    assert "graph-rag-release-gate" in text
    assert "graph-rag-integration-gate" in text
    assert "does not start or stop" in text
    assert "--include-quality-eval" not in text
    assert "RELEASE_GATE_INCLUDE_QUALITY_EVAL" not in text
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py::test_gate_docs_define_two_layers_and_no_retired_switches -q
```

Expected: fails because the integration-gate document does not exist.

- [ ] **Step 3: Write operator documentation**

Document these exact operations in `docs/real_dependency_integration_gate.md`:

```powershell
docker compose --profile api up --build
graph-rag-integration-gate
graph-rag-integration-gate --json
python -m scripts.integration_gate --policy eval/integration_gate.json
```

State prerequisites: completed bootstrap/build, ready serving API, reachable Neo4j/Milvus, provider
key configured on the API service, and explicit gate environment values. Document exit codes,
failure types, output paths, token/cost implications, safe CI scheduling, and that the gate does not
start or stop infrastructure.

Update README's command list and release section to explain the two independent layers. Update the
offline document to state that quality evaluation is always required and remove all optional-stage
language.

- [ ] **Step 4: Run focused gate tests**

Run:

```powershell
python -m pytest tests/test_gate_kernel.py tests/test_release_gate.py tests/test_integration_gate_config.py tests/test_integration_gate_probes.py tests/test_integration_gate_live_cases.py tests/test_integration_gate.py tests/test_entrypoints.py -q
```

Expected: all focused tests pass.

- [ ] **Step 5: Run retirement and secret scans**

Run:

```powershell
rg -n "include-quality-eval|RELEASE_GATE_INCLUDE_QUALITY_EVAL|optional_stages|activate_optional_stages" scripts tests README.md docs/offline_evaluation_release_gate.md docs/real_dependency_integration_gate.md
rg -n "API_TOKEN|PASSWORD|Authorization|question" scripts/integration_gate
```

Expected: first command returns no matches. Second command returns only environment loading, request
construction, and explicit allowlist/redaction tests; manually verify no report projection includes
those values.

- [ ] **Step 6: Run Ruff and formatting checks**

Run:

```powershell
python -m ruff check scripts/gates scripts/offline_gate scripts/integration_gate scripts/release_gate.py tests/test_gate_kernel.py tests/test_release_gate.py tests/test_integration_gate_config.py tests/test_integration_gate_probes.py tests/test_integration_gate_live_cases.py tests/test_integration_gate.py tests/test_entrypoints.py
python -m ruff format --check scripts/gates scripts/offline_gate scripts/integration_gate scripts/release_gate.py tests/test_gate_kernel.py tests/test_release_gate.py tests/test_integration_gate_config.py tests/test_integration_gate_probes.py tests/test_integration_gate_live_cases.py tests/test_integration_gate.py tests/test_entrypoints.py
```

Expected: both commands exit `0`.

- [ ] **Step 7: Run the full automated suite**

Run:

```powershell
python -m pytest -q
```

Expected: all repository tests pass.

- [ ] **Step 8: Run the deterministic offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: `[PASS] offline release gate` with all required suites, including `quality_eval`.

- [ ] **Step 9: Run repository hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: all hooks pass. If Ruff modifies files, inspect the diff and repeat Steps 4-9.

- [ ] **Step 10: Run the real integration gate only when dependencies are available**

Run:

```powershell
graph-rag-integration-gate --json
```

Expected with a prepared environment: exit `0`, all three dependency probes pass, all three live
cases execute, vector and graph coverage are proven, model tokens are positive, and report paths
point under `eval/reports/integration_gate/`.

If services or provider credentials are unavailable, do not claim this check passed. Record it as
not run and report that limitation in the delivery summary.

- [ ] **Step 11: Commit documentation and verification updates**

```powershell
git add README.md docs/offline_evaluation_release_gate.md docs/real_dependency_integration_gate.md tests/test_release_gate.py
git commit -m "docs: document two-layer release quality gates"
```

## Plan Self-Review

- Spec coverage: Tasks 1-2 cover the shared kernel and compatibility deletion; Tasks 3-6 cover
  strict configuration, probes, live provider/dependency proof, evaluation, reports, and CLI; Task 7
  covers operations, security audit, offline preservation, and honest live verification.
- Scope: one coherent delivery produces a separately runnable, testable integration gate while
  preserving the offline gate's role. No Docker lifecycle or data provisioning is added.
- Type consistency: all tasks use `GateCheckResult`, `GateFailureType`, `IntegrationGatePolicy`,
  `IntegrationGateSettings`, and `LiveCaseObservation` with the signatures introduced earlier.
- Compatibility: the plan deletes retired switches, environment variables, policy branches,
  exports, summary fields, and tests. It introduces no aliases or deprecation shims.
