# Route Request Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make answer request budgets and cancellation propagate through routing, retrieval, graph, rerank, Milvus, Neo4j, and LLM calls.

**Architecture:** Add a runtime `RequestControl` object and make online runtime ports carry it explicitly through `RetrievalRequest` or generation control parameters. Rewrite touched internal contracts directly rather than preserving mixed `str | RetrievalRequest`, optional trace, or ignored-control compatibility paths. Provider calls use `RequestControl.remaining_seconds()` for timeout and cooperative checkpoints use `raise_if_cancelled()`.

**Tech Stack:** Python 3.11, dataclasses, FastAPI service layer, concurrent futures, requests, OpenAI SDK, PyMilvus, Neo4j Python driver, pytest, Ruff.

---

## File Structure

- Create `rag_modules/runtime/request_control.py`: request budget, cancellation signal, child controls, safe trace details, and runtime-control exceptions.
- Modify `rag_modules/runtime/__init__.py`: export request-control types.
- Modify `rag_modules/contracts/retrieval.py`: add `RetrievalRequest.control` and safe serialization.
- Modify `rag_modules/runtime_contracts.py`: rewrite online runtime ports to accept explicit request/control parameters.
- Modify `rag_modules/routing/workflow_service.py`: create/pass route controls and store them on route retrieval requests.
- Modify `rag_modules/routing/search_orchestrator.py`: check controls around execute, post-process, and fallback.
- Modify `rag_modules/routing/strategies/base.py`: build retrieval requests with controls and update strategy protocol.
- Modify `rag_modules/routing/strategies/hybrid.py`: pass request controls to hybrid retrieval.
- Modify `rag_modules/routing/strategies/graph.py`: require traced graph retrieval and pass request controls through graph and hybrid supplement paths.
- Modify `rag_modules/routing/strategies/combined.py`: derive child controls, cancel timed-out branches, and trace requested/observed cancellation.
- Modify `rag_modules/retrieval/hybrid_executor.py`: accept `RetrievalRequest` only for online hybrid search.
- Modify `rag_modules/retrieval/hybrid_search_service.py`: check controls around candidate generation and enrichment.
- Modify `rag_modules/retrieval/candidate_sources.py`: make vector and BM25 sources pass full requests.
- Modify `rag_modules/retrieval/candidate_generator.py`: check controls before and after each source.
- Modify `rag_modules/retrieval/hybrid_runtime.py`: vector/BM25 candidate methods accept `RetrievalRequest`.
- Modify `rag_modules/retrieval/adapters/vector_retriever.py`: accept `RetrievalRequest`, pass timeout to Milvus, and check control around Neo4j neighbor enrichment.
- Modify `rag_modules/infra/milvus/search.py`: accept `RetrievalRequest`, derive query/k/filter/control, and pass timeout to embedding/search when supported.
- Modify `rag_modules/dashscope_clients.py`: add per-call timeout/control support for embedding and rerank clients.
- Modify `rag_modules/retrieval/post_processor.py`: pass control to rerank and expose rerank degradation details.
- Modify `rag_modules/graph/rag_retrieval.py`: accept `RetrievalRequest` only for online graph retrieval.
- Modify `rag_modules/graph/retrieval_executor.py`: check controls around graph execution stages.
- Modify `rag_modules/graph/evidence_orchestrator.py`: pass controls into graph query execution and reasoning checkpoints.
- Modify `rag_modules/graph/query_executor.py`: accept controls and pass per-query timeouts to Neo4j.
- Modify `rag_modules/query_understanding/planning/service.py`: pass route control into planner LLM calls.
- Modify `rag_modules/query_understanding/service.py`: accept optional controls for `understand/analyze/explain` paths used by online routing.
- Modify `rag_modules/generation/clients/adapter.py`: accept controls in completion and streaming calls.
- Modify `rag_modules/generation/execution/*.py`: thread controls through direct, two-stage, compose, streaming, and timeout helpers.
- Modify `rag_modules/generation/service.py`: accept controls on public internal generation methods.
- Modify `rag_modules/app/services/trace_adapters.py`: make trace adapters pass controls to router/generation services.
- Modify `rag_modules/app/services/answer_models.py`: add `request_control` to `AnswerPipelineState`.
- Modify `rag_modules/app/services/answer_workflow.py`: create root controls and cancel them on failure.
- Modify `rag_modules/app/services/answer_pipeline.py`: pass controls to routing and generation.
- Modify `rag_modules/interfaces/api/services/serving_streams.py`: cancel stream controls when the consumer closes.
- Modify `rag_modules/interfaces/api/services/serving.py`: keep public API stable while allowing request controls to flow internally.
- Modify focused tests:
  - `tests/test_runtime_retrieval_models.py`
  - `tests/test_route_execution_strategies.py`
  - `tests/test_route_search_orchestrator.py`
  - `tests/test_hybrid_search_service.py`
  - `tests/test_hybrid_retrieval_runtime.py`
  - `tests/test_model_client_ports.py`
  - `tests/test_graph_retrieval_executor.py`
  - `tests/test_generation_client.py`
  - `tests/test_generation_executor.py`
  - `tests/test_answer_workflow.py`
  - `tests/test_api_app.py`
  - `tests/test_public_surface_boundaries.py`

## Implementation Notes

Use `time.perf_counter()` everywhere for deadlines. A missing control means local/internal non-answer callers get a new scope-local control only when a runtime boundary needs one; online answer paths should always pass the root control. Do not serialize `threading.Event`, callbacks, provider clients, or exception objects into runtime snapshots.

Use this helper pattern in touched code:

```python
control = request.control
if control is not None:
    control.raise_if_cancelled()
timeout = control.remaining_seconds() if control is not None else configured_timeout
```

For provider calls that do not support cancellation, check before and after the call and pass the smallest provider timeout available.

## Task 1: RequestControl Core

**Files:**
- Create: `rag_modules/runtime/request_control.py`
- Modify: `rag_modules/runtime/__init__.py`
- Modify: `rag_modules/contracts/retrieval.py`
- Test: `tests/test_runtime_retrieval_models.py`

- [ ] **Step 1: Write the failing RequestControl tests**

Add these tests to `tests/test_runtime_retrieval_models.py`.

```python
import pytest
import time

from rag_modules.contracts import RetrievalRequest
from rag_modules.runtime import RequestBudgetExceeded, RequestCancelled, RequestControl


def test_request_control_child_uses_tighter_deadline_and_shared_cancel() -> None:
    parent = RequestControl.for_timeout(10.0, scope="answer")
    child = parent.child(0.25, scope="combined.graph")

    assert child.scope == "combined.graph"
    assert child.deadline <= time.perf_counter() + 0.30
    assert child.deadline <= parent.deadline

    child.cancel("combined_branch_timeout")

    assert parent.cancelled
    assert child.cancelled
    assert parent.reason == "combined_branch_timeout"
    assert child.reason == "combined_branch_timeout"


def test_request_control_raises_cancelled_and_budget_exceeded() -> None:
    cancelled = RequestControl.for_timeout(5.0, scope="answer")
    cancelled.cancel("client_disconnect")

    with pytest.raises(RequestCancelled, match="client_disconnect"):
        cancelled.raise_if_cancelled()

    exhausted = RequestControl(deadline=time.perf_counter() - 0.01, scope="answer")

    with pytest.raises(RequestBudgetExceeded, match="answer"):
        exhausted.raise_if_cancelled()


def test_retrieval_request_serializes_safe_control_details_only() -> None:
    control = RequestControl.for_timeout(5.0, scope="route")
    request = RetrievalRequest.from_inputs(query="tofu", top_k=2, control=control)

    payload = request.to_dict()

    assert payload["control"]["scope"] == "route"
    assert payload["control"]["cancelled"] is False
    assert "cancel_event" not in str(payload)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_runtime_retrieval_models.py -q
```

Expected: fail with `ImportError` or `AttributeError` for `RequestControl`.

- [ ] **Step 3: Add RequestControl implementation**

Create `rag_modules/runtime/request_control.py`.

```python
"""Runtime request budget and cancellation controls."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .json_types import JsonObject, coerce_json_object

_MIN_TIMEOUT_SECONDS = 0.1


class RequestControlError(RuntimeError):
    """Base class for request-control runtime exits."""


class RequestCancelled(RequestControlError):
    """Raised when request execution observes a cancellation signal."""


class RequestBudgetExceeded(RequestControlError):
    """Raised when request execution observes an exhausted budget."""


@dataclass(slots=True)
class RequestControl:
    deadline: float
    scope: str = "request"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    _reason: str = ""

    @classmethod
    def for_timeout(cls, timeout_seconds: float, *, scope: str = "request") -> "RequestControl":
        timeout = max(_MIN_TIMEOUT_SECONDS, float(timeout_seconds or _MIN_TIMEOUT_SECONDS))
        return cls(deadline=time.perf_counter() + timeout, scope=str(scope or "request"))

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def budget_exhausted(self) -> bool:
        return self.remaining_seconds(minimum=0.0) <= 0

    def remaining_seconds(self, *, minimum: float = _MIN_TIMEOUT_SECONDS) -> float:
        remaining = self.deadline - time.perf_counter()
        if minimum <= 0:
            return max(0.0, remaining)
        return max(float(minimum), remaining)

    def cancel(self, reason: str = "request_cancelled") -> None:
        if not self._reason:
            self._reason = str(reason or "request_cancelled")
        self.cancel_event.set()

    def child(self, timeout_seconds: float, *, scope: str) -> "RequestControl":
        timeout = max(_MIN_TIMEOUT_SECONDS, float(timeout_seconds or _MIN_TIMEOUT_SECONDS))
        child_deadline = min(self.deadline, time.perf_counter() + timeout)
        return RequestControl(
            deadline=child_deadline,
            scope=str(scope or self.scope),
            cancel_event=self.cancel_event,
            _reason=self._reason,
        )

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RequestCancelled(self.reason or f"{self.scope}_cancelled")
        if self.budget_exhausted:
            self._reason = self._reason or f"{self.scope}_budget_exhausted"
            raise RequestBudgetExceeded(self._reason)

    def to_trace_details(self) -> JsonObject:
        remaining_ms = round(self.remaining_seconds(minimum=0.0) * 1000, 2)
        return coerce_json_object(
            {
                "scope": self.scope,
                "cancelled": self.cancelled,
                "reason": self.reason,
                "budget_exhausted": self.budget_exhausted,
                "remaining_ms": remaining_ms,
            }
        )


def control_trace_details(control: RequestControl | None) -> JsonObject:
    return control.to_trace_details() if control is not None else {}


__all__ = [
    "RequestBudgetExceeded",
    "RequestCancelled",
    "RequestControl",
    "RequestControlError",
    "control_trace_details",
]
```

- [ ] **Step 4: Export runtime-control types**

Modify `rag_modules/runtime/__init__.py`.

```python
from .request_control import (
    RequestBudgetExceeded,
    RequestCancelled,
    RequestControl,
    RequestControlError,
    control_trace_details,
)
```

Add these names to `__all__`.

- [ ] **Step 5: Add `control` to RetrievalRequest**

Modify `rag_modules/contracts/retrieval.py`.

```python
from ..runtime.request_control import RequestControl, control_trace_details
```

Add the field:

```python
control: Optional[RequestControl] = field(default=None, repr=False, compare=False)
```

Update `from_dict()` to keep external deserialization control-free:

```python
control=None,
```

Update `from_inputs()` signature and constructor:

```python
control: Optional[RequestControl] = None,
...
control=control,
```

Update `to_dict()` after `asdict` or replace `asdict(self)` with explicit fields so the `Event` never appears. Use:

```python
payload = {
    "query": self.query,
    "top_k": self.top_k,
    "candidate_k": self.candidate_k,
    "strategy": self.strategy,
    "constraints": self.effective_constraints.to_dict(),
    "query_plan": self.query_plan.to_dict() if self.query_plan else None,
    "entity_keywords": list(self.entity_keywords),
    "topic_keywords": list(self.topic_keywords),
    "metadata": dict(self.metadata or {}),
}
control_details = control_trace_details(self.control)
if control_details:
    payload["control"] = control_details
return payload
```

- [ ] **Step 6: Run the tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_runtime_retrieval_models.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/runtime/request_control.py rag_modules/runtime/__init__.py rag_modules/contracts/retrieval.py tests/test_runtime_retrieval_models.py
git commit -m "feat: add request control runtime contract"
```

## Task 2: Routing And Combined Branch Controls

**Files:**
- Modify: `rag_modules/runtime_contracts.py`
- Modify: `rag_modules/app/services/trace_adapters.py`
- Modify: `rag_modules/routing/workflow_service.py`
- Modify: `rag_modules/routing/search_orchestrator.py`
- Modify: `rag_modules/routing/strategies/base.py`
- Modify: `rag_modules/routing/strategies/hybrid.py`
- Modify: `rag_modules/routing/strategies/graph.py`
- Modify: `rag_modules/routing/strategies/combined.py`
- Test: `tests/test_route_execution_strategies.py`
- Test: `tests/test_route_search_orchestrator.py`
- Test: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Write failing combined-route control tests**

Add fakes to `tests/test_route_execution_strategies.py`.

```python
from rag_modules.runtime import RequestCancelled, RequestControl


class _ControlAwareBlockingGraphRetrieval(_BlockingGraphRetrieval):
    def __init__(self, graph_docs=None, *, started, release) -> None:
        super().__init__(graph_docs, started=started, release=release)
        self.observed_control = None
        self.observed_cancel = None

    def graph_rag_evidence_search_with_trace(self, request):
        self.observed_control = request.control
        self.started.set()
        while not self.release.wait(timeout=0.01):
            try:
                request.control.raise_if_cancelled()
            except RequestCancelled as exc:
                self.observed_cancel = str(exc)
                return [], self.trace
        return list(self.graph_docs), self.trace


class _ControlAwareBlockingTraditionalRetrieval(_BlockingTraditionalRetrieval):
    def __init__(self, hybrid_docs=None, *, started, release) -> None:
        super().__init__(hybrid_docs, started=started, release=release)
        self.observed_control = None
        self.observed_cancel = None

    def hybrid_evidence_search(self, request):
        self.observed_control = request.control
        self.started.set()
        while not self.release.wait(timeout=0.01):
            try:
                request.control.raise_if_cancelled()
            except RequestCancelled as exc:
                self.observed_cancel = str(exc)
                return HybridRetrievalOutcome(documents=[])
        return super().hybrid_evidence_search(request)
```

Add the test:

```python
def test_combined_strategy_cancels_running_graph_branch_control_on_timeout(self) -> None:
    graph_started = threading.Event()
    release_graph = threading.Event()
    graph = _ControlAwareBlockingGraphRetrieval(
        [EvidenceDocument(content="graph", recipe_name="Graph Dish", node_id="20")],
        started=graph_started,
        release=release_graph,
    )
    services = RouteRetrievalServices(
        traditional_retrieval=_FakeTraditionalRetrieval(
            [EvidenceDocument(content="hybrid", recipe_name="Hybrid Dish", node_id="10")]
        ),
        graph_rag_retrieval=graph,
        retrieval_profile=_FakeRetrievalProfile(),
    )
    request = _request(query="slow graph", top_k=2, strategy=SearchStrategy.COMBINED)
    request.retrieval_request = request.retrieval_request.copy_with(
        control=RequestControl.for_timeout(5.0, scope="route")
    )
    strategy = CombinedRouteStrategy(branch_timeout_seconds=0.05)

    try:
        outcome = strategy.execute(request, services=services)
    finally:
        release_graph.set()
        strategy.close()

    assert graph.observed_control.scope == "combined.graph"
    assert graph.observed_cancel == "combined_branch_timeout"
    assert outcome.stages[0].details["cancel_requested_branches"] == ["graph"]
    assert outcome.stages[0].details["cancel_observed_branches"] == ["graph"]
    assert outcome.stages[0].details["graph_control"]["cancelled"] is True
```

- [ ] **Step 2: Write failing orchestrator control propagation test**

Add to `tests/test_route_search_orchestrator.py`.

```python
from rag_modules.runtime import RequestControl


def test_search_orchestrator_passes_control_to_post_processor() -> None:
    control = RequestControl.for_timeout(5.0, scope="route")
    request = _route_request(
        query="tofu",
        top_k=2,
        strategy=SearchStrategy.HYBRID_TRADITIONAL,
        control=control,
    )
    processor = _CapturingPostProcessor()
    orchestrator = _orchestrator(post_processor=processor)

    orchestrator.post_process(request, [], trace=RouteTraceRecorder(query="tofu", requested_top_k=2))

    assert processor.contexts[0].control is control
```

- [ ] **Step 3: Run route tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
```

Expected: fail because controls are not passed to strategy branches or post-process context.

- [ ] **Step 4: Update runtime ports**

Modify `rag_modules/runtime_contracts.py`.

```python
from .runtime.request_control import RequestControl
```

Change the online retrieval ports:

```python
class HybridRetrievalPort(Protocol):
    def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome: ...

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]: ...


class GraphRAGRetrievalPort(Protocol):
    def graph_rag_evidence_search_with_trace(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]: ...
```

Change LLM/rerank ports now even if implementations are completed in later tasks:

```python
class LLMClientPort(Protocol):
    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int | float,
        model_name: str | None = None,
        control: RequestControl | None = None,
    ) -> LLMCompletionResponsePort: ...


class StreamingLLMClientPort(LLMClientPort, Protocol):
    def stream_prompt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        retries: int,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
    ) -> Iterator[str]: ...


class RerankClientPort(Protocol):
    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
        *,
        control: RequestControl | None = None,
        timeout_seconds: float | None = None,
    ) -> list[int]: ...
```

- [ ] **Step 5: Update route request builders**

Modify `rag_modules/routing/strategies/base.py`.

```python
from ...runtime.request_control import RequestControl
```

Change `build_route_retrieval_request()`:

```python
def build_route_retrieval_request(
    *,
    query: str,
    top_k: int,
    constraints: Optional[QueryConstraints] = None,
    candidate_k: Optional[int] = None,
    query_plan: Optional[QueryPlan] = None,
    strategy: str = "",
    control: RequestControl | None = None,
) -> RetrievalRequest:
    return RetrievalRequest.from_inputs(
        query=query,
        top_k=top_k,
        candidate_k=candidate_k,
        constraints=constraints,
        query_plan=query_plan,
        strategy=strategy,
        control=control,
    )
```

- [ ] **Step 6: Update routing workflow to accept controls**

Modify `rag_modules/routing/workflow_service.py`.

```python
from ..runtime import RequestControl
```

Change signatures:

```python
def route(self, query: str, top_k: int = 5, *, control: RequestControl | None = None) -> RouteResolution:
    resolution, _trace = self.route_with_trace(query, top_k, control=control)
    return resolution

def route_with_trace(
    self,
    query: str,
    top_k: int = 5,
    *,
    control: RequestControl | None = None,
) -> tuple[RouteResolution, RouteSnapshot]:
    route_control = control or RequestControl.for_timeout(
        float(getattr(self.config.generation, "generation_latency_budget_seconds", 30.0)),
        scope="route",
    )
```

Pass `route_control` into `_build_execution_request()` and into `build_retrieval_request(control=route_control)`.

Add trace diagnostics before finalize:

```python
trace.snapshot.diagnostics.details["request_control"] = route_control.to_trace_details()
```

- [ ] **Step 7: Update trace adapters**

Modify `rag_modules/app/services/trace_adapters.py` protocols and methods:

```python
from ...runtime import RequestControl

def route(self, query: str, top_k: int = 5, *, control: RequestControl | None = None) -> object: ...

def route_with_trace(
    self,
    query: str,
    top_k: int = 5,
    *,
    control: RequestControl | None = None,
) -> tuple[object, object | None]: ...
```

In `QueryRouterTraceAdapter.route_with_trace()`:

```python
raw_resolution, route_trace = self.router.route_with_trace(
    question,
    top_k,
    control=control,
)
```

Remove the non-trace fallback in this online path. If a test fake needs routing, update the fake to implement `route_with_trace()`.

- [ ] **Step 8: Update route strategies**

Modify `rag_modules/routing/strategies/hybrid.py`.

```python
control = request.retrieval_request.control
if control is not None:
    control.raise_if_cancelled()
outcome = services.traditional_retrieval.hybrid_evidence_search(request.retrieval_request)
```

Modify `rag_modules/routing/strategies/graph.py` to require traced graph retrieval:

```python
graph_request = request.retrieval_request.copy_with(
    top_k=request.top_k,
    candidate_k=request.top_k,
    strategy=SearchStrategy.GRAPH_RAG.value,
)
graph_documents, graph_trace = services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(
    graph_request
)
documents = services.traditional_retrieval.enrich_to_parent_evidence_documents(
    graph_request,
    graph_documents,
    top_n=request.top_k,
)
```

For fallback and supplement requests, call `build_route_retrieval_request(..., control=request.retrieval_request.control)`.

Modify `rag_modules/routing/strategies/combined.py`:

```python
route_control = request.retrieval_request.control
branch_timeout_seconds = self._resolve_branch_timeout_seconds(request)
traditional_control = (
    route_control.child(branch_timeout_seconds, scope="combined.traditional")
    if route_control is not None
    else RequestControl.for_timeout(branch_timeout_seconds, scope="combined.traditional")
)
graph_control = (
    route_control.child(branch_timeout_seconds, scope="combined.graph")
    if route_control is not None
    else RequestControl.for_timeout(branch_timeout_seconds, scope="combined.graph")
)
traditional_request = build_route_retrieval_request(..., control=traditional_control)
graph_request = build_route_retrieval_request(..., control=graph_control)
```

Use `graph_request` in `load_graph()`:

```python
docs, trace = services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(graph_request)
```

After timeout:

```python
branch_controls = {"traditional": traditional_control, "graph": graph_control}
for branch_name in timed_out_branches:
    branch_controls[branch_name].cancel("combined_branch_timeout")
```

Compute observed cancellations:

```python
cancel_observed_branches = [
    name for name in timed_out_branches if branch_controls[name].cancelled
]
```

Add details:

```python
"cancel_observed_branches": cancel_observed_branches,
"traditional_control": traditional_control.to_trace_details(),
"graph_control": graph_control.to_trace_details(),
```

- [ ] **Step 9: Update search orchestrator**

Modify `rag_modules/routing/search_orchestrator.py`.

```python
control = request.retrieval_request.control
if control is not None:
    control.raise_if_cancelled()
```

Call before strategy execution, before post-process, and before exception fallback.

Extend `RetrievalPostProcessContext` construction with:

```python
control=request.retrieval_request.control,
```

In `_build_exception_fallback_request()`, preserve the original control in `copy_with(metadata=metadata)`.

- [ ] **Step 10: Remove optional graph trace fallback assertions**

Add a public-surface boundary test in `tests/test_public_surface_boundaries.py`:

```python
def test_online_graph_route_requires_trace_capable_graph_retrieval() -> None:
    source = Path("rag_modules/routing/strategies/graph.py").read_text(encoding="utf-8")
    assert "hasattr" not in source
    assert "graph_rag_evidence_search(" not in source
```

- [ ] **Step 11: Run route tests**

Run:

```powershell
python -m pytest tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py tests/test_public_surface_boundaries.py -q
```

Expected: pass.

- [ ] **Step 12: Commit**

```powershell
git add rag_modules/runtime_contracts.py rag_modules/app/services/trace_adapters.py rag_modules/routing tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py tests/test_public_surface_boundaries.py
git commit -m "feat: propagate request control through routing"
```

## Task 3: Hybrid Retrieval And Milvus Budgets

**Files:**
- Modify: `rag_modules/retrieval/hybrid_executor.py`
- Modify: `rag_modules/retrieval/hybrid_search_service.py`
- Modify: `rag_modules/retrieval/candidate_generator.py`
- Modify: `rag_modules/retrieval/candidate_sources.py`
- Modify: `rag_modules/retrieval/hybrid_runtime.py`
- Modify: `rag_modules/retrieval/adapters/vector_retriever.py`
- Modify: `rag_modules/infra/milvus/search.py`
- Modify: `rag_modules/dashscope_clients.py`
- Test: `tests/test_hybrid_search_service.py`
- Test: `tests/test_hybrid_retrieval_runtime.py`
- Test: `tests/test_model_client_ports.py`

- [ ] **Step 1: Write failing hybrid candidate control test**

Add to `tests/test_hybrid_search_service.py`.

```python
from rag_modules.contracts import RetrievalRequest
from rag_modules.runtime import RequestControl


class _ControlCapturingRuntime(_FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.vector_requests = []

    def vector_candidates(self, request):
        self.vector_requests.append(request)
        return [EvidenceDocument(content="v", recipe_name="V")]


def test_vector_candidate_source_receives_full_request_control() -> None:
    control = RequestControl.for_timeout(5.0, scope="route")
    runtime = _ControlCapturingRuntime()
    source = VectorCandidateSource(runtime=runtime)
    request = RetrievalRequest.from_inputs(query="tofu", top_k=2, candidate_k=4, control=control)

    docs = source.retrieve(request)

    assert docs[0].recipe_name == "V"
    assert runtime.vector_requests[0].control is control
```

- [ ] **Step 2: Write failing Milvus timeout test**

Add to `tests/test_model_client_ports.py`.

```python
from rag_modules.contracts import RetrievalRequest
from rag_modules.runtime import RequestControl


class _FakeMilvusSearchClient:
    def __init__(self) -> None:
        self.search_calls = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return [[]]


class _TimeoutEmbeddingClient(_FakeEmbeddingClient):
    def __init__(self) -> None:
        super().__init__()
        self.timeouts = []

    def embed_query(self, text: str, *, timeout_seconds=None) -> list[float]:
        self.timeouts.append(timeout_seconds)
        return [1.0, 0.0]


def test_milvus_similarity_search_uses_request_control_timeout() -> None:
    embedding_client = _TimeoutEmbeddingClient()
    module = _MilvusModuleWithoutNetwork(
        collection_name="recipes",
        dimension=2,
        embedding_client=embedding_client,
    )
    module.collection_created = True
    module.client = _FakeMilvusSearchClient()
    control = RequestControl.for_timeout(3.0, scope="vector")
    request = RetrievalRequest.from_inputs(query="tofu", top_k=2, candidate_k=4, control=control)

    module.similarity_search(request)

    assert 0 < embedding_client.timeouts[0] <= 3.0
    assert 0 < module.client.search_calls[0]["timeout"] <= 3.0
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py tests/test_model_client_ports.py -q
```

Expected: fail because vector source/runtime/Milvus still use decomposed query arguments.

- [ ] **Step 4: Rewrite candidate sources**

Modify `rag_modules/retrieval/candidate_sources.py`.

```python
class VectorCandidateSource:
    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.runtime.vector_candidates(request)


class Bm25CandidateSource:
    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.runtime.bm25_candidates(request)
```

- [ ] **Step 5: Add control checkpoints to candidate generator**

Modify `rag_modules/retrieval/candidate_generator.py`.

```python
control = effective_request.control
if control is not None:
    control.raise_if_cancelled()
```

Place this before the loop and before each source retrieval. After `source.retrieve(request)`, check again before normalizing.

- [ ] **Step 6: Rewrite hybrid runtime primitive candidate methods**

Modify `rag_modules/retrieval/hybrid_runtime.py`.

```python
def vector_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
    if request.control is not None:
        request.control.raise_if_cancelled()
    return self.ensure_vector_retriever().search(request)


def bm25_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
    if request.control is not None:
        request.control.raise_if_cancelled()
    if not self._ensure_bm25_ready():
        logger.warning("BM25 index not initialized, returning empty result set.")
        return []
    return self.bm25_retriever.search(request.query, top_k=request.effective_candidate_k)
```

Update tests that assert tuple calls to expect `RetrievalRequest`.

- [ ] **Step 7: Rewrite VectorRetriever**

Modify `rag_modules/retrieval/adapters/vector_retriever.py`.

```python
from ...contracts import EvidenceDocument, RetrievalRequest


def search(self, request: RetrievalRequest) -> List[EvidenceDocument]:
    control = request.control
    if control is not None:
        control.raise_if_cancelled()
    try:
        vector_docs = self.milvus_module.similarity_search(request)
    ...
    if control is not None:
        control.raise_if_cancelled()
    neighbor_map = self._batch_get_neighbors(request, node_ids) if node_ids else {}
```

Change `_batch_get_neighbors()`:

```python
def _batch_get_neighbors(
    self,
    request: RetrievalRequest,
    node_ids: List[str],
    max_neighbors: int = 3,
) -> Dict[str, List[str]]:
    control = request.control
    if control is not None:
        control.raise_if_cancelled()
    ...
    result = session.run(
        query,
        {"node_ids": list(set(node_ids)), "max_n": max_neighbors},
        timeout=control.remaining_seconds() if control is not None else None,
    )
```

- [ ] **Step 8: Rewrite Milvus search**

Modify `rag_modules/infra/milvus/search.py`.

```python
from ...contracts import RetrievalRequest


def similarity_search(self, request: RetrievalRequest) -> list[JsonObject]:
    control = request.control
    if control is not None:
        control.raise_if_cancelled()
    query = request.query
    requested_k = request.effective_candidate_k
```

Replace `self.embeddings.embed_query(query)` with:

```python
embedding_timeout = control.remaining_seconds() if control is not None else None
try:
    query_vector = self.embeddings.embed_query(query, timeout_seconds=embedding_timeout)
except TypeError:
    query_vector = self.embeddings.embed_query(query)
```

Add search timeout:

```python
if control is not None:
    search_kwargs["timeout"] = control.remaining_seconds()
results = self.client.search(**search_kwargs)
```

Check control after search:

```python
if control is not None:
    control.raise_if_cancelled()
```

- [ ] **Step 9: Add per-call timeout support to DashScope embedding**

Modify `rag_modules/dashscope_clients.py`.

```python
def embed_query(self, text: str, *, timeout_seconds: float | None = None) -> List[float]:
    vectors = self.embed_documents([text], timeout_seconds=timeout_seconds)
    return vectors[0] if vectors else []

def embed_documents(
    self,
    texts: Sequence[str],
    *,
    timeout_seconds: float | None = None,
) -> List[List[float]]:
    ...
    vectors.extend(self._embed_batch(batch, timeout_seconds=timeout_seconds))

def _embed_batch(self, texts: Sequence[str], *, timeout_seconds: float | None = None) -> List[List[float]]:
    data = self.circuit_breaker.call(self._post_json, payload, timeout_seconds=timeout_seconds)

def _post_json(self, payload: dict, *, timeout_seconds: float | None = None) -> dict:
    response = self.session.post(..., timeout=self.timeout if timeout_seconds is None else timeout_seconds)
```

Update `EmbeddingClientPort` in `rag_modules/runtime_contracts.py` to include optional timeout keyword.

- [ ] **Step 10: Add control checkpoints to hybrid search service and executor**

Modify `rag_modules/retrieval/hybrid_search_service.py`.

```python
control = request.control
if control is not None:
    control.raise_if_cancelled()
candidates = self.candidate_generator.generate(request)
if control is not None:
    control.raise_if_cancelled()
```

Modify `rag_modules/retrieval/hybrid_executor.py`:

```python
def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome:
    return self.search_service.hybrid_evidence_search(request)
```

Remove `request_or_query`, `top_k`, `constraints`, `candidate_k`, and `query_plan` from the online `hybrid_evidence_search()` signature.

- [ ] **Step 11: Run hybrid/Milvus tests**

Run:

```powershell
python -m pytest tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py tests/test_model_client_ports.py -q
```

Expected: pass.

- [ ] **Step 12: Commit**

```powershell
git add rag_modules/retrieval rag_modules/infra/milvus/search.py rag_modules/dashscope_clients.py rag_modules/runtime_contracts.py tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py tests/test_model_client_ports.py
git commit -m "feat: propagate request budgets through hybrid retrieval"
```

## Task 4: Graph Retrieval And Neo4j Budgets

**Files:**
- Modify: `rag_modules/graph/rag_retrieval.py`
- Modify: `rag_modules/graph/retrieval_executor.py`
- Modify: `rag_modules/graph/evidence_orchestrator.py`
- Modify: `rag_modules/graph/query_executor.py`
- Test: `tests/test_graph_retrieval_executor.py`

- [ ] **Step 1: Write failing Neo4j timeout test**

Add to `tests/test_graph_retrieval_executor.py`.

```python
from rag_modules.graph.query_executor import GraphQueryExecutor
from rag_modules.runtime import RequestControl


class _RecordingNeo4jSession:
    def __init__(self) -> None:
        self.run_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, parameters=None, **kwargs):
        self.run_calls.append({"query": query, "parameters": parameters, "kwargs": kwargs})
        return []


class _RecordingNeo4jDriver:
    def __init__(self) -> None:
        self.session_obj = _RecordingNeo4jSession()

    def session(self, **kwargs):
        return self.session_obj


def test_graph_query_executor_passes_control_timeout_to_neo4j() -> None:
    driver = _RecordingNeo4jDriver()
    executor = GraphQueryExecutor(driver, database="neo4j")
    plan = _FakeRetrievalPlan()
    request = RetrievalRequest.from_inputs(
        query="tofu",
        top_k=2,
        control=RequestControl.for_timeout(3.0, scope="graph"),
    )

    executor.multi_hop_paths(plan, control=request.control)

    timeout = driver.session_obj.run_calls[0]["kwargs"]["timeout"]
    assert 0 < timeout <= 3.0
```

- [ ] **Step 2: Write failing graph cancellation checkpoint test**

Add to `tests/test_graph_retrieval_executor.py`.

```python
def test_graph_retrieval_executor_stops_when_control_cancelled_before_retrieve() -> None:
    runtime = _FakeGraphRuntime()
    control = RequestControl.for_timeout(5.0, scope="graph")
    control.cancel("combined_branch_timeout")
    executor = GraphRetrievalExecutor(
        config=build_test_config(),
        runtime=runtime,
        orchestrator=_FakeOrchestrator([]),
        cache_warmup=SimpleNamespace(),
        graph_cache_stats_store=SimpleNamespace(path="storage/cache.json"),
        entity_linker=SimpleNamespace(driver=None),
        graph_executor=SimpleNamespace(driver=None),
        database_name="neo4j",
    )
    executor.driver = object()
    request = RetrievalRequest.from_inputs(query="tofu", top_k=2, control=control)

    results, trace = executor.execute_with_trace(request)

    assert results == []
    assert trace.error.detail == "combined_branch_timeout"
```

- [ ] **Step 3: Run graph tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_graph_retrieval_executor.py -q
```

Expected: fail because graph executor does not accept controls.

- [ ] **Step 4: Rewrite GraphRAGRetrieval entry point**

Modify `rag_modules/graph/rag_retrieval.py`:

```python
def graph_rag_evidence_search_with_trace(
    self,
    request: RetrievalRequest,
) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
    return self.executor.execute_with_trace(request)
```

Remove online `graph_rag_evidence_search(request_or_query, top_k, ...)` support in this path. If other non-online helpers still need graph search, convert their callers to build `RetrievalRequest`.

- [ ] **Step 5: Add control checkpoints to graph retrieval executor**

Modify `rag_modules/graph/retrieval_executor.py`.

```python
from ..runtime import RequestBudgetExceeded, RequestCancelled
```

At the start of `execute_with_trace()`:

```python
control = request.control
try:
    if control is not None:
        control.raise_if_cancelled()
    ...
except (RequestCancelled, RequestBudgetExceeded) as exc:
    self.runtime.record_event(
        trace,
        "request_control_cancelled",
        status="error",
        details={"reason": str(exc)},
    )
    final_trace = self.runtime.finalize_trace(
        trace,
        start_time=start_time,
        error=graph_error_detail(detail=str(exc)),
    )
    return [], GraphRetrievalSnapshot.from_dict(final_trace.to_dict())
```

Check before context resolution, before plan build, before orchestrator retrieve, and before finalization.

- [ ] **Step 6: Pass controls through graph orchestrator**

Modify `rag_modules/graph/evidence_orchestrator.py`.

```python
def execute_graph_plan(
    self,
    retrieval_plan: GraphRetrievalPlan,
    *,
    control=None,
) -> List[GraphPath]:
```

Pass `control` to `self.graph_executor.shortest_paths(...)`, `entity_relation_paths(...)`, `multi_hop_paths(...)`, and `subgraphs(...)`.

In `_execute_graph_evidence()`:

```python
control = request.control
if control is not None:
    control.raise_if_cancelled()
paths = self.execute_graph_plan(retrieval_plan, control=control)
```

Check again before `reason_over_subgraph()`.

- [ ] **Step 7: Pass controls to Neo4j query execution**

Modify `rag_modules/graph/query_executor.py`.

Change signatures:

```python
def multi_hop_paths(self, plan: GraphRetrievalPlan, *, control=None) -> List[Any]:
...
def _run_path_query(self, query: str, params: Dict[str, Any], *, control=None) -> List[Any]:
```

Use helper:

```python
def _run_kwargs(self, control) -> Dict[str, Any]:
    if control is None:
        return {}
    control.raise_if_cancelled()
    return {"timeout": control.remaining_seconds()}
```

Call:

```python
return list(session.run(query, params, **self._run_kwargs(control)))
```

Check control after collecting records.

- [ ] **Step 8: Run graph tests**

Run:

```powershell
python -m pytest tests/test_graph_retrieval_executor.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```powershell
git add rag_modules/graph tests/test_graph_retrieval_executor.py
git commit -m "feat: propagate request budgets through graph retrieval"
```

## Task 5: Rerank And LLM Budgets

**Files:**
- Modify: `rag_modules/dashscope_clients.py`
- Modify: `rag_modules/retrieval/post_processor.py`
- Modify: `rag_modules/query_understanding/planning/service.py`
- Modify: `rag_modules/query_understanding/service.py`
- Modify: `rag_modules/generation/clients/adapter.py`
- Modify: `rag_modules/generation/execution/contracts.py`
- Modify: `rag_modules/generation/execution/direct.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Modify: `rag_modules/generation/execution/streaming.py`
- Modify: `rag_modules/generation/execution/engine.py`
- Modify: `rag_modules/generation/service.py`
- Test: `tests/test_model_client_ports.py`
- Test: `tests/test_generation_client.py`
- Test: `tests/test_generation_executor.py`
- Test: `tests/test_query_understanding_config.py`

- [ ] **Step 1: Write failing rerank control timeout test**

Add to `tests/test_model_client_ports.py`.

```python
class _ControlAwareRerankClient(_FakeRerankClient):
    def rerank(self, query, documents, top_n, *, control=None, timeout_seconds=None):
        self.calls.append(
            {
                "query": query,
                "documents": list(documents),
                "top_n": top_n,
                "control": control,
                "timeout_seconds": timeout_seconds,
            }
        )
        return list(self.order)


def test_retrieval_post_processor_passes_control_to_rerank() -> None:
    control = RequestControl.for_timeout(4.0, scope="post_process")
    rerank_client = _ControlAwareRerankClient(order=[1, 0])
    processor = RetrievalPostProcessor(
        settings=RetrievalPostProcessSettings(enable_rerank=True, rerank_model="fake-reranker"),
        rerank_client=rerank_client,
    )
    docs = [
        EvidenceDocument(content="first", recipe_name="first"),
        EvidenceDocument(content="second", recipe_name="second"),
    ]

    processor.post_process(
        docs,
        top_k=2,
        context=RetrievalPostProcessContext(
            query="which one",
            strategy="hybrid_traditional",
            query_complexity=0.1,
            relationship_intensity=0.1,
            route_confidence=0.9,
            control=control,
        ),
    )

    assert rerank_client.calls[0]["control"] is control
    assert 0 < rerank_client.calls[0]["timeout_seconds"] <= 4.0
```

- [ ] **Step 2: Write failing LLM control timeout test**

Add to `tests/test_generation_client.py`.

```python
from rag_modules.runtime import RequestControl


def test_completion_timeout_is_capped_by_request_control() -> None:
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
    client = _FakeClient([response])
    adapter = GenerationClientAdapter(
        client=client,
        model_name="test-model",
        default_temperature=0.0,
        request_retries=1,
        stream_timeout_seconds=5,
    )
    control = RequestControl.for_timeout(2.0, scope="generation")

    adapter.create_completion(
        prompt="test",
        temperature=0.0,
        max_tokens=10,
        timeout=30,
        control=control,
    )

    assert 0 < client.completions.calls[0]["timeout"] <= 2.0
```

Add streaming test:

```python
def test_stream_stops_when_control_cancelled_between_chunks() -> None:
    control = RequestControl.for_timeout(5.0, scope="generation")
    client = _FakeClient([[_stream_chunk("hello"), _stream_chunk("world")]])
    adapter = GenerationClientAdapter(
        client=client,
        model_name="test-model",
        default_temperature=0.0,
        request_retries=1,
        stream_timeout_seconds=5,
    )

    stream = adapter.stream_prompt(
        prompt="test",
        max_tokens=10,
        retries=1,
        timeout_seconds=5,
        control=control,
    )
    assert next(stream) == "hello"
    control.cancel("client_disconnect")

    with pytest.raises(RequestCancelled):
        next(stream)
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py tests/test_generation_client.py tests/test_generation_executor.py tests/test_query_understanding_config.py -q
```

Expected: fail because rerank and LLM methods do not accept control.

- [ ] **Step 4: Extend post-process context and rerank calls**

Modify `rag_modules/retrieval/post_processor.py`.

```python
from ..runtime import RequestBudgetExceeded, RequestCancelled, RequestControl


@dataclass
class RetrievalPostProcessContext:
    ...
    control: RequestControl | None = None
```

Change `_rerank_documents()`:

```python
def _rerank_documents(
    self,
    query: str,
    documents: List[EvidenceDocument],
    top_k: int,
    *,
    control: RequestControl | None = None,
) -> List[EvidenceDocument]:
```

Call:

```python
ordered_indices = self.rerank_client.rerank(
    query=query,
    documents=[self._build_rerank_text(doc) for doc in documents],
    top_n=min(top_k, len(documents)),
    control=control,
    timeout_seconds=control.remaining_seconds() if control is not None else None,
)
```

Catch request-control exceptions and return original documents:

```python
except (RequestCancelled, RequestBudgetExceeded):
    return documents
```

- [ ] **Step 5: Extend DashScope rerank client**

Modify `rag_modules/dashscope_clients.py`.

```python
def rerank(
    self,
    query: str,
    documents: Sequence[str],
    top_n: int,
    *,
    control=None,
    timeout_seconds: float | None = None,
) -> List[int]:
    if control is not None:
        control.raise_if_cancelled()
    data = self.circuit_breaker.call(
        self._post_json,
        payload,
        timeout_seconds=timeout_seconds or (control.remaining_seconds() if control else None),
    )
```

Change `_post_json()`:

```python
def _post_json(self, payload: dict, *, timeout_seconds: float | None = None) -> dict:
    response = self.session.post(..., timeout=self.timeout if timeout_seconds is None else timeout_seconds)
```

- [ ] **Step 6: Pass control through query understanding planner**

Modify `rag_modules/query_understanding/planning/service.py`.

```python
from ...runtime import RequestControl

def plan(self, query: str, *, control: RequestControl | None = None) -> QueryPlan:
...
plan = self._create_plan(query, cache_key=cache_key, control=control)
```

Pass control to LLM:

```python
response = self.llm_client.create_completion(
    ...,
    timeout=self.settings.timeout_seconds,
    control=control,
)
```

Modify `rag_modules/query_understanding/service.py` so `understand(query, *, control=None)` passes control into planner.

- [ ] **Step 7: Extend GenerationClientAdapter**

Modify `rag_modules/generation/clients/adapter.py`.

`create_completion()`:

```python
def create_completion(..., control=None) -> LLMCompletionResponsePort:
    if control is not None:
        control.raise_if_cancelled()
    configured_deadline = time.perf_counter() + max(0.1, float(timeout))
    request_deadline = min(configured_deadline, control.deadline) if control is not None else configured_deadline
```

Before each attempt:

```python
if control is not None:
    control.raise_if_cancelled()
remaining = request_deadline - time.perf_counter()
```

`stream_prompt()`:

```python
def stream_prompt(..., control=None) -> Generator[str, None, None]:
```

Before provider call and inside chunk loop:

```python
if control is not None:
    control.raise_if_cancelled()
...
for chunk in response:
    if control is not None:
        control.raise_if_cancelled()
```

- [ ] **Step 8: Thread control through generation execution**

Modify `rag_modules/generation/execution/engine.py` signatures:

```python
def generate(..., control=None) -> str:
def generate_with_trace(..., control=None) -> tuple[str, GenerationSnapshot]:
def compose(..., timeout_seconds=None, control=None) -> str:
def compose_from_context(..., timeout_seconds=None, control=None) -> str:
```

Pass `control` into `_run_direct_completion()`, `_generate_two_stage_with_fallback()`, `_build_answer_plan()`, `compose_from_context()`, and `client_adapter.create_completion()`.

Modify `rag_modules/generation/execution/contracts.py` to add `control=None` to the protocol methods used by mixins.

Modify `rag_modules/generation/execution/direct.py`, `two_stage.py`, and `streaming.py` so every `client_adapter.create_completion()` and `stream_prompt()` call passes `control=control`.

In streaming loops, check control before fallback:

```python
if control is not None:
    control.raise_if_cancelled()
```

- [ ] **Step 9: Thread control through generation service**

Modify `rag_modules/generation/service.py`.

```python
def generate_answer_with_trace_from_context(
    self,
    answer_context: AnswerContext | dict,
    *,
    control=None,
) -> tuple[str, GenerationSnapshot]:
    ...
    answer, trace = self.executor.generate_with_trace(answer_context=context, control=control)
```

Do the same for `generate_answer_from_context()`, `generate_answer_stream_from_context()`, and `generate_answer_stream_with_trace_from_context()`.

Update `rag_modules/app/services/trace_adapters.py` generation protocols and adapter methods to accept/pass `control`.

- [ ] **Step 10: Run rerank and generation tests**

Run:

```powershell
python -m pytest tests/test_model_client_ports.py tests/test_generation_client.py tests/test_generation_executor.py tests/test_query_understanding_config.py -q
```

Expected: pass.

- [ ] **Step 11: Commit**

```powershell
git add rag_modules/dashscope_clients.py rag_modules/retrieval/post_processor.py rag_modules/query_understanding rag_modules/generation rag_modules/app/services/trace_adapters.py tests/test_model_client_ports.py tests/test_generation_client.py tests/test_generation_executor.py tests/test_query_understanding_config.py
git commit -m "feat: apply request budgets to rerank and llm calls"
```

## Task 6: Answer Workflow Root Control And Streaming Cancellation

**Files:**
- Modify: `rag_modules/app/services/answer_models.py`
- Modify: `rag_modules/app/services/answer_workflow.py`
- Modify: `rag_modules/app/services/answer_pipeline.py`
- Modify: `rag_modules/interfaces/api/services/serving_streams.py`
- Modify: `rag_modules/interfaces/api/services/serving.py`
- Test: `tests/test_answer_workflow.py`
- Test: `tests/test_api_app.py`

- [ ] **Step 1: Write failing answer workflow propagation test**

Add to `tests/test_answer_workflow.py`.

```python
class _ControlCapturingRouter:
    def __init__(self) -> None:
        self.controls = []

    def route_with_trace(self, question, top_k, *, control=None):
        self.controls.append(control)
        return _build_resolution(
            question,
            documents=[EvidenceDocument(content="doc", recipe_name="recipe")],
        ), RouteSnapshot(query=question, requested_top_k=top_k)


class _ControlCapturingGeneration:
    def __init__(self) -> None:
        self.controls = []

    def generate_answer_with_trace_from_context(self, answer_context, *, control=None):
        self.controls.append(control)
        return "answer", GenerationSnapshot(status="success")


def test_answer_workflow_uses_one_root_control_for_route_and_generation() -> None:
    router = _ControlCapturingRouter()
    generation = _ControlCapturingGeneration()
    workflow = AnswerWorkflow(
        build_test_config(),
        query_router=router,
        generation_module=generation,
        query_tracer=None,
    )

    result = workflow.answer_question("tofu")

    assert result.answer == "answer"
    assert router.controls[0] is generation.controls[0]
    assert router.controls[0].scope == "answer"
```

- [ ] **Step 2: Write failing streaming cancellation test**

Add to `tests/test_api_app.py` or extend the existing stream shutdown tests:

```python
def test_stream_consumer_close_cancels_answer_request_control(self) -> None:
    system = _StreamingControlCapturingSystem()
    service = GraphRAGServingApiService(system=system, config=build_test_config())

    stream = service.answer_question_stream("slow stream")
    first = next(stream)
    stream.close()

    assert system.last_control.cancelled
    assert system.last_control.reason == "stream_consumer_closed"
```

If the existing stream API does not expose the control directly, implement `_StreamingControlCapturingSystem.answer_question_response(..., control=None)` and assert captured control after closing the generator.

- [ ] **Step 3: Run tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py tests/test_api_app.py -q
```

Expected: fail because answer workflow does not create/pass root control.

- [ ] **Step 4: Add control to AnswerPipelineState**

Modify `rag_modules/app/services/answer_models.py`.

```python
from ...runtime import RequestControl

@dataclass
class AnswerPipelineState:
    ...
    request_control: RequestControl | None = None
```

- [ ] **Step 5: Create root control in AnswerWorkflow**

Modify `rag_modules/app/services/answer_workflow.py`.

```python
from ...runtime import RequestControl


def _new_request_control(self) -> RequestControl:
    generation = self.config.generation
    budget = float(getattr(generation, "generation_latency_budget_seconds", 30.0) or 30.0)
    return RequestControl.for_timeout(budget, scope="answer")
```

In `answer_question()`:

```python
request_control = self._new_request_control()
state = AnswerPipelineState(..., request_control=request_control)
```

In exception handling:

```python
request_control.cancel("answer_workflow_failed")
```

Do not expose the control in public response models.

- [ ] **Step 6: Pass control through AnswerPipelineService**

Modify `rag_modules/app/services/answer_pipeline.py`.

```python
control = state.request_control
if control is not None:
    control.raise_if_cancelled()
resolution, route_trace = self.router_traces.route_with_trace(
    state.question,
    self.top_k,
    control=control,
)
...
state.answer, state.generation_trace = self._generate_answer(..., control=control)
```

Change `_generate_answer()` to accept `control` and pass it into generation trace adapter.

- [ ] **Step 7: Thread control through serving stream close**

Modify `rag_modules/interfaces/api/services/serving.py` so internal calls can accept an optional control if tests/system protocols need it:

```python
def answer_question(..., control=None):
    return self.system.answer_question_response(..., control=control)
```

Modify `rag_modules/interfaces/api/services/serving_streams.py`:

```python
from ....runtime import RequestControl

control = RequestControl.for_timeout(
    float(getattr(self._config.generation, "generation_latency_budget_seconds", 30.0)),
    scope="answer.stream",
)
```

Pass `control=control` to answer execution. In the generator `finally` block:

```python
if stream_closed.is_set():
    control.cancel("stream_consumer_closed")
```

If serving streams delegate through `GraphRAGServingApiService.answer_question`, pass the control into that method rather than creating a second one in `AnswerWorkflow`.

- [ ] **Step 8: Run answer/API tests**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py tests/test_api_app.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```powershell
git add rag_modules/app/services/answer_models.py rag_modules/app/services/answer_workflow.py rag_modules/app/services/answer_pipeline.py rag_modules/interfaces/api/services/serving.py rag_modules/interfaces/api/services/serving_streams.py tests/test_answer_workflow.py tests/test_api_app.py
git commit -m "feat: create answer request controls"
```

## Task 7: Contract Cleanup And Full Verification

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: any tests/fakes still using removed internal signatures
- Verify: all touched runtime modules

- [ ] **Step 1: Add cleanup ratchet tests**

Add to `tests/test_public_surface_boundaries.py`.

```python
from pathlib import Path


def test_online_runtime_does_not_use_dual_shape_retrieval_signatures() -> None:
    files = [
        Path("rag_modules/retrieval/hybrid_executor.py"),
        Path("rag_modules/retrieval/hybrid_search_service.py"),
        Path("rag_modules/graph/rag_retrieval.py"),
        Path("rag_modules/routing/strategies/graph.py"),
        Path("rag_modules/routing/strategies/combined.py"),
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "request_or_query" not in source
    assert "hasattr(" not in source
    assert "graph_rag_evidence_search(" not in source


def test_future_cancel_is_not_reported_as_backend_cancellation() -> None:
    source = Path("rag_modules/routing/strategies/combined.py").read_text(encoding="utf-8")

    assert "cancel_observed_branches" in source
    assert "future.cancel()" not in source
```

If `_cancel_future()` remains for executor cleanup, make the assertion precise:

```python
assert '"cancelled_branches"' not in source
```

The trace should report requested and observed request-control cancellation, not future cancellation.

- [ ] **Step 2: Run public boundary ratchets and fix remaining old paths**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: fail until all old signatures and `hasattr` fallbacks are removed. Update fakes and production callers directly; do not add compatibility wrappers.

- [ ] **Step 3: Run focused subsystem tests**

Run:

```powershell
python -m pytest tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
python -m pytest tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py tests/test_model_client_ports.py -q
python -m pytest tests/test_graph_retrieval_executor.py -q
python -m pytest tests/test_generation_client.py tests/test_generation_executor.py -q
python -m pytest tests/test_answer_workflow.py tests/test_api_app.py -q
```

Expected: all pass.

- [ ] **Step 4: Run full tests**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Run formatting/static checks**

Run:

```powershell
pre-commit run --all-files
```

Expected: all hooks pass. If Ruff modifies files, inspect `git diff`, then rerun focused tests impacted by modified files.

- [ ] **Step 6: Commit cleanup**

```powershell
git add rag_modules tests
git commit -m "test: ratchet request control runtime contracts"
```

## Final Verification Checklist

- [ ] `RequestControl` child controls use tighter deadlines and shared cancellation.
- [ ] `RetrievalRequest.to_dict()` never serializes raw synchronization objects.
- [ ] Combined route cancels timed-out branch controls.
- [ ] Combined route trace distinguishes timeout, cancellation requested, and cancellation observed.
- [ ] Hybrid candidate sources receive full `RetrievalRequest`.
- [ ] Milvus embedding/search use remaining request budget.
- [ ] Neo4j query execution receives remaining request budget.
- [ ] Rerank receives remaining request budget and degrades safely.
- [ ] Query planner and generation LLM calls use remaining request budget.
- [ ] Streaming generation checks cancellation between chunks.
- [ ] Answer workflow creates one root control and passes it to route and generation.
- [ ] Public answer API response shapes remain stable.
- [ ] Focused tests pass.
- [ ] Full `python -m pytest -q` passes.
- [ ] `pre-commit run --all-files` passes.
