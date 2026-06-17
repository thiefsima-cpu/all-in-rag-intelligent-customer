# Retrieval Candidate Source Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make hybrid retrieval candidate generation tolerate per-source failures with independent circuit breakers, degraded trace details, and same-query fallback source skipping.

**Architecture:** Keep resilience centralized in `RetrievalCandidateGenerator`. Expose candidate diagnostics through `CandidateSet.to_stage_details()`, let hybrid search return request-scoped trace details when asked, and propagate `skip_candidate_sources` through route fallback requests without changing the public document-returning APIs.

**Tech Stack:** Python 3.11, dataclasses, existing `CircuitBreaker`, unittest, pytest, existing retrieval/routing models.

---

## File Structure

- Modify: `rag_modules/retrieval/candidate_generator.py` - add per-source circuit state, degraded detail records, request skip handling, and stage-detail serialization.
- Modify: `rag_modules/retrieval/candidate_sources.py` - remove vector-only exception swallowing so all source failures use generator policy.
- Modify: `rag_modules/retrieval/hybrid_search_service.py` - add request-scoped `hybrid_evidence_search_with_trace()` and reuse it from `hybrid_evidence_search()`.
- Modify: `rag_modules/retrieval/hybrid_executor.py` - delegate `hybrid_evidence_search_with_trace()`.
- Modify: `rag_modules/retrieval/hybrid_facade.py` - expose `hybrid_evidence_search_with_trace()` on the public module facade.
- Modify: `rag_modules/routing/execution_strategies.py` - collect candidate diagnostics from hybrid calls and attach them to route stage details.
- Modify: `rag_modules/routing/search_orchestrator.py` - propagate known degraded candidate sources into exception fallback request metadata.
- Modify: `tests/test_retrieval_candidate_generator.py` - add generator resilience tests first.
- Modify: `tests/test_hybrid_search_service.py` - add hybrid trace-details test first.
- Modify: `tests/test_route_execution_strategies.py` - add route stage diagnostics and skip propagation tests first.
- Modify: `tests/test_route_search_orchestrator.py` - add exception fallback skip propagation test first.

### Task 1: Candidate Generator Source Isolation

**Files:**
- Modify: `tests/test_retrieval_candidate_generator.py`
- Modify: `rag_modules/retrieval/candidate_generator.py`
- Modify: `rag_modules/retrieval/candidate_sources.py`

- [ ] **Step 1: Write failing generator tests**

Add source helpers to `tests/test_retrieval_candidate_generator.py`:

```python
class _FailingSource:
    def __init__(self, spec: CandidateSourceSpec, exc: Exception | None = None) -> None:
        self.spec = spec
        self.exc = exc or TimeoutError(f"{spec.name} timeout")
        self.requests = []

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        raise self.exc
```

Add these tests to `RetrievalCandidateGeneratorTests`:

```python
    def test_generate_degrades_failed_source_and_continues_later_sources(self) -> None:
        failing = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            TimeoutError("vector timed out"),
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(sources=[failing, bm25])

        candidate_set = generator.generate(
            RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)
        )

        self.assertEqual(candidate_set.stats, {"vector": 0, "bm25": 1})
        self.assertEqual(candidate_set.degraded_sources, ["vector"])
        self.assertEqual(candidate_set.degraded_details[0]["reason"], "exception")
        self.assertEqual(candidate_set.degraded_details[0]["error_type"], "TimeoutError")
        self.assertEqual(candidate_set.degraded_details[0]["circuit_state"], "open")
        self.assertEqual(len(bm25.requests), 1)
```

```python
    def test_open_circuit_skips_only_the_failed_source(self) -> None:
        vector = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            )
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(sources=[vector, bm25])
        request = RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)

        generator.generate(request)
        second = generator.generate(request)

        self.assertEqual(len(vector.requests), 1)
        self.assertEqual(len(bm25.requests), 2)
        self.assertEqual(second.degraded_details[0]["reason"], "circuit_open")
        self.assertEqual(second.bm25_docs[0].recipe_name, "B")
```

```python
    def test_request_skip_metadata_does_not_touch_source_or_circuit(self) -> None:
        vector = _StubSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            [EvidenceDocument(content="vector-doc", recipe_name="V")],
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        request = RetrievalRequest.from_inputs(
            query="recommend tofu",
            top_k=2,
            candidate_k=4,
            metadata={"skip_candidate_sources": ["vector"]},
        )
        generator = RetrievalCandidateGenerator(sources=[vector, bm25])

        candidate_set = generator.generate(request)

        self.assertEqual(len(vector.requests), 0)
        self.assertEqual(len(bm25.requests), 1)
        self.assertEqual(candidate_set.vector_docs, [])
        self.assertEqual(candidate_set.degraded_details[0]["reason"], "request_skip")
        self.assertEqual(candidate_set.to_stage_details()["candidate_counts"]["bm25"], 1)
        self.assertEqual(candidate_set.to_stage_details()["degraded_sources"], ["vector"])
```

- [ ] **Step 2: Run generator tests and verify RED**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py -q
```

Expected: FAIL because `CandidateSet.degraded_sources`, `degraded_details`, `to_stage_details()`, and generator-level circuiting do not exist yet.

- [ ] **Step 3: Implement generator-level degraded details and circuiting**

In `rag_modules/retrieval/candidate_generator.py`, import the existing breaker:

```python
from ..infra.resilience import CircuitBreaker, CircuitOpenError
```

Add the metadata constant and degradation record:

```python
SKIP_CANDIDATE_SOURCES_METADATA_KEY = "skip_candidate_sources"


@dataclass(frozen=True, slots=True)
class CandidateSourceDegradation:
    spec: CandidateSourceSpec
    reason: str
    error_type: str = ""
    message: str = ""
    circuit_state: str = ""
    failure_count: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.spec.name,
            "rank_name": self.spec.rank_name,
            "reason": self.reason,
            "error_type": self.error_type,
            "message": self.message,
            "circuit_state": self.circuit_state,
            "failure_count": self.failure_count,
        }
```

Extend `CandidateSet`:

```python
    degraded: List[CandidateSourceDegradation] = field(default_factory=list)

    @property
    def degraded_sources(self) -> List[str]:
        return [item.spec.name for item in self.degraded]

    @property
    def degraded_details(self) -> List[Dict[str, object]]:
        return [item.to_dict() for item in self.degraded]

    def to_stage_details(self) -> Dict[str, object]:
        return {
            "candidate_counts": self.stats,
            "degraded_sources": self.degraded_sources,
            "degraded_candidates": self.degraded_details,
        }
```

Update `RetrievalCandidateGenerator.__init__()`:

```python
        source_failure_threshold: int = 1,
        source_recovery_timeout_seconds: float = 30.0,
```

Create a breaker map keyed by source name:

```python
        self._source_breakers = {
            source.spec.name: CircuitBreaker(
                failure_threshold=source_failure_threshold,
                recovery_timeout_seconds=source_recovery_timeout_seconds,
            )
            for source in self.sources
        }
```

Replace direct source calls in `generate()` with an isolated helper:

```python
        skipped_sources = self._request_skipped_sources(effective_request)
        degraded: List[CandidateSourceDegradation] = []
        for source in self.sources:
            documents, degradation = self._retrieve_source(
                source,
                effective_request,
                skipped_sources=skipped_sources,
            )
            if degradation:
                degraded.append(degradation)
            results.append(CandidateSourceResult(spec=source.spec, documents=documents))
        candidate_set = CandidateSet(source_results=results, degraded=degraded)
```

Add helpers:

```python
    @staticmethod
    def _request_skipped_sources(request: RetrievalRequest) -> set[str]:
        raw_sources = request.metadata.get(SKIP_CANDIDATE_SOURCES_METADATA_KEY, [])
        if isinstance(raw_sources, str):
            raw_sources = [raw_sources]
        return {str(item).strip() for item in (raw_sources or []) if str(item).strip()}

    def _retrieve_source(
        self,
        source: RetrievalCandidateSource,
        request: RetrievalRequest,
        *,
        skipped_sources: set[str],
    ) -> tuple[List[EvidenceDocument], CandidateSourceDegradation | None]:
        breaker = self._source_breakers[source.spec.name]
        if source.spec.name in skipped_sources:
            return [], self._degradation(source.spec, reason="request_skip", breaker=breaker)
        try:
            breaker.before_call()
        except CircuitOpenError as exc:
            return [], self._degradation(
                source.spec,
                reason="circuit_open",
                breaker=breaker,
                error=exc,
            )
        try:
            documents = self._normalize_source_documents(source.retrieve(request), spec=source.spec)
        except Exception as exc:
            breaker.record_failure()
            logger.warning("Candidate source %s degraded: %s", source.spec.name, exc)
            return [], self._degradation(
                source.spec,
                reason="exception",
                breaker=breaker,
                error=exc,
            )
        breaker.record_success()
        return documents, None

    @staticmethod
    def _degradation(
        spec: CandidateSourceSpec,
        *,
        reason: str,
        breaker: CircuitBreaker,
        error: Exception | None = None,
    ) -> CandidateSourceDegradation:
        snapshot = breaker.snapshot()
        return CandidateSourceDegradation(
            spec=spec,
            reason=reason,
            error_type=type(error).__name__ if error else "",
            message=str(error or ""),
            circuit_state=snapshot.state,
            failure_count=snapshot.failure_count,
        )
```

In `rag_modules/retrieval/candidate_sources.py`, remove the `try/except` from `VectorCandidateSource.retrieve()` so it simply calls `runtime.vector_candidates(...)`.

- [ ] **Step 4: Run generator tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py -q
```

Expected: PASS.

### Task 2: Hybrid Search Request-Scoped Trace Details

**Files:**
- Modify: `tests/test_hybrid_search_service.py`
- Modify: `rag_modules/retrieval/hybrid_search_service.py`
- Modify: `rag_modules/retrieval/hybrid_executor.py`
- Modify: `rag_modules/retrieval/hybrid_facade.py`

- [ ] **Step 1: Write the failing hybrid trace test**

In `_StubCandidateGenerator.generate()` in `tests/test_hybrid_search_service.py`, return a degraded `CandidateSet`:

```python
            degraded=[
                CandidateSourceDegradation(
                    spec=CandidateSourceSpec(
                        name="vector",
                        rank_name="vector",
                        search_method="vector",
                        search_type="vector_enhanced",
                        rank_order=2,
                    ),
                    reason="exception",
                    error_type="TimeoutError",
                    message="vector timed out",
                    circuit_state="open",
                    failure_count=1,
                )
            ],
```

Add the import:

```python
from rag_modules.retrieval.candidate_generator import CandidateSourceDegradation
```

Add this test:

```python
    def test_hybrid_evidence_search_with_trace_returns_candidate_stage_details(self) -> None:
        config = build_test_config({"retrieval": {"enable_parent_doc_retrieval": False}})
        runtime = _FakeRuntime()
        generator = _StubCandidateGenerator()
        service = HybridSearchService(
            config=config,
            retrieval_profile=_FakeRetrievalProfile(),
            runtime=runtime,
            fusion_ranker=_FakeFusionRanker(),
            constraint_retriever=SimpleNamespace(),
            candidate_generator=generator,
        )

        docs, details = service.hybrid_evidence_search_with_trace(
            "recommend tofu dishes",
            top_k=2,
        )

        self.assertEqual([doc.recipe_name for doc in docs], ["C", "V"])
        self.assertEqual(details["candidate_counts"]["constraints"], 1)
        self.assertEqual(details["degraded_sources"], ["vector"])
        self.assertEqual(details["degraded_candidates"][0]["reason"], "exception")
```

- [ ] **Step 2: Run hybrid tests and verify RED**

Run:

```powershell
python -m pytest tests/test_hybrid_search_service.py -q
```

Expected: FAIL because `hybrid_evidence_search_with_trace()` does not exist yet.

- [ ] **Step 3: Implement hybrid trace-returning API**

In `HybridSearchService`, add:

```python
    def hybrid_evidence_search_with_trace(
        self,
        request_or_query: Union[str, RetrievalRequest],
        *,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> tuple[List[EvidenceDocument], dict]:
        request = self.prepare_hybrid_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )
        final_docs, details = self._execute_hybrid_request(request)
        return final_docs, details
```

Extract the body of `hybrid_evidence_search()` into `_execute_hybrid_request(request)`:

```python
    def _execute_hybrid_request(self, request: RetrievalRequest) -> tuple[List[EvidenceDocument], dict]:
        effective_constraints = request.effective_constraints
        candidates = self.candidate_generator.generate(request)
        final_docs = self.fusion_ranker.rrf_merge(
            ranked_lists=candidates.ranked_lists,
            top_k=request.top_k,
        )
        if self.retrieval.enable_parent_doc_retrieval:
            final_docs = self.runtime.attach_parent_evidence_documents(
                final_docs,
                top_n=request.top_k
                if effective_constraints and effective_constraints.has_constraints()
                else None,
            )
        details = candidates.to_stage_details()
        logger.info(
            "Hybrid retrieval complete: constraints=%s dual=%s vector=%s bm25=%s final=%s degraded=%s",
            candidates.stats.get("constraints", 0),
            candidates.stats.get("dual", 0),
            candidates.stats.get("vector", 0),
            candidates.stats.get("bm25", 0),
            len(final_docs),
            candidates.degraded_sources,
        )
        return final_docs, details
```

Change `hybrid_evidence_search()` to:

```python
        final_docs, _details = self.hybrid_evidence_search_with_trace(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )
        return final_docs
```

Delegate from `HybridRetrievalExecutor`:

```python
    def hybrid_evidence_search_with_trace(self, request_or_query: Union[str, RetrievalRequest], **kwargs):
        return self.search_service.hybrid_evidence_search_with_trace(request_or_query, **kwargs)
```

Expose from `HybridRetrievalModule`:

```python
    def hybrid_evidence_search_with_trace(self, request_or_query: Union[str, RetrievalRequest], **kwargs):
        return self._executor.hybrid_evidence_search_with_trace(request_or_query, **kwargs)
```

- [ ] **Step 4: Run hybrid tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hybrid_search_service.py -q
```

Expected: PASS.

### Task 3: Route Stage Details And Fallback Source Skipping

**Files:**
- Modify: `tests/test_route_execution_strategies.py`
- Modify: `tests/test_route_search_orchestrator.py`
- Modify: `rag_modules/routing/execution_strategies.py`
- Modify: `rag_modules/routing/search_orchestrator.py`

- [ ] **Step 1: Write failing route strategy tests**

Update `_FakeTraditionalRetrieval` in `tests/test_route_execution_strategies.py`:

```python
    def __init__(self, hybrid_docs=None, *, trace_details=None) -> None:
        self.hybrid_docs = list(hybrid_docs or [])
        self.trace_details = dict(trace_details or {})
        self.hybrid_calls = []
        self.enrich_calls = []

    def hybrid_evidence_search_with_trace(self, request):
        self.hybrid_calls.append(request)
        return list(self.hybrid_docs), dict(self.trace_details)
```

Add this test:

```python
    def test_hybrid_strategy_records_candidate_trace_details(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="hybrid", recipe_name="Mapo Tofu")],
                trace_details={
                    "candidate_counts": {"vector": 0, "bm25": 1},
                    "degraded_sources": ["vector"],
                    "degraded_candidates": [{"source": "vector", "reason": "exception"}],
                },
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=_FakeRetrievalProfile(),
        )

        outcome = HybridRouteStrategy().execute(
            _request(
                query="recommend tofu dishes",
                top_k=2,
                strategy=SearchStrategy.HYBRID_TRADITIONAL,
            ),
            services=services,
        )

        self.assertEqual(outcome.stages[0].details["degraded_sources"], ["vector"])
        self.assertEqual(outcome.stages[0].details["candidate_counts"]["bm25"], 1)
```

Add this graph supplement skip test:

```python
    def test_graph_supplement_preserves_existing_skip_candidate_metadata(self) -> None:
        services = RouteRetrievalServices(
            traditional_retrieval=_FakeTraditionalRetrieval(
                [EvidenceDocument(content="supplement", recipe_name="Supplement")],
            ),
            graph_rag_retrieval=_FakeGraphRetrieval(
                [EvidenceDocument(content="graph", recipe_name="Graph Dish")]
            ),
            retrieval_profile=_FakeRetrievalProfile(),
        )
        req = _request(
            query="why tofu",
            top_k=2,
            strategy=SearchStrategy.GRAPH_RAG,
        )
        req.retrieval_request = req.retrieval_request.copy_with(
            metadata={"skip_candidate_sources": ["vector"]}
        )

        GraphRouteStrategy().execute(req, services=services)

        self.assertEqual(
            services.traditional_retrieval.hybrid_calls[0].metadata["skip_candidate_sources"],
            ["vector"],
        )
```

- [ ] **Step 2: Write failing exception fallback skip test**

In `tests/test_route_search_orchestrator.py`, update `_FakeTraditionalRetrieval.hybrid_evidence_search()` to keep requests:

```python
    def __init__(self, hybrid_docs=None) -> None:
        self.hybrid_docs = list(hybrid_docs or [])
        self.hybrid_calls = []

    def hybrid_evidence_search(self, request):
        self.hybrid_calls.append(request)
        return list(self.hybrid_docs)
```

Add this test:

```python
    def test_exception_fallback_skips_candidate_sources_degraded_in_prior_stage(self) -> None:
        traditional = _FakeTraditionalRetrieval(
            [EvidenceDocument(content="fallback", recipe_name="Mapo Tofu")]
        )
        orchestrator = RouteSearchOrchestrator(
            traditional_retrieval=traditional,
            graph_rag_retrieval=_FakeGraphRetrieval(),
            retrieval_profile=SimpleNamespace(candidates=SimpleNamespace()),
            post_processor=_FakePostProcessor(),
        )
        plan = QueryPlan(query="recommend tofu dishes")
        request = RouteExecutionRequest(
            query="recommend tofu dishes",
            top_k=2,
            analysis=QueryAnalysis(recommended_strategy=SearchStrategy.COMBINED),
            retrieval_request=RouteSearchOrchestrator.build_retrieval_request(
                query="recommend tofu dishes",
                top_k=2,
                strategy="combined",
                query_plan=plan,
            ),
            constraints=QueryConstraints(),
            query_plan=plan,
        )
        trace = RouteTraceRecorder(query=request.query, requested_top_k=request.top_k)
        trace.add_stage(
            "hybrid",
            start_time=0.0,
            documents=[],
            details={"degraded_sources": ["vector"]},
        )

        orchestrator.execute_exception_fallback(
            request,
            trace=trace,
            error=RuntimeError("post-process failed"),
        )

        self.assertEqual(
            traditional.hybrid_calls[0].metadata["skip_candidate_sources"],
            ["vector"],
        )
```

- [ ] **Step 3: Run route tests and verify RED**

Run:

```powershell
python -m pytest tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
```

Expected: FAIL because route strategies still call `hybrid_evidence_search()` and exception fallback does not derive skip metadata.

- [ ] **Step 4: Implement route diagnostics and skip propagation**

In `rag_modules/routing/execution_strategies.py`, add helpers:

```python
def hybrid_evidence_search_with_stage_details(traditional_retrieval, request):
    search_with_trace = getattr(traditional_retrieval, "hybrid_evidence_search_with_trace", None)
    if callable(search_with_trace):
        docs, details = search_with_trace(request)
        return list(docs), dict(details or {})
    return list(traditional_retrieval.hybrid_evidence_search(request)), {}
```

Use it in `HybridRouteStrategy`, `GraphRouteStrategy`, and `CombinedRouteStrategy` wherever hybrid retrieval is called. Pass `details=hybrid_details` into `RouteExecutionStageResult` for `hybrid`, `hybrid_fallback`, and `hybrid_supplement`.

In `rag_modules/routing/search_orchestrator.py`, collect degraded source names:

```python
    @staticmethod
    def _degraded_candidate_sources_from_trace(trace: RouteTraceRecorder) -> List[str]:
        sources: List[str] = []
        for stage in trace.snapshot.stages.values():
            for source in stage.details.get("degraded_sources") or []:
                normalized = str(source).strip()
                if normalized:
                    sources.append(normalized)
        return list(dict.fromkeys(sources))
```

Pass `trace` into `_build_exception_fallback_outcome()` and copy request metadata:

```python
        degraded_sources = self._degraded_candidate_sources_from_trace(trace)
        fallback_request = request.retrieval_request
        if degraded_sources:
            metadata = dict(fallback_request.metadata or {})
            metadata["skip_candidate_sources"] = degraded_sources
            fallback_request = fallback_request.copy_with(metadata=metadata)
        evidence_documents = self.traditional_retrieval.hybrid_evidence_search(fallback_request)
```

- [ ] **Step 5: Run route tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
```

Expected: PASS.

### Task 4: Focused Regression And Staging

**Files:**
- All files changed in Tasks 1-3

- [ ] **Step 1: Run the focused retrieval and routing regression set**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_route_execution_strategies.py tests/test_route_search_orchestrator.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the broader retrieval smoke subset touched by this change**

Run:

```powershell
python -m pytest tests/test_hybrid_retrieval_executor.py tests/test_hybrid_retrieval_runtime.py tests/test_route_trace_recorder.py tests/test_query_tracer.py -q
```

Expected: PASS.

- [ ] **Step 3: Check git status without disturbing unrelated work**

Run:

```powershell
git -c safe.directory=E:/all-in-rag-intelligent-customer status --short
```

Expected: the plan file and retrieval/routing/test files are modified; pre-existing unrelated dependency/public-surface edits may still appear and must not be reverted.

- [ ] **Step 4: Stage only the files from this feature if committing is requested**

Run:

```powershell
git -c safe.directory=E:/all-in-rag-intelligent-customer add -- `
  docs/superpowers/plans/2026-06-17-retrieval-candidate-source-resilience.md `
  rag_modules/retrieval/candidate_generator.py `
  rag_modules/retrieval/candidate_sources.py `
  rag_modules/retrieval/hybrid_search_service.py `
  rag_modules/retrieval/hybrid_executor.py `
  rag_modules/retrieval/hybrid_facade.py `
  rag_modules/routing/execution_strategies.py `
  rag_modules/routing/search_orchestrator.py `
  tests/test_retrieval_candidate_generator.py `
  tests/test_hybrid_search_service.py `
  tests/test_route_execution_strategies.py `
  tests/test_route_search_orchestrator.py
```

Expected: only feature files are staged. Do not stage unrelated working-tree changes.
