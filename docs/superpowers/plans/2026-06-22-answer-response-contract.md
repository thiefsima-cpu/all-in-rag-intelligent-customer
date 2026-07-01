# Answer Response Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tighten `/answers` and SSE `result` response schemas so grounding, diagnostics, and traces use stable Pydantic contracts instead of broad `JsonObject` fields.

**Architecture:** Keep the application workflow unchanged and make the FastAPI response model the strict boundary. Add nested Pydantic models in `rag_modules/interfaces/api/models.py` that mirror existing runtime dataclass `to_dict()` shapes, while preserving intentionally open-ended metadata and detail payloads as JSON maps.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, existing runtime dataclasses, pytest, Ruff/pre-commit.

---

## File Structure

- Modify: `tests/test_api_app.py` - expand the fake answer response to runtime-shaped payloads and add focused model strictness tests.
- Modify: `rag_modules/interfaces/api/models.py` - add answer response sub-models for retrieval grounding, query diagnostics, route/graph/generation traces, query trace events, and summary token/cost fields.
- Optional verify only: `rag_modules/interfaces/api/response_builder.py` - no code change expected; existing `build_answer_response()` and `AnswerStreamEventModel.result()` already validate through `AnswerPayloadModel`.

### Task 1: Lock Answer Response Contract Tests

**Files:**
- Modify: `tests/test_api_app.py`

- [ ] **Step 1: Add test imports for model validation and runtime payload builders**

In `tests/test_api_app.py`, replace:

```python
from rag_modules.interfaces.api.models import MAX_QUESTION_CHARS, AnswerStreamEventType
```

with:

```python
from pydantic import ValidationError

from rag_modules.interfaces.api.models import (
    MAX_QUESTION_CHARS,
    AnswerResponseModel,
    AnswerStreamEventType,
)
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteResolution,
    RouteSnapshot,
)
```

- [ ] **Step 2: Add a runtime-shaped answer payload helper**

In `tests/test_api_app.py`, insert this helper after `_diagnostics(...)` and before `_DummyAnswerResponse`:

```python
def _answer_payload(question: str, *, stream: bool = False) -> dict:
    route_trace = RouteSnapshot(
        query=question,
        strategy="hybrid_traditional",
        requested_top_k=5,
        total_latency_ms=3.5,
        final_doc_count=1,
    )
    evidence_document = EvidenceDocument(
        content="Mapo tofu is a tofu dish.",
        recipe_name="mapo tofu",
        score=0.93,
        search_type="hybrid",
        search_method="vector",
        source="vector",
        route_strategy="hybrid_traditional",
    )
    retrieval = RetrievalOutcome(
        query=question,
        strategy="hybrid_traditional",
        evidence_documents=[evidence_document],
        route_trace=route_trace,
    )
    analysis = QueryAnalysis(
        query_complexity=0.2,
        relationship_intensity=0.1,
        recommended_strategy="hybrid_traditional",
        confidence=0.8,
        reasoning="simple factual cooking question",
    )
    answer_context = AnswerContext(
        question=question,
        retrieval=retrieval,
        analysis=analysis,
        metadata={"stream": stream},
    )
    route_resolution = RouteResolution(
        retrieval=retrieval,
        metadata={"route_strategy": "hybrid_traditional"},
    )
    graph_trace = GraphRetrievalSnapshot()
    generation_trace = GenerationSnapshot(
        status="success",
        mode="direct",
        total_evidence_items=1,
        selected_evidence_items=1,
        total_latency_ms=4.2,
        provider_latency_ms=2.7,
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        estimated_cost_usd=0.001,
        token_usage_source="test",
    )
    diagnostics = QueryDiagnostics(
        retrieval_bucket="ok",
        generation_bucket="ok",
        overall_bucket="ok",
    )
    trace_event = QueryTraceEvent(
        query_id="trace-test",
        timestamp=1,
        query=question,
        strategy="hybrid_traditional",
        latency_ms=12.3,
        retrieval=RetrievalTraceSnapshot(
            doc_count=1,
            evidence=[evidence_document.to_dict()],
            route_trace=route_trace,
            graph_trace=graph_trace,
        ),
        generation=generation_trace,
        diagnostics=diagnostics,
    )

    return {
        "summary": {
            "answer": f"answer:{question}",
            "status": "success",
            "strategy": "hybrid_traditional",
            "latency_ms": 12.3,
            "doc_count": 1,
            "has_evidence": True,
            "fallback_used": False,
            "failure_code": "",
            "provider_latency_ms": generation_trace.provider_latency_ms,
            "prompt_tokens": generation_trace.prompt_tokens,
            "completion_tokens": generation_trace.completion_tokens,
            "total_tokens": generation_trace.total_tokens,
            "estimated_cost_usd": generation_trace.estimated_cost_usd,
            "token_usage_source": generation_trace.token_usage_source,
            "error": "",
        },
        "grounding": {
            "retrieval_outcome": retrieval.to_dict(),
            "answer_context": answer_context.to_dict(),
            "route_resolution": route_resolution.to_dict(),
            "evidence_documents": [evidence_document.to_dict()],
        },
        "diagnostics": {
            "analysis": analysis.to_dict(),
            "diagnostics": diagnostics.to_dict(),
        },
        "traces": {
            "route_trace": route_trace.to_dict(),
            "graph_trace": graph_trace.to_dict(),
            "generation_trace": generation_trace.to_dict(),
            "trace_event": trace_event.to_dict(),
        },
    }
```

- [ ] **Step 3: Update the fake answer response to use the helper**

In `_DummyAnswerResponse.to_dict()`, replace the entire returned dictionary with:

```python
        return _answer_payload(self.question, stream=self.stream)
```

The method becomes:

```python
    def to_dict(self) -> dict:
        return _answer_payload(self.question, stream=self.stream)
```

- [ ] **Step 4: Add focused Pydantic strictness tests**

In the `ApiAppTests` class in `tests/test_api_app.py`, add these tests after `test_answer_flow_uses_serving_api_surface`:

```python
    def test_answer_response_model_accepts_runtime_shaped_payload(self) -> None:
        payload = _answer_payload("Can I cook tofu?")

        model = AnswerResponseModel.model_validate({"response": payload})

        dumped = model.model_dump()
        self.assertEqual(dumped["response"]["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(dumped["response"]["summary"]["prompt_tokens"], 11)
        self.assertEqual(
            dumped["response"]["grounding"]["retrieval_outcome"]["evidence_documents"][0][
                "recipe_name"
            ],
            "mapo tofu",
        )
        self.assertEqual(
            dumped["response"]["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(
            dumped["response"]["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_answer_response_model_rejects_unknown_stable_fields(self) -> None:
        payload = _answer_payload("Can I cook tofu?")
        payload["summary"]["unexpected"] = True

        with self.assertRaises(ValidationError):
            AnswerResponseModel.model_validate({"response": payload})

        payload = _answer_payload("Can I cook tofu?")
        payload["traces"]["generation_trace"]["unexpected"] = True

        with self.assertRaises(ValidationError):
            AnswerResponseModel.model_validate({"response": payload})

        payload = _answer_payload("Can I cook tofu?")
        payload["diagnostics"]["diagnostics"]["explained"] = True

        with self.assertRaises(ValidationError):
            AnswerResponseModel.model_validate({"response": payload})

    def test_answer_response_schema_exposes_summary_token_fields(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        summary_schema = schema["components"]["schemas"]["AnswerSummaryModel"]
        self.assertIn("prompt_tokens", summary_schema["properties"])
        self.assertIn("completion_tokens", summary_schema["properties"])
        self.assertIn("total_tokens", summary_schema["properties"])
        self.assertIn("estimated_cost_usd", summary_schema["properties"])
        self.assertIn("token_usage_source", summary_schema["properties"])
```

- [ ] **Step 5: Update answer flow assertions for the strict diagnostics shape**

In `test_answer_flow_uses_serving_api_surface`, replace:

```python
        self.assertTrue(answer_payload["diagnostics"]["diagnostics"]["explained"])
        self.assertFalse(answer_payload["diagnostics"]["diagnostics"]["stream"])
```

with:

```python
        self.assertEqual(
            answer_payload["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(answer_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(answer_payload["summary"]["total_tokens"], 18)
```

- [ ] **Step 6: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py::ApiAppTests::test_answer_response_model_accepts_runtime_shaped_payload tests/test_api_app.py::ApiAppTests::test_answer_response_model_rejects_unknown_stable_fields tests/test_api_app.py::ApiAppTests::test_answer_response_schema_exposes_summary_token_fields tests/test_api_app.py::ApiAppTests::test_answer_flow_uses_serving_api_surface -q
```

Expected: FAIL because `AnswerSummaryModel` does not yet expose token/cost fields, `diagnostics.diagnostics` still accepts arbitrary `JsonObject` keys, and nested trace models do not yet exist.

- [ ] **Step 7: Commit the failing tests**

Run:

```powershell
git add tests/test_api_app.py
git commit -m "test: lock answer response contract"
```

Expected: commit succeeds with only `tests/test_api_app.py` staged.

### Task 2: Add Strict Answer Response Pydantic Models

**Files:**
- Modify: `rag_modules/interfaces/api/models.py`

- [ ] **Step 1: Replace loose answer sub-models with runtime-shaped models**

In `rag_modules/interfaces/api/models.py`, replace the block from `class AnswerSummaryModel(BaseModel):` through the end of `class AnswerTracesModel(BaseModel):` with this code:

```python
class QueryAnalysisResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_complexity: float = 0.0
    relationship_intensity: float = 0.0
    reasoning_required: bool = False
    entity_count: int = 0
    recommended_strategy: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    semantic_profile: JsonObject = Field(default_factory=dict)


class EvidenceDocumentResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    node_id: str = ""
    recipe_name: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    recipe_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: list[str] = Field(default_factory=list)
    graph_evidence: JsonObject = Field(default_factory=dict)
    recipe_graph_evidence: JsonObject = Field(default_factory=dict)
    constraint_evidence: JsonObject = Field(default_factory=dict)
    evidence_units: list[JsonObject] = Field(default_factory=list)
    route_strategy: str = ""
    metadata: JsonObject = Field(default_factory=dict)


class RouteStageSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    latency_ms: float = 0.0
    doc_count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)


class RouteDiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_fallback: bool = False
    fallback_count: int = 0
    planner_used_cache: Optional[bool] = None
    graph_doc_count: int = 0
    hybrid_doc_count: int = 0
    post_process_doc_count: int = 0
    retrieval_degraded: bool = False
    degraded_sources: list[str] = Field(default_factory=list)
    degraded_candidates: list[JsonObject] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = Field(default_factory=list)


class RouteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    requested_top_k: int = 0
    retrieval_request: JsonObject = Field(default_factory=dict)
    stages: dict[str, RouteStageSnapshotResponseModel] = Field(default_factory=dict)
    fallbacks: list[str] = Field(default_factory=list)
    diagnostics: RouteDiagnosticsResponseModel = Field(
        default_factory=RouteDiagnosticsResponseModel
    )
    total_latency_ms: float = 0.0
    final_doc_count: int = 0
    error: str = ""


class RetrievalOutcomeResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    doc_count: int = 0
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    degradation_summary: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class QueryUnderstandingSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    query_plan: JsonObject = Field(default_factory=dict)
    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    constraints: JsonObject = Field(default_factory=dict)
    semantic_profile: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class RouteResolutionResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understanding: QueryUnderstandingSnapshotResponseModel = Field(
        default_factory=QueryUnderstandingSnapshotResponseModel
    )
    retrieval: RetrievalOutcomeResponseModel = Field(default_factory=RetrievalOutcomeResponseModel)
    metadata: JsonObject = Field(default_factory=dict)


class AnswerContextResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = ""
    retrieval: RetrievalOutcomeResponseModel = Field(default_factory=RetrievalOutcomeResponseModel)
    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    understanding: QueryUnderstandingSnapshotResponseModel = Field(
        default_factory=QueryUnderstandingSnapshotResponseModel
    )
    evidence_package: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class QueryDiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_bucket: str = ""
    generation_bucket: str = ""
    overall_bucket: str = ""
    retrieval_degraded: bool = False
    degraded_sources: list[str] = Field(default_factory=list)
    degraded_candidates: list[JsonObject] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = Field(default_factory=list)


class GraphTraceEventSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    details: JsonObject = Field(default_factory=dict)


class GraphRetrievalSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = "graph_rag"
    requested_top_k: int = 0
    retrieval_request: JsonObject = Field(default_factory=dict)
    query_type: str = ""
    source_entities: list[str] = Field(default_factory=list)
    target_entities: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    path_count: int = 0
    subgraph_count: int = 0
    reasoning_patterns: list[str] = Field(default_factory=list)
    reasoning_chain_count: int = 0
    evidence_unit_count: int = 0
    doc_count: int = 0
    retrieval_plan: JsonObject = Field(default_factory=dict)
    events: list[GraphTraceEventSnapshotResponseModel] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    error: str = ""


class GenerationSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    mode: str = ""
    decision_reason: str = ""
    total_evidence_items: int = 0
    selected_evidence_items: int = 0
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    failure_code: str = ""
    total_latency_ms: float = 0.0
    provider_latency_ms: float = 0.0
    request_retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""


class ModelSuiteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: str = ""
    embedding: str = ""
    rerank: str = ""


class RetrievalTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_count: int = 0
    evidence: list[JsonObject] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    failure_reasons: list[str] = Field(default_factory=list)


class AnswerTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chars: int = 0
    preview: str = ""


class QueryTraceEventResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = ""
    timestamp: int = 0
    query: str = ""
    strategy: Optional[str] = None
    latency_ms: float = 0.0
    plan: JsonObject = Field(default_factory=dict)
    models: ModelSuiteSnapshotResponseModel = Field(default_factory=ModelSuiteSnapshotResponseModel)
    retrieval: RetrievalTraceSnapshotResponseModel = Field(
        default_factory=RetrievalTraceSnapshotResponseModel
    )
    generation: GenerationSnapshotResponseModel = Field(
        default_factory=GenerationSnapshotResponseModel
    )
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
    )
    answer: AnswerTraceSnapshotResponseModel = Field(
        default_factory=AnswerTraceSnapshotResponseModel
    )
    error: str = ""


class AnswerSummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    status: str = "success"
    strategy: str = ""
    latency_ms: float = 0.0
    doc_count: int = 0
    has_evidence: bool = False
    fallback_used: bool = False
    failure_code: str = ""
    provider_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""
    error: str = ""


class AnswerGroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_outcome: RetrievalOutcomeResponseModel = Field(
        default_factory=RetrievalOutcomeResponseModel
    )
    answer_context: AnswerContextResponseModel = Field(default_factory=AnswerContextResponseModel)
    route_resolution: RouteResolutionResponseModel = Field(
        default_factory=RouteResolutionResponseModel
    )
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)


class AnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
    )


class AnswerTracesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    generation_trace: GenerationSnapshotResponseModel = Field(
        default_factory=GenerationSnapshotResponseModel
    )
    trace_event: QueryTraceEventResponseModel = Field(default_factory=QueryTraceEventResponseModel)
```

- [ ] **Step 2: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py::ApiAppTests::test_answer_response_model_accepts_runtime_shaped_payload tests/test_api_app.py::ApiAppTests::test_answer_response_model_rejects_unknown_stable_fields tests/test_api_app.py::ApiAppTests::test_answer_response_schema_exposes_summary_token_fields tests/test_api_app.py::ApiAppTests::test_answer_flow_uses_serving_api_surface -q
```

Expected: PASS.

- [ ] **Step 3: Run all API app tests**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit the model implementation**

Run:

```powershell
git add rag_modules/interfaces/api/models.py tests/test_api_app.py
git commit -m "feat: tighten answer response schema"
```

Expected: commit succeeds with the API model and test changes staged.

### Task 3: Verify SSE Result Contract And OpenAPI Shape

**Files:**
- Modify: `tests/test_api_app.py`

- [ ] **Step 1: Add an SSE result assertion for strict trace fields**

In `test_answer_stream_uses_sse_surface`, after the existing result answer assertion:

```python
        self.assertEqual(
            events["result"][0]["response"]["summary"]["answer"],
            "answer:Can I cook tofu?",
        )
```

add:

```python
        result_payload = events["result"][0]["response"]
        self.assertEqual(result_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(
            result_payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )
        self.assertEqual(
            result_payload["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
```

- [ ] **Step 2: Add an OpenAPI assertion for nested answer trace models**

In `test_explicit_answer_stream_route_uses_sse_surface`, after:

```python
        self.assertIn("/answers/stream", schema["paths"])
```

add:

```python
        schemas = schema["components"]["schemas"]
        self.assertIn("GenerationSnapshotResponseModel", schemas)
        self.assertIn("QueryTraceEventResponseModel", schemas)
        generation_schema = schemas["GenerationSnapshotResponseModel"]
        self.assertIn("token_usage_source", generation_schema["properties"])
        trace_event_schema = schemas["QueryTraceEventResponseModel"]
        self.assertIn("diagnostics", trace_event_schema["properties"])
```

- [ ] **Step 3: Run the SSE-focused tests**

Run:

```powershell
python -m pytest tests/test_api_app.py::ApiAppTests::test_answer_stream_uses_sse_surface tests/test_api_app.py::ApiAppTests::test_explicit_answer_stream_route_uses_sse_surface -q
```

Expected: PASS.

- [ ] **Step 4: Run the full API test file again**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the SSE/OpenAPI assertions**

Run:

```powershell
git add tests/test_api_app.py
git commit -m "test: verify streamed answer response schema"
```

Expected: commit succeeds with only `tests/test_api_app.py` staged.

### Task 4: Final Verification And Cleanup

**Files:**
- Verify: `rag_modules/interfaces/api/models.py`
- Verify: `tests/test_api_app.py`

- [ ] **Step 1: Run the narrow behavior test**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Ruff on touched Python files**

Run:

```powershell
python -m ruff check rag_modules/interfaces/api/models.py tests/test_api_app.py
```

Expected: PASS. If the environment reports `No module named ruff`, record that exact output and run `pre-commit run --all-files` only if the repository environment has pre-commit available.

- [ ] **Step 3: Run the repository hook gate when available**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If the command modifies files, inspect `git diff` and rerun the relevant test command from Step 1.

- [ ] **Step 4: Check git status**

Run:

```powershell
git status --short
```

Expected: no unstaged implementation changes. If verification tools changed formatting, stage and commit those formatting changes with:

```powershell
git add rag_modules/interfaces/api/models.py tests/test_api_app.py
git commit -m "chore: format answer response schema changes"
```

## Self-Review

- Spec coverage: Task 1 covers focused tests, runtime-shaped fake payloads, rejected unknown stable fields, and summary token/cost schema. Task 2 covers strict Pydantic answer grounding, diagnostics, traces, and shared JSON-shaped metadata/detail fields. Task 3 covers the shared SSE `result` contract and OpenAPI nested model exposure. Task 4 covers the requested final verification.
- Placeholder scan: The plan contains no incomplete steps or deferred implementation notes. Python ellipses are not used in code snippets.
- Type consistency: The Pydantic model names match the approved design, and later tests assert fields defined by the Task 2 model block.
