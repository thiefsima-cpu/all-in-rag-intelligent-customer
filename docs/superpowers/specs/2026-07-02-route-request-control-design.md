# Route Request Control Design

## Goal

Make online answer execution cancellation and latency budgets real runtime
contracts instead of executor wait-time behavior. Combined-route branch timeout
must propagate down to traditional retrieval, graph retrieval, rerank, Milvus,
Neo4j, and LLM provider calls so already-running work can stop cooperatively or
use provider-level timeouts.

This is an internal runtime contract rewrite, not a compatibility patch. Public
HTTP response shapes should stay stable, but internal route, retrieval, graph,
post-processing, and generation ports should move to one explicit request
control model.

## Scope

This design covers:

- Answer runtime request control creation and propagation.
- Routing workflow and route execution strategy contracts.
- Combined route branch budget and cancellation propagation.
- Hybrid retrieval candidate generation, Milvus vector search, and parent or
  neighbor enrichment checkpoints.
- Graph retrieval, Neo4j query execution, graph post-processing, and graph
  reasoning checkpoints.
- Retrieval post-processing rerank calls.
- Query-planner LLM calls and generation LLM calls, including streaming.
- Focused tests that prove controls reach backend adapters.

This design does not change public FastAPI response DTOs, policy bundle JSON
schema, build pipeline execution, or offline evaluation semantics except where
tests need deterministic request-control fixtures.

## Current Problem

`CombinedRouteStrategy` currently enforces branch timeout by waiting on two
`Future` objects. When a branch exceeds its wait budget, the route can return a
degraded result, but `Future.cancel()` cannot stop a task that is already
running. The traditional branch may still be inside embedding, Milvus, Neo4j
neighbor enrichment, or rerank work. The graph branch may still be inside Neo4j
queries or graph reasoning. LLM calls already use configured timeouts in some
paths, but query planning and generation do not share a single request-level
budget or cancellation signal.

The root cause is that the request budget is not part of the runtime contract.
It is local state in the route strategy wait loop.

## Recommended Approach

Add a first-class `RequestControl` runtime object and propagate it through all
online answer work.

`RequestControl` owns:

- `deadline`: monotonic absolute deadline for the current request or branch.
- `cancel_event`: shared cancellation signal.
- `reason`: stable cancellation or budget-exhaustion reason.
- `scope`: traceable name such as `answer`, `combined.graph`, or
  `combined.traditional`.
- `remaining_seconds(minimum=0.1)`: remaining provider timeout.
- `raise_if_cancelled()`: cooperative checkpoint.
- `cancel(reason)`: mark the control as cancelled.
- `child(timeout_seconds, scope)`: derive a child control with a tighter
  deadline and the same root cancellation signal.
- `to_trace_details()`: safe JSON-shaped observability summary.

Add focused exceptions:

- `RequestCancelled`
- `RequestBudgetExceeded`

These exceptions are runtime control outcomes. Retrieval layers may either
propagate them to the orchestrator or convert them into existing degraded route
metadata when fallback behavior is intended.

## Boundary Rules

Internal online runtime contracts use explicit request objects and controls.

Required changes:

- `RetrievalRequest` carries `control: RequestControl | None`.
- `RetrievalRequest.to_dict()` never serializes the control object. It emits
  only safe control details.
- `HybridRetrievalPort.hybrid_evidence_search()` accepts a
  `RetrievalRequest`.
- `GraphRAGRetrievalPort.graph_rag_evidence_search_with_trace()` accepts a
  `RetrievalRequest`.
- Candidate sources receive `RetrievalRequest` instead of decomposed
  `query/top_k` arguments.
- Rerank and LLM ports accept explicit timeout or control parameters.

Removed internal compatibility patterns:

- No `str | RetrievalRequest` dual-shape retrieval entry point in the touched
  runtime path.
- No `hasattr(..., "graph_rag_evidence_search_with_trace")` fallback in route
  strategies.
- No new adapter APIs that silently ignore control.
- `Future.cancel()` is retained only as executor cleanup, not as evidence that
  backend work stopped.

## Architecture

### Answer Runtime

`AnswerWorkflow` creates the root `RequestControl` for every answer operation.
The default budget comes from existing configured answer or generation budgets
where available. If a route request metadata field such as
`request_budget_seconds` is present, it becomes a tighter request deadline.

Streaming answer execution should connect consumer shutdown or disconnect to
`control.cancel("stream_consumer_closed")`. Runtime shutdown should cancel
in-flight answer controls before waiting on worker completion.

### Routing Workflow

`RoutingWorkflowService.route_with_trace()` accepts an optional
`RequestControl`. If absent, it creates one from retrieval request metadata.
The control is stored on the route `RetrievalRequest` and copied into derived
requests.

`SearchOrchestrator.execute()` and `post_process()` check the control before
each major stage:

- query understanding and route plan handoff
- strategy execution
- post-processing and rerank
- result assembly

Trace details include request-control summary, whether cancellation was
requested, and the remaining budget when the route finished.

### Combined Route

`CombinedRouteStrategy` derives branch controls:

- `combined.traditional`
- `combined.graph`

Each branch receives a request carrying its child control. The route wait loop
still uses a shared deadline to return quickly, but on timeout it calls
`branch_control.cancel("combined_branch_timeout")`. Timed-out branches are
reported separately from branches that actually observed cancellation.

Combined-route stage details include:

- `branch_timeout_seconds`
- `timed_out_branches`
- `cancel_requested_branches`
- `cancel_observed_branches`
- `traditional_control`
- `graph_control`

### Hybrid Retrieval And Milvus

`HybridSearchService` checks the request control before candidate generation,
after each candidate source, before parent enrichment, and before returning.

`VectorCandidateSource` passes the full `RetrievalRequest` into
`HybridRetrievalRuntime.vector_candidates()`.

`VectorRetriever.search()` receives `RetrievalRequest`, checks control, calls
Milvus with a provider timeout derived from `control.remaining_seconds()`, and
checks control again before Neo4j neighbor enrichment.

`MilvusIndexConstructionModule.similarity_search()` accepts a required
`RetrievalRequest` in the online runtime path. It uses:

- the request query
- the effective candidate count
- request filters
- `control.remaining_seconds()` for embedding HTTP timeout when the embedding
  client supports per-call timeout
- `control.remaining_seconds()` for `client.search(..., timeout=...)`

If a third-party client lacks a direct cancellation hook, the code still checks
control immediately before and after the call and uses the smallest available
provider timeout.

### Graph Retrieval And Neo4j

`GraphRAGRetrieval` and `GraphRetrievalExecutor.execute_with_trace()` accept a
`RetrievalRequest` carrying control. The executor checks control before context
resolution, retrieval-plan build, Neo4j execution, post-processing, and trace
finalization.

`GraphEvidenceOrchestrator.retrieve()` passes control into graph-plan execution
and subgraph extraction. Graph reasoning checks control before expensive
reasoning steps.

`GraphQueryExecutor` methods accept control and pass a per-query timeout to
Neo4j. Neo4j timeout should use the driver-supported query timeout path in the
current dependency version. Every query method checks control before opening a
session and after records are collected.

### Rerank

`RerankClientPort.rerank()` accepts `timeout_seconds` or `control`. The
DashScope rerank client uses `control.remaining_seconds()` for the HTTP request
timeout.

When rerank observes cancellation or budget exhaustion, `RetrievalPostProcessor`
returns the original document order and records a degraded rerank detail instead
of blocking the whole route.

### LLM Clients

`LLMClientPort.create_completion()` and `StreamingLLMClientPort.stream_prompt()`
accept `control`. Provider timeout is always:

`min(configured_timeout, control.remaining_seconds())`

Query planning, answer generation, and streaming generation use the same
control. Streaming generation checks the control before the provider request and
between emitted chunks.

## Error Handling

Request-control exceptions map to existing degraded behavior where fallback is
part of the route contract:

- Combined graph timeout with hybrid result yields
  `combined_graph_timeout_to_hybrid`.
- Combined traditional timeout with graph result yields
  `combined_hybrid_timeout_to_graph`.
- Both branches timeout yields `combined_branches_timeout`.
- Rerank timeout returns original ranking and records rerank degradation.
- LLM timeout follows existing generation fallback behavior.

When no fallback can produce a valid answer, the answer workflow returns the
existing answer failure surface. Public error payloads should remain stable.

## Observability

Trace payloads should expose safe request-control diagnostics:

- scope
- cancelled
- cancel reason
- budget exhausted
- remaining milliseconds at stage completion
- timeout source, such as `request_budget_seconds` or
  `combined_branch_timeout_seconds`

The trace must not expose raw synchronization objects, provider clients,
request secrets, or stack traces.

## Testing

Use TDD for each slice.

Focused tests:

- `RequestControl` child controls share cancellation signal and use tighter
  deadlines.
- `RetrievalRequest.to_dict()` serializes safe control details only.
- Combined route derives separate branch controls and timed-out branches receive
  cancellation.
- A fake running traditional branch observes `combined_branch_timeout`.
- A fake running graph branch observes `combined_branch_timeout`.
- Hybrid candidate sources receive `RetrievalRequest` with control.
- Vector retrieval passes a budget-derived timeout to Milvus search.
- Milvus embedding and search calls use the remaining budget when supported.
- Graph query executor passes budget-derived timeout to Neo4j.
- Graph retrieval stops between plan execution and reasoning when cancelled.
- Rerank receives the remaining budget and degrades on control timeout.
- Query planner LLM and generation LLM calls use control-derived timeouts.
- Streaming generation stops when the control is cancelled between chunks.
- Public API answer response tests continue to pass without response shape
  changes.

Recommended narrow checks:

- `python -m pytest tests/test_route_execution_strategies.py -q`
- `python -m pytest tests/test_hybrid_search_service.py tests/test_hybrid_retrieval_runtime.py -q`
- `python -m pytest tests/test_graph_retrieval_executor.py -q`
- `python -m pytest tests/test_generation_client.py tests/test_generation_executor.py -q`
- `python -m pytest tests/test_answer_workflow.py tests/test_api_app.py -q`

Before completion, run:

- `python -m pytest -q`
- `pre-commit run --all-files` or the equivalent Ruff checks

## Migration Strategy

Implement in focused review chunks:

1. Add `RequestControl`, exceptions, serialization summary, and tests.
2. Rewrite routing and combined strategy contracts around request control.
3. Rewrite hybrid retrieval and Milvus vector search contracts.
4. Rewrite graph retrieval and Neo4j query execution contracts.
5. Rewrite rerank and LLM client contracts.
6. Wire answer workflow, streaming cancellation, and shutdown cancellation.
7. Remove obsolete compatibility paths and add public-surface regression tests.

Each chunk removes the old internal contract in its touched slice before moving
to the next. No chunk should leave a permanent dual API.

## Acceptance Criteria

- Combined-route branch timeout requests cancellation on already-running branch
  work.
- Milvus, Neo4j, rerank, and LLM calls receive request or branch budget.
- Runtime code uses explicit request-control contracts, not best-effort
  `Future.cancel()` semantics.
- Internal route, retrieval, graph, rerank, and LLM ports no longer expose
  mixed old/new call shapes in the online runtime path.
- Public answer API response shapes remain stable.
- Focused tests, full pytest, and formatting checks pass.
