# Live Quality Interaction SLO Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make client-observed TTFT plus retrieval, rerank, generation, and
full-response p95 budgets release-blocking, then produce current real-model
development evidence for the 52-case `0.4.0.dev0` corpus.

**Architecture:** Execute every live-quality case once through
`/v1/debug/answers/stream`, measure TTFT and result arrival in the client, and
read stage timings from the final debug trace. Extend post-processing with an
explicit rerank outcome, aggregate strict timing metrics into a version 2 live
report, and make release-evidence v2 recompute and bind every blocking metric.

**Tech Stack:** Python 3.11, dataclasses, Pydantic v2, requests, FastAPI SSE,
pytest/unittest, Ruff, existing gate and release-evidence infrastructure.

## Global Constraints

- Keep Python compatibility at `>=3.11,<3.12`.
- Do not add runtime or development dependencies.
- Keep the canonical live corpus at exactly 52 cases, including the existing 5
  grounded customer-service cases.
- Use exactly one serving-model request per live-quality case.
- Define TTFT as request start through the first non-empty SSE `chunk`.
- Keep `generation_trace.first_token_latency_ms` diagnostic-only.
- Enforce p95 TTFT <= 5,000 ms, retrieval <= 3,000 ms, rerank <= 2,000 ms,
  generation <= 20,000 ms, and full response <= 25,000 ms.
- Treat missing timing observations and zero rerank coverage as failures, never
  as zero-valued successes.
- Keep lines within 100 characters and use Ruff's double-quote/import-order
  conventions.
- Do not write credentials, bearer tokens, raw exceptions, private absolute
  paths, or real customer data to reports or committed evidence.
- Preserve the historical version 1 `case_count=0` report as diagnostic history.
- Label the new `0.4.0.dev0` result as development diagnostic evidence, not
  protected-tag release evidence.

---

### Task 1: Record an Explicit Rerank Outcome

**Files:**

- Modify: `rag_modules/retrieval/post_processor.py`
- Modify: `rag_modules/routing/search_orchestrator.py`
- Test: `tests/test_model_client_ports.py`
- Test: `tests/test_route_search_orchestrator.py`

**Interfaces:**

- Produces:
  `RetrievalPostProcessResult(documents, rerank_attempted, rerank_succeeded,
  rerank_latency_ms)`.
- Produces:
  `RetrievalPostProcessor.post_process_with_trace(...) -> RetrievalPostProcessResult`.
- Preserves:
  `RetrievalPostProcessor.post_process(...) -> list[EvidenceDocument]`.
- Produces `post_process` route-stage details consumed by Task 2.

- [ ] **Step 1: Write failing tests for successful and failed rerank timing**

Add tests that patch `rag_modules.retrieval.post_processor.time.perf_counter` so
the values are deterministic:

```python
from unittest.mock import patch


def test_retrieval_post_processor_records_successful_rerank_timing(self) -> None:
    rerank_client = _FakeRerankClient(order=[1, 0])
    processor = RetrievalPostProcessor(
        settings=self.postprocess_settings,
        rerank_client=rerank_client,
    )
    docs = [
        EvidenceDocument(content="first", recipe_name="first"),
        EvidenceDocument(content="second", recipe_name="second"),
    ]

    with patch(
        "rag_modules.retrieval.post_processor.time.perf_counter",
        side_effect=[10.0, 10.125],
    ):
        outcome = processor.post_process_with_trace(
            docs,
            top_k=2,
            context=RetrievalPostProcessContext(
                query="which one",
                strategy="hybrid_traditional",
                query_complexity=0.1,
                relationship_intensity=0.1,
                route_confidence=0.9,
            ),
        )

    self.assertEqual([doc.recipe_name for doc in outcome.documents], ["second", "first"])
    self.assertTrue(outcome.rerank_attempted)
    self.assertTrue(outcome.rerank_succeeded)
    self.assertEqual(outcome.rerank_latency_ms, 125.0)


def test_retrieval_post_processor_records_failed_rerank_without_dropping_documents(
    self,
) -> None:
    rerank_client = _FailingRerankClient()
    processor = RetrievalPostProcessor(
        settings=self.postprocess_settings,
        rerank_client=rerank_client,
    )
    docs = [EvidenceDocument(content="first", recipe_name="first")]

    with patch(
        "rag_modules.retrieval.post_processor.time.perf_counter",
        side_effect=[20.0, 20.05],
    ):
        outcome = processor.post_process_with_trace(
            docs,
            top_k=1,
            context=RetrievalPostProcessContext(
                query="which one",
                strategy="hybrid_traditional",
                query_complexity=0.1,
                relationship_intensity=0.1,
                route_confidence=0.9,
            ),
        )

    self.assertEqual(list(outcome.documents), docs)
    self.assertTrue(outcome.rerank_attempted)
    self.assertFalse(outcome.rerank_succeeded)
    self.assertEqual(outcome.rerank_latency_ms, 50.0)
```

Add a no-client/no-document test asserting
`rerank_attempted=False`, `rerank_succeeded=False`, and
`rerank_latency_ms is None`. Keep the existing document-only test to prove the
compatibility wrapper still returns a list.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py -q
```

Expected: the new tests fail because `post_process_with_trace` and
`RetrievalPostProcessResult` do not exist.

- [ ] **Step 3: Add the traced post-process result and compatibility wrapper**

Add the following shape to `rag_modules/retrieval/post_processor.py`:

```python
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalPostProcessResult:
    documents: tuple[EvidenceDocument, ...]
    rerank_attempted: bool
    rerank_succeeded: bool
    rerank_latency_ms: float | None
```

Move the existing post-process body into `post_process_with_trace`. Make
`_rerank_documents` return
`tuple[list[EvidenceDocument], bool, bool, float | None]`. Start the monotonic
timer only when documents and a rerank client are present, and compute:

```python
rerank_started = time.perf_counter()
try:
    ordered_indices = self.rerank_client.rerank(...)
except Exception as exc:
    rerank_latency_ms = round((time.perf_counter() - rerank_started) * 1000, 2)
    log_failure(...)
    return documents, True, False, rerank_latency_ms
rerank_latency_ms = round((time.perf_counter() - rerank_started) * 1000, 2)
return reranked, True, True, rerank_latency_ms
```

Return the traced outcome after graph preservation and normalization:

```python
return RetrievalPostProcessResult(
    documents=tuple(normalized_docs),
    rerank_attempted=rerank_attempted,
    rerank_succeeded=rerank_succeeded,
    rerank_latency_ms=rerank_latency_ms,
)
```

Keep the original interface as:

```python
def post_process(
    self,
    evidence_documents: List[EvidenceDocument],
    top_k: int,
    context: RetrievalPostProcessContext,
) -> List[EvidenceDocument]:
    return list(
        self.post_process_with_trace(
            evidence_documents,
            top_k=top_k,
            context=context,
        ).documents
    )
```

- [ ] **Step 4: Write the failing route-stage degradation test**

Change `_FakePostProcessor` in `tests/test_route_search_orchestrator.py` to
provide `post_process_with_trace`, then add:

```python
def test_post_process_records_failed_rerank_as_retrieval_degradation(self) -> None:
    post_processor = _FakePostProcessor(
        rerank_attempted=True,
        rerank_succeeded=False,
        rerank_latency_ms=75.0,
    )
    orchestrator, request, trace = self._post_process_fixture(post_processor)

    orchestrator.post_process(
        request,
        [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")],
        trace=trace,
    )

    stage = trace.snapshot.stages["post_process"]
    self.assertEqual(stage.details["rerank_latency_ms"], 75.0)
    self.assertTrue(stage.details["rerank_attempted"])
    self.assertFalse(stage.details["rerank_succeeded"])
    self.assertTrue(stage.details["retrieval_degraded"])
    self.assertEqual(stage.details["degraded_sources"], ["rerank"])
    self.assertTrue(trace.snapshot.diagnostics.retrieval_degraded)
```

- [ ] **Step 5: Run the route test and verify RED**

Run:

```powershell
python -m pytest tests/test_route_search_orchestrator.py -q
```

Expected: the new stage-detail assertions fail because the orchestrator still
calls the list-only method and records no rerank details.

- [ ] **Step 6: Record rerank details in the route trace**

Update `RouteSearchOrchestrator.post_process` to call the traced method and
construct details exactly as follows:

```python
outcome = self.post_processor.post_process_with_trace(
    evidence_documents,
    top_k=request.top_k,
    context=RetrievalPostProcessContext(...),
)
details: JsonObject = {
    "rerank_attempted": outcome.rerank_attempted,
    "rerank_succeeded": outcome.rerank_succeeded,
    "rerank_latency_ms": outcome.rerank_latency_ms,
}
if outcome.rerank_attempted and not outcome.rerank_succeeded:
    details.update(
        {
            "retrieval_degraded": True,
            "degraded_sources": ["rerank"],
        }
    )
processed_documents = list(outcome.documents)
trace.add_stage(
    "post_process",
    start_time=post_start,
    documents=processed_documents,
    details=details,
)
return processed_documents
```

- [ ] **Step 7: Run both focused test files and verify GREEN**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py tests/test_route_search_orchestrator.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit Task 1**

```powershell
git add rag_modules/retrieval/post_processor.py `
  rag_modules/routing/search_orchestrator.py `
  tests/test_model_client_ports.py `
  tests/test_route_search_orchestrator.py
git commit -m "feat: trace live rerank latency"
```

---

### Task 2: Expose Rerank Timing Through the Debug API

**Files:**

- Modify: `rag_modules/interfaces/api/answer_debug_route_models.py`
- Test: `tests/test_answer_response_mapping.py`
- Test: `tests/test_api_answer.py`
- Test: `tests/test_api_sse.py`

**Interfaces:**

- Consumes Task 1 `post_process` stage details.
- Produces explicit `rerank_attempted`, `rerank_succeeded`, and
  `rerank_latency_ms` fields in `RouteStageSnapshotResponseModel`.
- Preserves public answer DTOs; only debug trace payloads gain these fields.

- [ ] **Step 1: Write the failing debug mapping test**

Extend the `post_process` fixture stage in
`tests/test_answer_response_mapping.py`:

```python
"post_process": RouteStageSnapshot(
    latency_ms=3.1,
    doc_count=1,
    sources={"vector": 1},
    details={
        "rerank_attempted": True,
        "rerank_succeeded": True,
        "rerank_latency_ms": 2.75,
    },
),
```

Assert:

```python
post_process = payload.traces.route_trace.stages["post_process"]
assert post_process.rerank_attempted is True
assert post_process.rerank_succeeded is True
assert post_process.rerank_latency_ms == 2.75
assert post_process.model_dump()["rerank_latency_ms"] == 2.75
```

Add one API response assertion to `tests/test_api_answer.py` and one debug SSE
result assertion to `tests/test_api_sse.py` proving the three fields survive
real response serialization.

- [ ] **Step 2: Run the mapping/API tests and verify RED**

Run:

```powershell
python -m pytest `
  tests/test_answer_response_mapping.py `
  tests/test_api_answer.py `
  tests/test_api_sse.py `
  -q
```

Expected: the new attributes/serialized keys are absent.

- [ ] **Step 3: Add explicit debug route-stage fields**

Add to `RouteStageSnapshotResponseModel`:

```python
rerank_attempted: bool = False
rerank_succeeded: bool = False
rerank_latency_ms: float | None = None
```

Map the stage details in `from_dto`:

```python
details = dict(stage.details or {})
raw_rerank_latency = details.get("rerank_latency_ms")
return cls(
    latency_ms=stage.latency_ms,
    doc_count=stage.doc_count,
    sources=dict(stage.sources),
    rerank_attempted=bool(details.get("rerank_attempted", False)),
    rerank_succeeded=bool(details.get("rerank_succeeded", False)),
    rerank_latency_ms=(
        float(raw_rerank_latency) if raw_rerank_latency is not None else None
    ),
    **public_degradation_payload(stage.details),
)
```

Keep `extra="allow"` for existing public degradation detail compatibility.

- [ ] **Step 4: Run the mapping/API tests and verify GREEN**

Run:

```powershell
python -m pytest `
  tests/test_answer_response_mapping.py `
  tests/test_api_answer.py `
  tests/test_api_sse.py `
  -q
```

Expected: all tests pass and both non-streaming and debug SSE traces expose the
new fields.

- [ ] **Step 5: Commit Task 2**

```powershell
git add rag_modules/interfaces/api/answer_debug_route_models.py `
  tests/test_answer_response_mapping.py `
  tests/test_api_answer.py `
  tests/test_api_sse.py
git commit -m "feat: expose rerank timing in debug traces"
```

---

### Task 3: Replace the Non-streaming Live Client With One Strict SSE Request

**Files:**

- Modify: `scripts/live_quality_gate/client.py`
- Modify: `scripts/live_quality_gate/runtime_models.py`
- Test: `tests/test_live_quality_gate_client.py`

**Interfaces:**

- Consumes `/v1/debug/answers/stream` SSE events and Task 2 trace fields.
- Produces timing-complete `LiveQualityObservation`.
- Preserves `run_live_case(...) -> LiveQualityCaseRunResult`.
- Produces structured `LIVE_QUALITY_REQUEST_FAILED` checks for transport,
  protocol, or trace-contract failures.

- [ ] **Step 1: Replace fake HTTP helpers with a streaming response fixture**

Change `FakeResponse` to expose `headers`, `iter_lines`, and `close`:

```python
class FakeResponse:
    def __init__(
        self,
        lines: list[str],
        *,
        content_type: str = "text/event-stream; charset=utf-8",
        error: Exception | None = None,
    ) -> None:
        self.lines = lines
        self.headers = {"content-type": content_type}
        self.error = error
        self.closed = False

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_lines(self, *, decode_unicode: bool) -> list[str]:
        assert decode_unicode is True
        return self.lines

    def close(self) -> None:
        self.closed = True
```

Add a canonical event helper:

```python
def sse_lines(*events: tuple[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for name, data in events:
        lines.extend(
            [
                f"event: {name}",
                f"data: {json.dumps(data, ensure_ascii=False)}",
                "",
            ]
        )
    return lines
```

Make `FakeSession.post` require `stream=True`.

- [ ] **Step 2: Write the failing happy-path TTFT test**

Update `answer_payload()` to include:

```python
"route_trace": {
    "strategy": "combined",
    "total_latency_ms": 850.0,
    "stages": {
        "hybrid": {"latency_ms": 500.0, "sources": {"vector": 2}},
        "post_process": {
            "latency_ms": 300.0,
            "sources": {"rerank": 1},
            "rerank_attempted": True,
            "rerank_succeeded": True,
            "rerank_latency_ms": 250.0,
        },
    },
    ...
},
"generation_trace": {
    ...
    "total_latency_ms": 4000.0,
    "first_token_latency_ms": 1200.0,
},
```

Use a deterministic clock:

```python
clock_values = iter([100.0, 101.25, 106.0])
response = FakeResponse(
    sse_lines(
        ("message", {"message": "Running query routing..."}),
        ("chunk", {"content": "Use tofu"}),
        ("result", answer_payload()),
        ("done", {"ok": True}),
    )
)
session = FakeSession(response)

result = run_live_case(
    settings=settings(),
    policy=policy(),
    case=case(),
    http_session=session,
    request_id_factory=lambda: "fixed-id",
    clock=lambda: next(clock_values),
)

assert result.checks == ()
assert result.observation is not None
assert result.observation.ttft_ms == 1250.0
assert result.observation.latency_ms == 6000.0
assert result.observation.retrieval_latency_ms == 850.0
assert result.observation.rerank_attempted is True
assert result.observation.rerank_succeeded is True
assert result.observation.rerank_latency_ms == 250.0
assert result.observation.generation_latency_ms == 4000.0
assert result.observation.generation_first_token_latency_ms == 1200.0
assert session.posts[0]["url"].endswith("/v1/debug/answers/stream")
assert session.posts[0]["json"] == {
    "question": "How do I make mapo tofu?",
    "explain_routing": True,
}
assert session.posts[0]["stream"] is True
assert response.closed is True
```

- [ ] **Step 3: Write failing protocol and framing tests**

Parameterize streams that contain:

```python
[
    (
        "no_non_empty_chunk",
        [
            ("chunk", {"content": ""}),
            ("result", answer_payload()),
            ("done", {"ok": True}),
        ],
    ),
    (
        "duplicate_result",
        [
            ("chunk", {"content": "x"}),
            ("result", answer_payload()),
            ("result", answer_payload()),
            ("done", {"ok": True}),
        ],
    ),
    ("missing_result", [("chunk", {"content": "x"}), ("done", {"ok": True})]),
    ("missing_done", [("chunk", {"content": "x"}), ("result", answer_payload())]),
    (
        "error_event",
        [
            ("error", {"error": {"code": "ANSWER_FAILED", "message": "safe"}}),
            ("done", {"ok": True}),
        ],
    ),
    ("event_after_done", [("done", {"ok": True}), ("chunk", {"content": "x"})]),
]
```

For each, assert `observation is None`,
`code == "LIVE_QUALITY_REQUEST_FAILED"`, and that no server error message or
secret enters the check payload. Add direct parser tests for LF, CRLF, comment
lines, multiple `data:` lines, an incomplete trailing frame, a field without a
colon, and non-JSON data.

- [ ] **Step 4: Run the live client tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_client.py -q
```

Expected: the current client posts to the non-streaming endpoint, has no SSE
parser, and lacks all new observation fields.

- [ ] **Step 5: Add strict timing fields to the runtime observation**

Extend `LiveQualityObservation`:

```python
ttft_ms: float
retrieval_latency_ms: float
rerank_attempted: bool
rerank_succeeded: bool
rerank_latency_ms: float | None
generation_latency_ms: float
generation_first_token_latency_ms: float
```

Place `ttft_ms` before the existing `latency_ms`; keep cost/token fields
unchanged.

- [ ] **Step 6: Implement the incremental SSE parser**

In `client.py`, add a private immutable event DTO and parser:

```python
@dataclass(frozen=True)
class _SseEvent:
    name: str
    data: dict[str, Any]


def _iter_sse_events(lines: Iterable[str | bytes]) -> Iterator[_SseEvent]:
    event_name = ""
    data_lines: list[str] = []
    frame_started = False
    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.removesuffix("\r")
        if line == "":
            if not frame_started:
                continue
            if not event_name or not data_lines:
                raise ValueError("incomplete live quality SSE event")
            payload = json.loads("\n".join(data_lines))
            if not isinstance(payload, dict):
                raise ValueError("live quality SSE data must be an object")
            yield _SseEvent(name=event_name, data=payload)
            event_name = ""
            data_lines = []
            frame_started = False
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            raise ValueError("invalid live quality SSE field")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            if event_name:
                raise ValueError("duplicate live quality SSE event field")
            event_name = value
            frame_started = True
        elif field == "data":
            data_lines.append(value)
            frame_started = True
        else:
            raise ValueError("unsupported live quality SSE field")
    if frame_started:
        raise ValueError("unterminated live quality SSE event")
```

Import `json`, `dataclass`, `Iterable`, and `Iterator`.

- [ ] **Step 7: Implement one streaming request and protocol validation**

Replace `_post_debug_answer` with `_post_debug_answer_stream`. It must:

1. POST to `/v1/debug/answers/stream` with `stream=True`.
2. Require a content type beginning with `text/event-stream`.
3. Ignore progress messages for timing.
4. Record the first non-empty chunk elapsed time.
5. Reject stream error events.
6. Require exactly one result and one final done.
7. Reject any event after done.
8. Compare the concatenated non-empty chunk content to
   `result["response"]["summary"]["answer"]`.
9. Close the response in `finally`.

Use:

```python
def _elapsed_ms(clock: Clock, started: float) -> float:
    elapsed = (clock() - started) * 1000
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError("invalid live quality client timing")
    return elapsed
```

Return `(result_payload, ttft_ms, response_latency_ms)`. Keep the sanitized
request-failure check and measure its duration from the same injected clock.

- [ ] **Step 8: Normalize and strictly validate trace timings**

Change `normalize_live_quality_observation` to require keyword-only
`ttft_ms` and `latency_ms`. Add `route_trace.total_latency_ms`,
`generation_trace.total_latency_ms`, and
`generation_trace.first_token_latency_ms` to the explicit contract. Require the
`post_process` stage and explicitly set rerank fields.

Validate:

```python
if route_trace.total_latency_ms <= 0:
    raise ValueError("live quality retrieval latency is missing")
if generation_trace.total_latency_ms <= 0:
    raise ValueError("live quality generation latency is missing")
if generation_trace.first_token_latency_ms <= 0:
    raise ValueError("live quality generation first-token latency is missing")
if post_process.rerank_attempted:
    if post_process.rerank_latency_ms is None or post_process.rerank_latency_ms <= 0:
        raise ValueError("live quality rerank latency is missing")
elif post_process.rerank_latency_ms is not None:
    raise ValueError("live quality rerank timing is inconsistent")
```

Populate every new observation field from the client timing or trace.

- [ ] **Step 9: Run the live client tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_client.py -q
```

Expected: all happy-path, framing, protocol, trace, timeout, sanitization, URL,
token, and session-ownership tests pass.

- [ ] **Step 10: Commit Task 3**

```powershell
git add scripts/live_quality_gate/client.py `
  scripts/live_quality_gate/runtime_models.py `
  tests/test_live_quality_gate_client.py
git commit -m "feat: measure live quality over debug SSE"
```

---

### Task 4: Enforce and Report the Interaction SLOs

**Files:**

- Modify: `scripts/live_quality_gate/models.py`
- Modify: `scripts/live_quality_gate/evaluator.py`
- Modify: `scripts/live_quality_gate/reporter.py`
- Test: `tests/test_live_quality_gate_config.py`
- Test: `tests/test_live_quality_gate_evaluator.py`
- Test: `tests/test_live_quality_gate_reporter.py`
- Test: `tests/test_live_quality_gate_service.py`

**Interfaces:**

- Consumes timing-complete observations from Task 3.
- Produces live-quality policy/report schema version 2.
- Produces per-case `timings` and aggregate/slice p95 metrics.
- Produces five blocking latency checks plus rerank coverage.
- Produces the report contract consumed by Task 5.

- [ ] **Step 1: Write failing schema-v2 policy tests**

Update the test policy fixture to `schema_version=2` and add:

```python
minimum_rerank_observation_count=1,
maximum_p95_ttft_ms=5000.0,
maximum_p95_retrieval_latency_ms=3000.0,
maximum_p95_rerank_latency_ms=2000.0,
maximum_p95_generation_latency_ms=20000.0,
maximum_p95_latency_ms=25000.0,
```

Add each field to missing-key and numeric-bound parameterization. Assert
schema version 1 is rejected.

- [ ] **Step 2: Run config tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_config.py -q
```

Expected: schema version 2 and the new threshold names are rejected.

- [ ] **Step 3: Implement the strict version 2 policy model**

Change:

```python
class LiveQualityThresholds(StrictLiveQualityModel):
    minimum_case_count: int = Field(ge=1)
    minimum_rerank_observation_count: int = Field(ge=1)
    ...
    maximum_p95_ttft_ms: float = Field(gt=0)
    maximum_p95_retrieval_latency_ms: float = Field(gt=0)
    maximum_p95_rerank_latency_ms: float = Field(gt=0)
    maximum_p95_generation_latency_ms: float = Field(gt=0)
    maximum_p95_latency_ms: float = Field(gt=0)
```

Set `LiveQualityGatePolicy.schema_version` to `Literal[2]`.

- [ ] **Step 4: Write failing aggregate and threshold tests**

Extend `make_observation` with deterministic timing defaults. In the three-case
aggregate test, use:

```python
ttft_ms=(1000.0, 2000.0, 6000.0)
retrieval_latency_ms=(500.0, 1000.0, 3500.0)
rerank_attempted=(True, False, True)
rerank_succeeded=(True, False, True)
rerank_latency_ms=(250.0, None, 2100.0)
generation_latency_ms=(4000.0, 8000.0, 21000.0)
generation_first_token_latency_ms=(900.0, 1500.0, 5000.0)
latency_ms=(5000.0, 10000.0, 26000.0)
```

Assert:

```python
assert metrics["p95_ttft_ms"] == 6000.0
assert metrics["p95_retrieval_latency_ms"] == 3500.0
assert metrics["rerank_observation_count"] == 2
assert metrics["p95_rerank_latency_ms"] == 2100.0
assert metrics["p95_generation_latency_ms"] == 21000.0
assert metrics["p95_generation_first_token_latency_ms"] == 5000.0
assert metrics["p95_latency_ms"] == 26000.0
```

Add exact-boundary pass tests and one-over-boundary failures for all five
budgets. Add a no-rerank test asserting
`rerank_observation_count == 0`, `p95_rerank_latency_ms is None`, and both
coverage and missing-metric checks fail.

- [ ] **Step 5: Run evaluator tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_evaluator.py -q
```

Expected: aggregate timing names and checks are missing.

- [ ] **Step 6: Implement timing aggregation and blocking checks**

In `_summary`, calculate:

```python
rerank_latencies = [
    result.observation.rerank_latency_ms
    for result in grouped_results
    if result.observation.rerank_attempted
    and result.observation.rerank_succeeded
    and result.observation.rerank_latency_ms is not None
]
```

Return:

```python
"p95_ttft_ms": percentile(
    [result.observation.ttft_ms for result in grouped_results],
    0.95,
) if grouped_results else 0.0,
"p95_retrieval_latency_ms": percentile(
    [result.observation.retrieval_latency_ms for result in grouped_results],
    0.95,
) if grouped_results else 0.0,
"rerank_observation_count": len(rerank_latencies),
"p95_rerank_latency_ms": (
    percentile(rerank_latencies, 0.95) if rerank_latencies else None
),
"p95_generation_latency_ms": percentile(
    [result.observation.generation_latency_ms for result in grouped_results],
    0.95,
) if grouped_results else 0.0,
"p95_generation_first_token_latency_ms": percentile(
    [
        result.observation.generation_first_token_latency_ms
        for result in grouped_results
    ],
    0.95,
) if grouped_results else 0.0,
```

Add `numeric_threshold_check` calls named:

```text
metrics.rerank_observation_count
metrics.p95_ttft_ms
metrics.p95_retrieval_latency_ms
metrics.p95_rerank_latency_ms
metrics.p95_generation_latency_ms
metrics.p95_latency_ms
```

Use `COVERAGE_REGRESSION` for rerank count and `BUDGET_REGRESSION` for latency.
The internal first-token metric receives no blocking check.

- [ ] **Step 7: Write failing report-v2 tests**

In `tests/test_live_quality_gate_reporter.py`, expand `passing_metrics`, assert
`schema_version == 2`, and assert a case timing object exactly equals:

```python
{
    "ttft_ms": 1000.0,
    "latency_ms": 5000.0,
    "retrieval_latency_ms": 500.0,
    "rerank_attempted": True,
    "rerank_succeeded": True,
    "rerank_latency_ms": 250.0,
    "generation_latency_ms": 4000.0,
    "generation_first_token_latency_ms": 900.0,
}
```

Assert the Markdown summary contains every p95 metric and
`rerank_observation_count`.

- [ ] **Step 8: Run reporter/service tests and verify RED**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_reporter.py tests/test_live_quality_gate_service.py -q
```

Expected: report schema remains 1 and has no timing object or summary lines.

- [ ] **Step 9: Implement report-v2 case timing and summary output**

Set report `schema_version` to 2. Add a `_case_timings` helper returning the
exact object above, include it in each case summary, and add the aggregate
metric names to `_PRIMARY_METRIC_NAMES`.

Do not add timing data to manual-review samples; the canonical report remains
the recomputation source.

- [ ] **Step 10: Run all live-quality unit tests and verify GREEN**

Run:

```powershell
python -m pytest `
  tests/test_live_quality_gate_config.py `
  tests/test_live_quality_gate_client.py `
  tests/test_live_quality_gate_evaluator.py `
  tests/test_live_quality_gate_reporter.py `
  tests/test_live_quality_gate_service.py `
  -q
```

Expected: all tests pass.

- [ ] **Step 11: Commit Task 4**

```powershell
git add scripts/live_quality_gate/models.py `
  scripts/live_quality_gate/evaluator.py `
  scripts/live_quality_gate/reporter.py `
  tests/test_live_quality_gate_config.py `
  tests/test_live_quality_gate_evaluator.py `
  tests/test_live_quality_gate_reporter.py `
  tests/test_live_quality_gate_service.py
git commit -m "feat: enforce live interaction SLOs"
```

---

### Task 5: Upgrade Release Evidence to Recompute the SLOs

**Files:**

- Modify: `scripts/release_evidence/models.py`
- Modify: `scripts/release_evidence/capture.py`
- Modify: `scripts/release_evidence/verifier.py`
- Modify: `tests/release_evidence_fixtures.py`
- Modify: `tests/test_release_evidence_models.py`
- Modify: `tests/test_release_evidence_capture.py`
- Modify: `tests/test_release_evidence_verifier.py`
- Modify: `tests/test_release_evidence_finalize.py`

**Interfaces:**

- Consumes Task 4 report schema version 2.
- Produces `graph-rag-release-evidence-capture-v2`.
- Produces `graph-rag-release-evidence-v2`.
- Projects every blocking timing metric and rerank observation count into
  `QualityMetrics`.

- [ ] **Step 1: Write failing v2 evidence-model tests**

Update `QualityMetrics` fixtures to require:

```python
rerank_observation_count=1,
p95_ttft_ms=1000.0,
p95_retrieval_latency_ms=500.0,
p95_rerank_latency_ms=250.0,
p95_generation_latency_ms=4000.0,
p95_latency_ms=5000.0,
```

Add assertions:

```python
assert CAPTURE_SCHEMA_VERSION == "graph-rag-release-evidence-capture-v2"
assert MANIFEST_SCHEMA_VERSION == "graph-rag-release-evidence-v2"
```

Add a strict-model test proving a v1 manifest is rejected.

- [ ] **Step 2: Run evidence model/finalize tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_models.py tests/test_release_evidence_finalize.py -q
```

Expected: constants remain v1 and `QualityMetrics` rejects the new keys.

- [ ] **Step 3: Implement release-evidence v2 model fields**

Set:

```python
CAPTURE_SCHEMA_VERSION = "graph-rag-release-evidence-capture-v2"
MANIFEST_SCHEMA_VERSION = "graph-rag-release-evidence-v2"
```

Extend `QualityMetrics`:

```python
rerank_observation_count: PositiveInt
p95_ttft_ms: NonNegativeFloat
p95_retrieval_latency_ms: NonNegativeFloat
p95_rerank_latency_ms: NonNegativeFloat
p95_generation_latency_ms: NonNegativeFloat
p95_latency_ms: NonNegativeFloat
```

Keep diagnostic internal first-token latency out of the compact release
projection because it is not release-blocking.

- [ ] **Step 4: Update the canonical evidence fixture to report v2**

Update `tests/release_evidence_fixtures.py` policy schema, thresholds,
observation timings, report schema expectations, and generated aggregate
checks. The fixture must contain one successful rerank observation so it can
produce a valid successful release report.

- [ ] **Step 5: Write failing exact-schema and tamper tests**

Extend capture parameterization with these mutations:

```text
case timing removed
case timing extra key
aggregate TTFT changed
aggregate retrieval p95 changed
aggregate rerank p95 changed
aggregate generation p95 changed
rerank count changed
rerank attempted changed to false
diagnostic first-token p95 changed
policy threshold expected payload changed
```

Every mutation must raise `ReleaseEvidenceCaptureError`. Add verifier mutations
for a v1 live report and a v1 evidence manifest.

- [ ] **Step 6: Run capture/verifier tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_evidence_capture.py tests/test_release_evidence_verifier.py -q
```

Expected: v2 report fields are unknown or are not recomputed, so at least the
new tamper cases fail to raise.

- [ ] **Step 7: Implement exact report-v2 validation**

In `capture.py`:

- add all aggregate timing names plus diagnostic internal first-token and
  rerank count to `_LIVE_SUMMARY_KEYS`;
- add `timings` to `_LIVE_CASE_KEYS`;
- define `_LIVE_CASE_TIMING_KEYS` with the exact seven Task 4 case keys;
- validate counts as integers, flags as booleans, optional rerank latency
  consistently, and all observed numbers as finite/non-negative;
- require report schema version 2;
- add the blocking names to `_QUALITY_METRIC_CHECK_NAMES`;
- reconstruct `LiveQualityObservation` timings from case reports;
- call `aggregate_live_quality_metrics` and compare every aggregate and slice
  timing summary;
- require successful report rerank count to meet policy;
- project all blocking values in `_project_quality`.

Use the existing `_float_matches` tolerance and existing exact-key helpers. Do
not trust aggregate values without recomputing them from cases.

In `verifier.py`, require report schema version 2 and v2 manifest models before
validating bundle timestamps and hashes.

- [ ] **Step 8: Run all evidence tests and verify GREEN**

Run:

```powershell
python -m pytest `
  tests/test_release_evidence_models.py `
  tests/test_release_evidence_capture.py `
  tests/test_release_evidence_finalize.py `
  tests/test_release_evidence_verifier.py `
  -q
```

Expected: all tests pass, including every semantic fabrication case.

- [ ] **Step 9: Commit Task 5**

```powershell
git add scripts/release_evidence/models.py `
  scripts/release_evidence/capture.py `
  scripts/release_evidence/verifier.py `
  tests/release_evidence_fixtures.py `
  tests/test_release_evidence_models.py `
  tests/test_release_evidence_capture.py `
  tests/test_release_evidence_verifier.py `
  tests/test_release_evidence_finalize.py
git commit -m "feat: bind interaction SLOs to release evidence"
```

---

### Task 6: Ratchet the Canonical Policy and Documentation

**Files:**

- Modify: `eval/live_quality_gate.json`
- Modify: `docs/live_quality_gate.md`
- Modify: `docs/release_process.md`
- Modify: `quality-evidence/README.md`
- Test: `tests/test_live_quality_gate_config.py`

**Interfaces:**

- Consumes Task 4 policy schema version 2.
- Makes the five confirmed budgets canonical for all live runs.
- Documents the difference between development evidence and release evidence.

- [ ] **Step 1: Write the failing canonical-policy assertion**

Add:

```python
def test_default_policy_enforces_interactive_slo_and_customer_grounding() -> None:
    gate_policy = load_live_quality_policy()
    customer_grounded = [
        case
        for case in gate_policy.cases
        if case.cuisine == "customer_service"
        and case.expected_response_mode is LiveQualityResponseMode.GROUNDED_ANSWER
    ]

    assert gate_policy.schema_version == 2
    assert len(gate_policy.cases) == 52
    assert len(customer_grounded) == 5
    assert gate_policy.thresholds.minimum_rerank_observation_count == 1
    assert gate_policy.thresholds.maximum_p95_ttft_ms == 5000.0
    assert gate_policy.thresholds.maximum_p95_retrieval_latency_ms == 3000.0
    assert gate_policy.thresholds.maximum_p95_rerank_latency_ms == 2000.0
    assert gate_policy.thresholds.maximum_p95_generation_latency_ms == 20000.0
    assert gate_policy.thresholds.maximum_p95_latency_ms == 25000.0
```

- [ ] **Step 2: Run the assertion and verify RED**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_config.py -q
```

Expected: default policy schema/threshold assertions fail.

- [ ] **Step 3: Update the canonical policy**

Set the JSON root schema version to 2. Add:

```json
"minimum_rerank_observation_count": 1,
"maximum_p95_ttft_ms": 5000.0,
"maximum_p95_retrieval_latency_ms": 3000.0,
"maximum_p95_rerank_latency_ms": 2000.0,
"maximum_p95_generation_latency_ms": 20000.0,
"maximum_p95_latency_ms": 25000.0
```

Do not modify the 52 case objects or their expected outcomes.

- [ ] **Step 4: Update gate and release documentation**

Document:

- the single debug SSE request;
- first non-empty chunk TTFT;
- result-event full-response latency;
- retrieval and generation trace sources;
- applicable-only rerank p95 and minimum rerank coverage;
- internal first-token diagnostic semantics;
- exact thresholds and failure types;
- policy/report schema v2 and evidence v2;
- the 52-case/5-customer-grounded baseline;
- `0.4.0.dev0` diagnostic evidence not being release eligible;
- the requirement to recapture on every candidate commit.

Update `quality-evidence/README.md` without weakening the rule that only a
version-named `evidence-manifest.json` directly under `quality-evidence/releases/`
is release-discoverable.

- [ ] **Step 5: Run policy and documentation checks**

Run:

```powershell
python -m pytest tests/test_live_quality_gate_config.py -q
git diff --check
```

Expected: config tests pass and `git diff --check` emits no output.

- [ ] **Step 6: Commit Task 6**

```powershell
git add eval/live_quality_gate.json `
  docs/live_quality_gate.md `
  docs/release_process.md `
  quality-evidence/README.md `
  tests/test_live_quality_gate_config.py
git commit -m "docs: ratchet live interaction quality policy"
```

---

### Task 7: Complete Engineering Verification

**Files:**

- Modify only files changed by automated Ruff formatting, if any.

**Interfaces:**

- Verifies Tasks 1-6 as one repository change.
- Produces a clean implementation commit suitable for real-model evaluation.

- [ ] **Step 1: Run the focused combined slice**

```powershell
python -m pytest `
  tests/test_model_client_ports.py `
  tests/test_route_search_orchestrator.py `
  tests/test_answer_response_mapping.py `
  tests/test_live_quality_gate_config.py `
  tests/test_live_quality_gate_client.py `
  tests/test_live_quality_gate_evaluator.py `
  tests/test_live_quality_gate_reporter.py `
  tests/test_live_quality_gate_service.py `
  tests/test_release_evidence_models.py `
  tests/test_release_evidence_capture.py `
  tests/test_release_evidence_finalize.py `
  tests/test_release_evidence_verifier.py `
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run the API contract slice**

```powershell
python -m pytest `
  tests/test_api_answer.py `
  tests/test_api_build.py `
  tests/test_api_public_surface.py `
  tests/test_api_security.py `
  tests/test_api_sse.py `
  tests/test_entrypoints.py `
  -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run the full test suite**

```powershell
python -m pytest -q
```

Expected: exit code 0 with no failures or errors.

- [ ] **Step 4: Run Ruff without hiding auto-fixes**

```powershell
pre-commit run --all-files
```

Expected: all hooks pass. If Ruff changes files, inspect the diff, rerun the
focused combined slice, and rerun `pre-commit run --all-files` until it passes
without changes.

- [ ] **Step 5: Run the offline release gate**

```powershell
python scripts/release_gate.py
```

Expected: exit code 0 and a PASS summary.

- [ ] **Step 6: Verify the final code commit is clean**

```powershell
git diff --check
git status --short
```

Expected: `git diff --check` and `git status --short` emit no output. If
verification caused legitimate formatting changes, treat this step as failed.
Return to the task that owns each changed file, add that path to the task's
already-explicit `git add` command, amend that task commit, and restart Task 7
from Step 1. Do not create an unscoped formatting-only commit.

---

### Task 8: Run Real Gates and Retain 0.4 Development Evidence

**Files:**

- Create after a successful run:
  `docs/real_live_gates_success_2026-07-19.md`
- Create after a successful run:
  `quality-evidence/integration_gate/$runId/report.json`
- Create after a successful run:
  `quality-evidence/integration_gate/$runId/summary.md`
- Create after a successful run:
  `quality-evidence/live_quality_gate/$runId/report.json`
- Create after a successful run:
  `quality-evidence/live_quality_gate/$runId/summary.md`
- Create after a successful run:
  `quality-evidence/live_quality_gate/$runId/manual_review_sample.jsonl`

**Interfaces:**

- Consumes the clean final code commit from Task 7.
- Produces real-dependency and real-model diagnostic evidence bound to its
  evaluated commit.
- Does not create a protected release manifest for `0.4.0.dev0`.

Run all Task 8 commands in one persistent PowerShell terminal so
`$evaluatedCommit`, the process-only environment, and the evidence destination
variables remain in scope.

- [ ] **Step 1: Capture the evaluated commit and verify cleanliness**

Run:

```powershell
$dirtyPaths = git status --short
if ($dirtyPaths) {
    throw "The evaluated worktree is not clean."
}
$evaluatedCommit = git rev-parse HEAD
if ($evaluatedCommit -notmatch "^[0-9a-f]{40}$") {
    throw "The evaluated commit is invalid."
}
```

Expected: no exception and `$evaluatedCommit` contains one 40-character commit.
Do not change code after this point.

- [ ] **Step 2: Start the current customer-service stack**

Ensure Docker Desktop is running, then execute:

```powershell
docker compose --profile api up --build -d
docker compose --profile api ps
```

Expected: `neo4j`, `standalone`, `build-api`, `build-worker`, `bootstrap`, and
`api` reach their declared running/healthy/completed states. Do not proceed
while bootstrap or readiness is incomplete.

- [ ] **Step 3: Verify serving diagnostics without printing secrets**

The Docker API profile fixes authentication off, so do not construct or print
an authorization header. Request readiness and save diagnostics in the ignored
report workspace:

```powershell
$ready = Invoke-RestMethod -Uri "http://localhost:8000/v1/health/ready"
if ($ready.status -ne "ok") {
    throw "Serving readiness did not report ok."
}

$diagnosticsPath = "eval/reports/live_quality_gate/diagnostics.json"
New-Item -ItemType Directory -Force -Path "eval/reports/live_quality_gate" |
  Out-Null
Invoke-WebRequest `
  -UseBasicParsing `
  -Uri "http://localhost:8000/v1/diagnostics" `
  -OutFile $diagnosticsPath
$diagnostics = (
  Get-Content -Raw -Encoding utf8 $diagnosticsPath | ConvertFrom-Json
).diagnostics
if (
    -not $diagnostics.system_ready `
    -or $diagnostics.domain_name -ne "customer_service" `
    -or $diagnostics.manifest.health -ne "ready" `
    -or [string]::IsNullOrWhiteSpace($diagnostics.manifest.collection_name) `
    -or [string]::IsNullOrWhiteSpace($diagnostics.llm_model) `
    -or [string]::IsNullOrWhiteSpace($diagnostics.embedding_model) `
    -or [string]::IsNullOrWhiteSpace($diagnostics.rerank_model)
) {
    throw "Serving diagnostics do not identify a ready real-model stack."
}
```

This verifies:

- ready is true;
- domain is `customer_service`;
- the real LLM, embedding, and rerank model names are non-empty;
- the active artifact manifest is ready;
- Neo4j and Milvus identify the current customer-service knowledge base.

Save diagnostics only in the ignored `eval/reports` workspace. Do not print
headers or environment values.

- [ ] **Step 4: Load the local environment and run the integration gate**

Load the repository's existing `.env` into the current PowerShell process
without echoing names or values:

```powershell
$dotenvLines = Get-Content -Encoding utf8 .env
foreach ($dotenvLine in $dotenvLines) {
    if ($dotenvLine -notmatch "^[A-Za-z_][A-Za-z0-9_]*=") {
        continue
    }
    $dotenvName, $dotenvValue = $dotenvLine -split "=", 2
    $dotenvValue = $dotenvValue.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($dotenvName, $dotenvValue, "Process")
}
if ([string]::IsNullOrWhiteSpace($env:DASHSCOPE_API_KEY)) {
    throw "DASHSCOPE_API_KEY is missing from the local environment."
}

python -m scripts.integration_gate `
  --policy eval/integration_gate.json `
  --output-dir eval/reports/integration_gate `
  --json
```

Expected: exit code 0, `passed=true`, all 3 live cases executed, real vector and
graph participation present, no fallback/degradation, and the report generated
under `eval/reports/integration_gate`.

- [ ] **Step 5: Configure the judge from the loaded real-model credential**

Set process-only aliases without printing their values:

```powershell
$env:LIVE_QUALITY_API_URL = "http://localhost:8000"
$judgeEndpoint = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
$env:LIVE_QUALITY_JUDGE_API_URL = $judgeEndpoint
$env:LIVE_QUALITY_JUDGE_API_KEY = $env:DASHSCOPE_API_KEY
$env:LIVE_QUALITY_JUDGE_MODEL = $env:LLM_MODEL
$env:LIVE_QUALITY_JUDGE_ENABLE_THINKING = "false"
if ([string]::IsNullOrWhiteSpace($env:LIVE_QUALITY_JUDGE_MODEL)) {
    throw "LLM_MODEL is missing from the local environment."
}
```

Do not persist or print the key. Use the serving token only if API
authentication is enabled.

- [ ] **Step 6: Run the 52-case real-model live-quality gate**

```powershell
python -m scripts.live_quality_gate `
  --policy eval/live_quality_gate.json `
  --output-dir eval/reports/live_quality_gate `
  --json
```

Expected: exit code 0 and `passed=true`; `case_count=52`;
`rerank_observation_count>=1`; all blocking quality, degradation, cost, and
interaction SLO checks pass.

If the command exits 1 or 2, keep the ignored reports, identify the exact
failing stage/check, and do not create success evidence. Any code or policy fix
requires a new commit and a complete repeat from Task 7.

- [ ] **Step 7: Inspect and sanitize the final artifacts**

Verify the report:

- contains 52 case summaries and 52 valid observations;
- contains all five blocking p95 checks;
- contains no failed release-blocking check;
- contains no NaN or Infinity;
- contains no API key, bearer value, authorization header, raw exception,
  traceback, private absolute path, or real customer data;
- uses only synthetic customer identifiers already committed in the corpus.

Compute SHA-256 for both policies, both reports, both summaries, the manual
sample, diagnostics, and the active artifact manifest:

```powershell
$artifactManifestPath = "storage/indexes/artifact_manifest.json"
$hashPaths = @(
    "eval/integration_gate.json"
    "eval/live_quality_gate.json"
    "eval/reports/integration_gate/report.json"
    "eval/reports/integration_gate/summary.md"
    "eval/reports/live_quality_gate/report.json"
    "eval/reports/live_quality_gate/summary.md"
    "eval/reports/live_quality_gate/manual_review_sample.jsonl"
    $diagnosticsPath
    $artifactManifestPath
)
foreach ($hashPath in $hashPaths) {
    if (-not (Test-Path -LiteralPath $hashPath -PathType Leaf)) {
        throw "Required evidence input is missing: $hashPath"
    }
}
$artifactHashes = $hashPaths | ForEach-Object {
    [ordered]@{
        path = $_
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_).Hash.ToLower()
    }
}
```

Use `$artifactHashes` as the source for the success document; do not retype
digests.

- [ ] **Step 8: Retain timestamped diagnostic evidence**

Create the UTC run ID and diagnostic destinations once:

```powershell
$runId = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
$integrationEvidence = Join-Path "quality-evidence/integration_gate" $runId
$liveEvidence = Join-Path "quality-evidence/live_quality_gate" $runId
New-Item -ItemType Directory -Path $integrationEvidence, $liveEvidence
```

Copy only the sanitized integration report/summary and live
report/summary/manual sample:

```powershell
Copy-Item `
  -LiteralPath "eval/reports/integration_gate/report.json" `
  -Destination $integrationEvidence
Copy-Item `
  -LiteralPath "eval/reports/integration_gate/summary.md" `
  -Destination $integrationEvidence
Copy-Item `
  -LiteralPath "eval/reports/live_quality_gate/report.json" `
  -Destination $liveEvidence
Copy-Item `
  -LiteralPath "eval/reports/live_quality_gate/summary.md" `
  -Destination $liveEvidence
Copy-Item `
  -LiteralPath "eval/reports/live_quality_gate/manual_review_sample.jsonl" `
  -Destination $liveEvidence
```

Keep `$runId`, `$integrationEvidence`, and `$liveEvidence` in scope through
Step 9.

Write `docs/real_live_gates_success_2026-07-19.md` with:

- package version `0.4.0.dev0`;
- exact `evaluated_commit`;
- UTC run timestamp;
- profile and model suite;
- knowledge-base identity;
- policy/report SHA-256 values;
- integration result and 3-case details;
- live result, 52-case mode/customer-service counts, and judge averages;
- TTFT, retrieval, rerank, generation, full-response, and cost values against
  their thresholds;
- an explicit statement that this is development diagnostic evidence and not a
  protected release manifest;
- commands/checks run and any limitations.

- [ ] **Step 9: Commit only successful sanitized evidence**

Run:

```powershell
git diff --check
git status --short
```

Review every evidence file. Then:

```powershell
git add -- docs/real_live_gates_success_2026-07-19.md $integrationEvidence $liveEvidence
git commit -m "docs: record 0.4 live quality evidence"
```

The evidence commit may follow the evaluated code commit; the success document
must continue to name the exact code commit that was exercised.

- [ ] **Step 10: Stop the local stack only after artifacts are safe**

After reports and evidence are verified:

```powershell
docker compose --profile api down
```

Expected: project containers stop cleanly. Do not delete volumes because they
are local generated state and may be needed to reproduce the run.
