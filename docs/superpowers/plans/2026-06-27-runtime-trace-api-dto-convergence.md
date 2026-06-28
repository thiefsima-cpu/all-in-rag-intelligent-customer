# Runtime, Trace, and Answer API DTO Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep stable answer runtime and trace objects typed until they are explicitly mapped into the FastAPI response schema, without changing public JSON.

**Architecture:** Runtime and trace dataclasses retain domain state and use `JsonObject` only for intentionally dynamic JSON. Application answer response groups hold those DTOs directly. The API layer maps the application response into Pydantic models through explicit `from_dto()` constructors shared by ordinary and SSE responses; `to_dict()` remains only as a compatibility/final-serialization path.

**Tech Stack:** Python 3.11, dataclasses, Pydantic v2, FastAPI, unittest/pytest, mypy, Ruff, pre-commit.

---

## File Structure

- `rag_modules/runtime/json_types.py`: shared recursive JSON aliases and coercion helpers.
- `rag_modules/runtime/generation_models.py`: typed generation snapshot serialization.
- `rag_modules/runtime/graph_models.py`: typed graph snapshot and event detail JSON.
- `rag_modules/runtime/route_models.py`: typed route stage details and degradation diagnostics.
- `rag_modules/runtime/retrieval_models.py`: typed retrieval metadata and degradation summary.
- `rag_modules/runtime/workflow_models.py`: typed workflow metadata and evidence-package JSON.
- `rag_modules/runtime/trace_models.py`: typed query trace plan, evidence, and diagnostics.
- `rag_modules/app/services/answer_models.py`: typed application response groups.
- `rag_modules/interfaces/api/answer_models.py`: explicit runtime/application DTO to Pydantic mapping.
- `rag_modules/interfaces/api/response_builder.py`: typed response wrapper construction.
- `rag_modules/interfaces/api/services/serving.py`: ordinary and SSE mapping entry points.
- `tests/test_type_contract_ratchets.py`: prevents explicit `Any` from returning to the vertical slice.
- `tests/test_runtime_snapshot_utils.py`: leaf snapshot behavior and JSON compatibility.
- `tests/test_runtime_retrieval_models.py`: route/retrieval JSON compatibility.
- `tests/test_runtime_workflow_models.py`: workflow JSON compatibility.
- `tests/test_query_tracer.py`: query trace persistence compatibility.
- `tests/test_answer_workflow.py`: application response DTO behavior and compatibility.
- `tests/test_answer_response_mapping.py`: focused API mapper contract tests.
- `tests/test_api_app.py`: HTTP and SSE integration tests.

### Task 1: Tighten generation and graph snapshot JSON contracts

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `rag_modules/runtime/json_types.py`
- Modify: `rag_modules/runtime/generation_models.py`
- Modify: `rag_modules/runtime/graph_models.py`
- Test: `tests/test_runtime_snapshot_utils.py`
- Test: `tests/test_graph_retrieval_executor.py`

- [ ] **Step 1: Add leaf runtime modules to the no-`Any` ratchet**

Add these paths to `NO_EXPLICIT_ANY_TARGETS`:

```python
ROOT / "rag_modules" / "runtime" / "generation_models.py",
ROOT / "rag_modules" / "runtime" / "graph_models.py",
```

- [ ] **Step 2: Run the ratchet and verify the expected failure**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py -q
```

Expected: FAIL listing explicit `Any` occurrences in both newly added runtime files.

- [ ] **Step 3: Replace dynamic generation deserialization with an explicit DTO constructor**

In `generation_models.py`, import `JsonObject`, accept `Mapping[str, object]`, return
`JsonObject`, and replace the dynamic `cls(**filtered_payload)` call with an explicit constructor:

```python
from .json_types import JsonObject, coerce_json_float, coerce_json_int

@classmethod
def from_dict(cls, data: Mapping[str, object] | None) -> "GenerationSnapshot":
    payload = dict(data or {})
    return cls(
        status=str(payload.get("status") or ""),
        mode=str(payload.get("mode") or ""),
        decision_reason=str(payload.get("decision_reason") or ""),
        total_evidence_items=coerce_json_int(payload.get("total_evidence_items")),
        selected_evidence_items=coerce_json_int(payload.get("selected_evidence_items")),
        plan_latency_ms=coerce_json_float(payload.get("plan_latency_ms")),
        compose_latency_ms=coerce_json_float(payload.get("compose_latency_ms")),
        direct_latency_ms=coerce_json_float(payload.get("direct_latency_ms")),
        fallback_used=bool(payload.get("fallback_used")),
        fallback_reason=str(payload.get("fallback_reason") or ""),
        failure_code=str(payload.get("failure_code") or ""),
        total_latency_ms=coerce_json_float(payload.get("total_latency_ms")),
        provider_latency_ms=coerce_json_float(payload.get("provider_latency_ms")),
        request_retries=coerce_json_int(payload.get("request_retries")),
        prompt_tokens=coerce_json_int(payload.get("prompt_tokens")),
        completion_tokens=coerce_json_int(payload.get("completion_tokens")),
        total_tokens=coerce_json_int(payload.get("total_tokens")),
        estimated_cost_usd=coerce_json_float(payload.get("estimated_cost_usd")),
        token_usage_source=str(payload.get("token_usage_source") or ""),
    )

def to_dict(self) -> JsonObject:
    return {
        "status": self.status,
        "mode": self.mode,
        "decision_reason": self.decision_reason,
        "total_evidence_items": self.total_evidence_items,
        "selected_evidence_items": self.selected_evidence_items,
        "plan_latency_ms": self.plan_latency_ms,
        "compose_latency_ms": self.compose_latency_ms,
        "direct_latency_ms": self.direct_latency_ms,
        "fallback_used": self.fallback_used,
        "fallback_reason": self.fallback_reason,
        "failure_code": self.failure_code,
        "total_latency_ms": self.total_latency_ms,
        "provider_latency_ms": self.provider_latency_ms,
        "request_retries": self.request_retries,
        "prompt_tokens": self.prompt_tokens,
        "completion_tokens": self.completion_tokens,
        "total_tokens": self.total_tokens,
        "estimated_cost_usd": self.estimated_cost_usd,
        "token_usage_source": self.token_usage_source,
}
```

Add and export the shared scalar coercers in `json_types.py`:

```python
def coerce_json_int(value: object, default: int = 0) -> int:
    if isinstance(value, (bool, int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
    return default


def coerce_json_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, (bool, int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default
    return default
```

Include both names in `json_types.__all__`.

- [ ] **Step 4: Replace graph dynamic dictionaries with JSON aliases**

In `graph_models.py`, use these exact public annotations and signatures:

Set `GraphTraceEventSnapshot.details` and `GraphRetrievalSnapshot.retrieval_plan` to
`JsonObject`. Change both `from_dict` inputs to `Mapping[str, object] | None`; change
`GraphTraceEventSnapshot.to_dict`, `GraphRetrievalSnapshot.to_stage_details`, and
`GraphRetrievalSnapshot.to_dict` to return `JsonObject`; change the `details` parameter of
`add_event` to accept `JsonObject | None`.

Use `coerce_json_object(payload.get("details"))` and
`coerce_json_object(payload.get("retrieval_plan"))` at input boundaries. Normalize list inputs
with an `isinstance(value, list)` guard before iterating. Preserve every existing output key and
use `coerce_json_int`/`coerce_json_float` for numeric values read from `payload`.

- [ ] **Step 5: Run leaf snapshot tests and the ratchet**

Run:

```powershell
python -m pytest tests/test_runtime_snapshot_utils.py tests/test_graph_retrieval_executor.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the leaf contract change**

```powershell
git add rag_modules/runtime/json_types.py rag_modules/runtime/generation_models.py rag_modules/runtime/graph_models.py tests/test_type_contract_ratchets.py
git commit -m "refactor: type generation and graph snapshots"
```

### Task 2: Tighten route and retrieval JSON contracts

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `rag_modules/runtime/route_models.py`
- Modify: `rag_modules/runtime/retrieval_models.py`
- Test: `tests/test_runtime_retrieval_models.py`
- Test: `tests/test_route_trace_recorder.py`

- [ ] **Step 1: Extend the ratchet to route and retrieval models**

Add:

```python
ROOT / "rag_modules" / "runtime" / "retrieval_models.py",
ROOT / "rag_modules" / "runtime" / "route_models.py",
```

- [ ] **Step 2: Run the ratchet and verify it fails on the new targets**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py -q
```

Expected: FAIL listing `Any` in `route_models.py` and `retrieval_models.py` only.

- [ ] **Step 3: Type route stage details and degradation summaries**

Set `RouteStageSnapshot.details` to `JsonObject` and
`RouteDiagnostics.degraded_candidates` to `list[JsonObject]`. Change the `from_dict` inputs for
`RouteStageSnapshot`, `RouteDiagnostics`, and `RouteSnapshot` to
`Mapping[str, object] | None`. Change all three `to_dict` return types and
`_summarize_stage_degradation` to `JsonObject`. Change `RouteSnapshot.add_stage` to accept
`RouteStageSnapshot | Mapping[str, object]`, and change `_unique_strings` to accept
`Iterable[object]`.

Normalize details with `coerce_json_object`. Build degraded candidates with this checked pattern:

```python
raw_candidates = payload.get("degraded_candidates")
degraded_candidates = (
    [coerce_json_object(item) for item in raw_candidates]
    if isinstance(raw_candidates, list)
    else []
)
```

Use `coerce_json_int` and `coerce_json_float` for numeric mapping inputs. Preserve the current
stage names, fallback aggregation, circuit-breaker detection, and diagnostic defaults.

- [ ] **Step 4: Type retrieval metadata and degradation summaries**

Set `RetrievalOutcome.degradation_summary` and `RetrievalOutcome.metadata` to `JsonObject`.
Change `RetrievalOutcome.from_dict` to accept `Mapping[str, object] | None`; change
`RetrievalOutcome.to_dict`, `_route_degradation_summary`, and `_normalize_degradation_summary` to
return `JsonObject`; change `_normalize_degradation_summary` to accept `JsonObject`.

Normalize `metadata` and `degradation_summary` with `coerce_json_object`. Before mapping evidence,
guard the input with `isinstance(raw_evidence, list)`. Keep
`EvidenceDocument.from_dict` as the compatibility adapter for evidence mappings and do not broaden
this task into the retrieval contract package.

- [ ] **Step 5: Run focused route/retrieval tests**

Run:

```powershell
python -m pytest tests/test_runtime_retrieval_models.py tests/test_route_trace_recorder.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS with the existing degradation assertions unchanged.

- [ ] **Step 6: Commit route/retrieval typing**

```powershell
git add rag_modules/runtime/route_models.py rag_modules/runtime/retrieval_models.py tests/test_type_contract_ratchets.py
git commit -m "refactor: type route and retrieval payloads"
```

### Task 3: Tighten workflow and query trace JSON contracts

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `rag_modules/runtime/workflow_models.py`
- Modify: `rag_modules/runtime/trace_models.py`
- Test: `tests/test_runtime_workflow_models.py`
- Test: `tests/test_query_tracer.py`

- [ ] **Step 1: Add workflow and trace modules to the ratchet**

Add:

```python
ROOT / "rag_modules" / "runtime" / "trace_models.py",
ROOT / "rag_modules" / "runtime" / "workflow_models.py",
```

- [ ] **Step 2: Verify the new targets fail the ratchet**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py -q
```

Expected: FAIL listing explicit `Any` in the two new targets.

- [ ] **Step 3: Type workflow metadata and evidence packages**

Set `QueryUnderstandingSnapshot.metadata`, `RouteResolution.metadata`,
`AnswerContext.evidence_package`, and `AnswerContext.metadata` to `JsonObject`. Change
the `metadata` parameters of `QueryUnderstandingSnapshot.from_plan` and
`AnswerContext.from_route_resolution` to accept `JsonObject | None`. Change the
`evidence_package` parameter of `AnswerContext.from_route_resolution` and
`AnswerContext.with_evidence_package(payload)` to accept `object`; the latter implementation is:

```python
def with_evidence_package(self, payload: object) -> "AnswerContext":
    return replace(self, evidence_package=coerce_json_object(payload))
```

All three `from_dict` methods accept `Mapping[str, object] | None`; all three `to_dict` methods
return `JsonObject`. Keep the compatibility support for objects with `to_dict()` through
`coerce_json_object`, which is allowed here because this method is an explicit JSON adapter.

- [ ] **Step 4: Type query trace plans, evidence, and diagnostics**

Use these stable annotations:

```python
from .json_types import JsonObject, coerce_json_object

class QueryDiagnostics:
    degraded_candidates: list[JsonObject] = field(default_factory=list)

class RetrievalTraceSnapshot:
    evidence: list[JsonObject] = field(default_factory=list)

class QueryTraceEvent:
    plan: JsonObject = field(default_factory=dict)
```

Change every trace `from_dict` input to `Mapping[str, object] | None` and every trace `to_dict`
return type to `JsonObject`. Replace the dynamic `QueryTraceEvent(**filtered_payload)` with the
explicit construction below so the trace boundary is statically visible:

```python
return cls(
    query_id=str(payload.get("query_id") or ""),
    timestamp=coerce_json_int(payload.get("timestamp")),
    query=str(payload.get("query") or ""),
    strategy=(str(payload["strategy"]) if payload.get("strategy") is not None else None),
    latency_ms=coerce_json_float(payload.get("latency_ms")),
    plan=coerce_json_object(payload.get("plan")),
    models=ModelSuiteSnapshot.from_dict(_mapping_or_none(payload.get("models"))),
    retrieval=RetrievalTraceSnapshot.from_dict(_mapping_or_none(payload.get("retrieval"))),
    generation=GenerationSnapshot.from_dict(_mapping_or_none(payload.get("generation"))),
    diagnostics=QueryDiagnostics.from_dict(_mapping_or_none(payload.get("diagnostics"))),
    answer=AnswerTraceSnapshot.from_dict(_mapping_or_none(payload.get("answer"))),
    error=str(payload.get("error") or ""),
)
```

Define `_mapping_or_none(value: object) -> Mapping[str, object] | None` in the same module using an
`isinstance(value, Mapping)` guard. Preserve the persisted query trace key order and values.

- [ ] **Step 5: Run workflow and trace compatibility tests**

Run:

```powershell
python -m pytest tests/test_runtime_workflow_models.py tests/test_query_tracer.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS, including JSON serialization of `QueryTraceEvent.to_dict()`.

- [ ] **Step 6: Commit workflow/trace typing**

```powershell
git add rag_modules/runtime/workflow_models.py rag_modules/runtime/trace_models.py tests/test_type_contract_ratchets.py
git commit -m "refactor: type workflow and trace payloads"
```

### Task 4: Make application answer response groups hold DTOs

**Files:**
- Modify: `tests/test_answer_workflow.py`
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `rag_modules/app/services/answer_models.py`

- [ ] **Step 1: Write failing application response DTO tests**

Add this test beside the existing response-shape tests in `tests/test_answer_workflow.py`:

```python
def test_response_groups_preserve_typed_runtime_contracts(self) -> None:
    result = self.make_result("typed response")

    response = result.to_response()

    self.assertIs(response.grounding.retrieval_outcome, result.retrieval_outcome)
    self.assertIs(response.grounding.answer_context, result.answer_context)
    self.assertIs(response.grounding.route_resolution, result.route_resolution)
    self.assertEqual(response.grounding.evidence_documents, result.evidence_documents)
    self.assertIs(response.diagnostics.analysis, result.analysis)
    self.assertIs(response.diagnostics.diagnostics, result.trace_event.diagnostics)
    self.assertIs(response.traces.route_trace, result.route_trace)
    self.assertIs(response.traces.graph_trace, result.graph_trace)
    self.assertIs(response.traces.generation_trace, result.generation_trace)
    self.assertIs(response.traces.trace_event, result.trace_event)
```

Update typed accessor assertions from mapping access to DTO access:

```python
self.assertEqual(response.trace_event.query, question)
self.assertTrue(response.diagnostic_payload.retrieval_degraded)
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py::AnswerWorkflowTests::test_response_groups_preserve_typed_runtime_contracts -q
```

Expected: FAIL because the grouped fields currently contain dictionaries.

- [ ] **Step 3: Replace grouped dictionary fields with DTOs**

In `answer_models.py`, remove `Any`, `Dict`, and the `analysis_payload` import. Import `JsonObject`
and `QueryDiagnostics`. Define the grouped contracts as:

```python
@dataclass
class QuestionAnswerGrounding:
    retrieval_outcome: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    answer_context: AnswerContext = field(default_factory=AnswerContext)
    route_resolution: RouteResolution = field(default_factory=RouteResolution)
    evidence_documents: list[EvidenceDocument] = field(default_factory=list)

    def to_dict(self) -> JsonObject:
        return {
            "retrieval_outcome": self.retrieval_outcome.to_dict(),
            "answer_context": self.answer_context.to_dict(),
            "route_resolution": self.route_resolution.to_dict(),
            "evidence_documents": [item.to_dict() for item in self.evidence_documents],
        }


@dataclass
class QuestionAnswerDiagnostics:
    analysis: QueryAnalysis | None = None
    diagnostics: QueryDiagnostics = field(default_factory=QueryDiagnostics)

    def to_dict(self) -> JsonObject:
        return {
            "analysis": self.analysis.to_dict() if self.analysis else {},
            "diagnostics": self.diagnostics.to_dict(),
        }


@dataclass
class QuestionAnswerTraces:
    route_trace: RouteSnapshot = field(default_factory=RouteSnapshot)
    graph_trace: GraphRetrievalSnapshot = field(default_factory=GraphRetrievalSnapshot)
    generation_trace: GenerationSnapshot = field(default_factory=GenerationSnapshot)
    trace_event: QueryTraceEvent = field(default_factory=QueryTraceEvent)

    def to_dict(self) -> JsonObject:
        return {
            "route_trace": self.route_trace.to_dict(),
            "graph_trace": self.graph_trace.to_dict(),
            "generation_trace": self.generation_trace.to_dict(),
            "trace_event": self.trace_event.to_dict(),
        }
```

Construct them in `QuestionAnswerResponse.from_result()` from the existing objects, with
`diagnostics=result.trace_event.diagnostics`. Change compatibility accessors to return the typed
objects, including `analysis: QueryAnalysis | None`, `diagnostic_payload: QueryDiagnostics`, and
`trace_event: QueryTraceEvent`. Change all serializers in this file to return `JsonObject`.

- [ ] **Step 4: Add the application response module to the ratchet**

Add:

```python
ROOT / "rag_modules" / "app" / "services" / "answer_models.py",
```

- [ ] **Step 5: Run application workflow and ratchet tests**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS, including the existing `result.to_dict() == response.to_dict()` compatibility
assertion.

- [ ] **Step 6: Commit the typed application response**

```powershell
git add rag_modules/app/services/answer_models.py tests/test_answer_workflow.py tests/test_type_contract_ratchets.py
git commit -m "refactor: preserve DTOs in answer responses"
```

### Task 5: Add explicit DTO-to-Pydantic answer mapping

**Files:**
- Create: `tests/test_answer_response_mapping.py`
- Modify: `rag_modules/interfaces/api/answer_models.py`

- [ ] **Step 1: Write a failing mapper test that forbids `to_dict()` handoffs**

Create `tests/test_answer_response_mapping.py` with a complete `QuestionAnswerResult` fixture and
this core assertion:

```python
from contextlib import ExitStack
from unittest.mock import patch

from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.interfaces.api.answer_models import AnswerPayloadModel
from rag_modules.query_understanding import QueryPlan, QuerySemanticProfile
from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteResolution,
    RouteSnapshot,
)


def test_answer_payload_maps_typed_response_without_to_dict() -> None:
    response = _complete_result().to_response()
    blocked_types = (
        AnswerContext,
        EvidenceDocument,
        GenerationSnapshot,
        GraphRetrievalSnapshot,
        QueryAnalysis,
        QueryConstraints,
        QueryDiagnostics,
        QueryPlan,
        QuerySemanticProfile,
        QueryTraceEvent,
        RetrievalRequest,
        RetrievalOutcome,
        RouteResolution,
        RouteSnapshot,
    )

    with ExitStack() as stack:
        for dto_type in blocked_types:
            stack.enter_context(
                patch.object(dto_type, "to_dict", side_effect=AssertionError("DTO serialized"))
            )
        payload = AnswerPayloadModel.from_dto(response)

    assert payload.summary.answer == "grounded answer"
    assert payload.grounding.retrieval_outcome.strategy == "combined"
    assert payload.traces.generation_trace.total_tokens == 12
    assert payload.traces.trace_event.diagnostics.overall_bucket == "healthy"
```

Add a second test without patches:

```python
def test_typed_mapper_matches_compatibility_payload() -> None:
    response = _complete_result().to_response()

    assert AnswerPayloadModel.from_dto(response).model_dump() == response.to_dict()
```

The helper `_complete_result()` must include one evidence document, one route stage, one graph
event, a retrieval request with a query plan, non-empty generation usage, diagnostics, and trace
answer preview so all nested mappers are exercised. Its expected answer is `"grounded answer"`,
retrieval strategy is `"combined"`, generation total tokens is `12`, and diagnostics overall bucket
is `"healthy"`, matching the assertions above.

- [ ] **Step 2: Run the mapper test and verify the missing API failure**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py -q
```

Expected: FAIL because `AnswerPayloadModel.from_dto` does not exist.

- [ ] **Step 3: Add explicit `from_dto()` constructors for grounding models**

In `answer_models.py`, add typed constructors to:

- `QueryAnalysisResponseModel`
- `EvidenceDocumentResponseModel`
- `RouteStageSnapshotResponseModel`
- `RouteDiagnosticsResponseModel`
- `RouteSnapshotResponseModel`
- `RetrievalOutcomeResponseModel`
- `QueryUnderstandingSnapshotResponseModel`
- `RouteResolutionResponseModel`
- `AnswerContextResponseModel`

Before those classes, add explicit JSON projection helpers for nested runtime objects that the API
still intentionally exposes as `JsonObject`. The helpers must access fields, not call `to_dict()`:

```python
from ...app.services.answer_models import (
    QuestionAnswerDiagnostics,
    QuestionAnswerGrounding,
    QuestionAnswerResponse,
    QuestionAnswerSummary,
    QuestionAnswerTraces,
)
from ...domain.shared.query_constraints import QueryConstraints
from ...query_understanding import QueryPlan, QuerySemanticProfile, QuerySemanticScoreBreakdown
from ...retrieval.contracts import EvidenceDocument, RetrievalRequest
from ...runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    GraphTraceEventSnapshot,
    ModelSuiteSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    QueryUnderstandingSnapshot,
    RetrievalTraceSnapshot,
    RetrievalOutcome,
    RouteDiagnostics,
    RouteResolution,
    RouteSnapshot,
    RouteStageSnapshot,
)
from ...runtime.json_types import JsonObject, coerce_json_object
```

```python
def _constraints_payload(value: QueryConstraints) -> JsonObject:
    return {
        "include_terms": list(value.include_terms),
        "exclude_terms": list(value.exclude_terms),
        "ingredients": list(value.ingredients),
        "excluded_ingredients": list(value.excluded_ingredients),
        "cuisine_terms": list(value.cuisine_terms),
        "excluded_cuisine_terms": list(value.excluded_cuisine_terms),
        "category_terms": list(value.category_terms),
        "health_terms": list(value.health_terms),
        "preference_terms": list(value.preference_terms),
        "time": {
            "max_total_minutes": value.max_total_minutes,
            "max_prep_minutes": value.max_prep_minutes,
            "max_cook_minutes": value.max_cook_minutes,
        },
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
    }


def _score_breakdown_payload(value: QuerySemanticScoreBreakdown) -> JsonObject:
    return {
        "relation_hit_count": value.relation_hit_count,
        "constraint_hit_count": value.constraint_hit_count,
        "structural_hit_count": value.structural_hit_count,
        "fast_rule_hit_count": value.fast_rule_hit_count,
        "length_factor": value.length_factor,
        "lexical_relationship_intensity": value.lexical_relationship_intensity,
        "relation_hit_intensity_boost": value.relation_hit_intensity_boost,
        "lexical_complexity": value.lexical_complexity,
        "relation_hit_complexity_boost": value.relation_hit_complexity_boost,
        "relationship_intensity": value.relationship_intensity,
        "complexity": value.complexity,
    }


def _semantic_profile_payload(value: QuerySemanticProfile) -> JsonObject:
    return {
        "query": value.query,
        "query_type": value.query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "constraints": coerce_json_object(value.constraints),
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "recommendation_hits": list(value.recommendation_hits),
        "relation_hits": list(value.relation_hits),
        "constraint_hits": list(value.constraint_hits),
        "structural_hits": list(value.structural_hits),
        "fast_rule_hits": list(value.fast_rule_hits),
        "score_breakdown": _score_breakdown_payload(value.score_breakdown),
    }


def _query_plan_payload(value: QueryPlan) -> JsonObject:
    return {
        "query": value.query,
        "intent": value.intent,
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "strategy": value.strategy,
        "confidence": value.confidence,
        "reasoning": value.reasoning,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "graph_query_type": value.graph_query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "max_depth": value.max_depth,
        "constraints": _constraints_payload(value.constraints),
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "answer_style": value.answer_style,
        "planner_version": value.planner_version,
        "used_cache": value.used_cache,
        "fallback_reason": value.fallback_reason,
        "planner_mode": value.planner_mode,
        "semantic_profile": _semantic_profile_payload(value.semantic_profile),
        "validation_errors": list(value.validation_errors),
    }


def _retrieval_request_payload(value: RetrievalRequest | None) -> JsonObject:
    if value is None:
        return {}
    return {
        "query": value.query,
        "top_k": value.top_k,
        "candidate_k": value.candidate_k,
        "strategy": value.strategy,
        "constraints": _constraints_payload(value.effective_constraints),
        "query_plan": _query_plan_payload(value.query_plan) if value.query_plan else None,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "metadata": coerce_json_object(value.metadata),
    }
```

Each constructor must instantiate fields directly. The route mapper pattern is:

```python
@classmethod
def from_dto(cls, snapshot: RouteSnapshot) -> "RouteSnapshotResponseModel":
    return cls(
        query=snapshot.query,
        strategy=snapshot.strategy,
        requested_top_k=snapshot.requested_top_k,
        retrieval_request=_retrieval_request_payload(snapshot.retrieval_request),
        stages={
            name: RouteStageSnapshotResponseModel.from_dto(stage)
            for name, stage in snapshot.stages.items()
        },
        fallbacks=list(snapshot.fallbacks),
        diagnostics=RouteDiagnosticsResponseModel.from_dto(snapshot.diagnostics),
        total_latency_ms=snapshot.total_latency_ms,
        final_doc_count=snapshot.final_doc_count,
        error=snapshot.error,
    )
```

For dynamic JSON fields, use `coerce_json_object` directly on the field value. Do not call a DTO
`to_dict()`. Map every `EvidenceDocument` scalar and JSON field explicitly.

- [ ] **Step 4: Add explicit `from_dto()` constructors for trace models**

Add direct constructors to:

- `QueryDiagnosticsResponseModel`
- `GraphTraceEventSnapshotResponseModel`
- `GraphRetrievalSnapshotResponseModel`
- `GenerationSnapshotResponseModel`
- `ModelSuiteSnapshotResponseModel`
- `RetrievalTraceSnapshotResponseModel`
- `AnswerTraceSnapshotResponseModel`
- `QueryTraceEventResponseModel`

The query trace mapper must be structurally explicit:

```python
@classmethod
def from_dto(cls, event: QueryTraceEvent) -> "QueryTraceEventResponseModel":
    return cls(
        query_id=event.query_id,
        timestamp=event.timestamp,
        query=event.query,
        strategy=event.strategy,
        latency_ms=event.latency_ms,
        plan=coerce_json_object(event.plan),
        models=ModelSuiteSnapshotResponseModel.from_dto(event.models),
        retrieval=RetrievalTraceSnapshotResponseModel.from_dto(event.retrieval),
        generation=GenerationSnapshotResponseModel.from_dto(event.generation),
        diagnostics=QueryDiagnosticsResponseModel.from_dto(event.diagnostics),
        answer=AnswerTraceSnapshotResponseModel.from_dto(event.answer),
        error=event.error,
    )
```

- [ ] **Step 5: Add grouped application response mappers and the root entry point**

Add `from_dto()` to `AnswerSummaryModel`, `AnswerGroundingModel`, `AnswerDiagnosticsModel`,
`AnswerTracesModel`, and `AnswerPayloadModel`. The root method is:

```python
@classmethod
def from_dto(cls, response: QuestionAnswerResponse) -> "AnswerPayloadModel":
    return cls(
        summary=AnswerSummaryModel.from_dto(response.summary),
        grounding=AnswerGroundingModel.from_dto(response.grounding),
        diagnostics=AnswerDiagnosticsModel.from_dto(response.diagnostics),
        traces=AnswerTracesModel.from_dto(response.traces),
    )
```

Retain `from_payload()` as a compatibility adapter, but do not call it from the typed response path.

- [ ] **Step 6: Run mapper and schema tests**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS. The API service is not wired to the mapper until Task 6, so its current integration
behavior remains green at this commit boundary.

- [ ] **Step 7: Commit explicit API mapping**

```powershell
git add rag_modules/interfaces/api/answer_models.py tests/test_answer_response_mapping.py
git commit -m "refactor: map answer DTOs explicitly at API boundary"
```

### Task 6: Wire ordinary and SSE responses through the typed mapper

**Files:**
- Modify: `rag_modules/interfaces/api/answer_models.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Modify: `rag_modules/interfaces/api/response_builder.py`
- Modify: `tests/test_api_app.py`

- [ ] **Step 1: Add failing ordinary and SSE no-serialization integration tests**

Add a test that patches only the application compatibility serializer, allowing the API Pydantic
model to perform final JSON serialization:

```python
def test_answer_http_and_sse_paths_do_not_call_application_to_dict(self) -> None:
    with patch.object(
        QuestionAnswerResponse,
        "to_dict",
        side_effect=AssertionError("application response serialized internally"),
    ):
        answer_response = self.client.post("/answers", json={"question": "tofu"})
        stream_response = self.client.post(
            "/answers/stream",
            json={"question": "tofu"},
        )

    self.assertEqual(answer_response.status_code, 200)
    self.assertEqual(answer_response.json()["response"]["summary"]["answer"], "answer")
    self.assertEqual(stream_response.status_code, 200)
    self.assertIn("event: result", stream_response.text)
```

Use the existing authenticated client and fake answer fixture setup in `test_api_app.py`; preserve
its configured expected answer text rather than introducing a second fake application.

- [ ] **Step 2: Run the new integration test and verify it fails**

Run:

```powershell
python -m pytest tests/test_api_app.py -k "do_not_call_application_to_dict" -q
```

Expected: FAIL from `GraphRAGServingApiService.answer_question()` calling `response.to_dict()`.

- [ ] **Step 3: Map the ordinary response in the API service**

Change the serving method return type and final return:

```python
def answer_question(
    self,
    *,
    question: str,
    stream: bool = False,
    explain_routing: bool = False,
) -> AnswerPayloadModel:
    self._ensure_serving_runtime_initialized()
    self._refresh_serving_runtime_if_stale()
    self._raise_if_system_not_ready()
    with self._answer_admission.permit():
        with self._locks.answer_operation():
            self._raise_if_system_not_ready()
            response = self.system.answer_question_response(
                question=question,
                stream=stream,
                explain_routing=explain_routing,
            )
            return AnswerPayloadModel.from_dto(response)
```

Import `AnswerPayloadModel` from the adjacent answer model module.

- [ ] **Step 4: Map SSE results through the same root mapper**

Change `AnswerStreamEventModel.result` in `answer_models.py` to accept an already mapped payload:

```python
@classmethod
def result(cls, response: AnswerPayloadModel) -> "AnswerStreamEventModel":
    return cls(
        event=AnswerStreamEventType.result,
        data=AnswerStreamResultDataModel(response=response),
    )
```

Then replace the result emission in `serving.py` with:

```python
emit(AnswerStreamEventModel.result(AnswerPayloadModel.from_dto(response)))
```

Message, chunk, error, cancellation, backpressure, and done events remain unchanged.

- [ ] **Step 5: Make the response builder accept the typed payload**

Change:

```python
def build_answer_response(answer_payload: AnswerPayloadModel) -> AnswerResponseModel:
    return AnswerResponseModel(response=answer_payload)
```

Do not use `model_validate()` for this already typed object. The route function needs no structural
change because it already passes the service return value to `build_answer_response()`.

- [ ] **Step 6: Run API, mapper, and workflow tests**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_answer_workflow.py tests/test_api_app.py -q
```

Expected: PASS, including ordinary answer, compatibility `stream=true`, `/answers/stream`, unknown
stable-field rejection, and the new no-serialization test.

- [ ] **Step 7: Commit API wiring**

```powershell
git add rag_modules/interfaces/api/answer_models.py rag_modules/interfaces/api/services/serving.py rag_modules/interfaces/api/response_builder.py tests/test_api_app.py
git commit -m "refactor: keep answer responses typed through API"
```

### Task 7: Verify compatibility and repository gates

**Files:**
- Modify only if checks require formatting: files touched in Tasks 1-6

- [ ] **Step 1: Run all focused runtime and answer tests**

Run:

```powershell
python -m pytest tests/test_runtime_snapshot_utils.py tests/test_runtime_retrieval_models.py tests/test_runtime_workflow_models.py tests/test_query_tracer.py tests/test_answer_workflow.py tests/test_answer_response_mapping.py tests/test_api_app.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 2: Run mypy**

Run:

```powershell
python -m mypy
```

Expected: PASS with no new type errors. Fix errors by narrowing `object` with `isinstance`, explicit
scalar coercion, or `cast`; do not reintroduce `Any` in ratcheted files.

- [ ] **Step 3: Run repository hooks and inspect automatic changes**

Run:

```powershell
pre-commit run --all-files
git diff --check
git status --short
```

Expected: all hooks PASS and `git diff --check` reports no whitespace errors. If Ruff reformats a
file, rerun the focused tests from Step 1 before continuing.

- [ ] **Step 4: Run the release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS. If an environment-only integration dependency prevents completion, preserve the
exact command output and report the skipped check in the final handoff.

- [ ] **Step 5: Review the final diff for scope and JSON compatibility**

Run:

```powershell
git diff HEAD~4 --stat
git diff HEAD~4 -- rag_modules/runtime rag_modules/app/services/answer_models.py rag_modules/interfaces/api tests
```

Expected: changes are limited to the runtime/trace/answer API vertical slice and its tests; no
artifact metadata, configuration, or unrelated public surface changes appear.

- [ ] **Step 6: Commit any check-driven formatting fixes**

Only when Step 3 changed files:

```powershell
git add rag_modules tests
git commit -m "style: format typed answer response path"
```

If the worktree is already clean, do not create an empty commit.
