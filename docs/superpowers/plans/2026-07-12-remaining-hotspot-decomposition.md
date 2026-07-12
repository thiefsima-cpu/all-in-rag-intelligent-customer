# Remaining Hotspot Decomposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce the five remaining named hotspots while preserving runtime behavior and hard-cutting the pressure tool over to responsibility-owned modules.

**Architecture:** Keep entity indexing, generation streaming, answer orchestration, and evidence extraction in their current owner modules and reduce them with private helpers. Replace the monolithic pressure script with an acyclic `scripts.pressure` package, a thin direct-script bootstrap, capability-owned tests, and structural ratchets.

**Tech Stack:** Python 3.11, dataclasses, generators, OpenAI-compatible client APIs, FastAPI service collaborators, pytest/unittest, Ruff, mypy, pre-commit, AST structural tests.

## Global Constraints

- Preserve all public production APIs, answer behavior, callback order, traces, telemetry, evidence ordering, pressure JSON schema, human output, and exit codes.
- Use Python `>=3.11,<3.12`; do not add dependencies or edit generated lock files.
- Keep the first four refactors local to their current owner modules. Do not add public types, protocols, factories, or forwarding modules for those extractions.
- Cut pressure imports over to canonical `scripts.pressure.*` modules. Do not re-export pressure data types or runner functions from `scripts.pressure_api_service.py` or `scripts.pressure.__init__`.
- Keep `python scripts/pressure_api_service.py --json` working as the documented direct script.
- Point the `graph-rag-pressure` console entry directly at `scripts.pressure.cli:main`.
- Keep the pressure tool local and deterministic. It must not contact real model providers, Neo4j, Milvus, or other external services.
- Add failing structural or import tests before production refactoring, then preserve the existing behavioral suites throughout the extraction.
- Do not repair or rewrite the existing entity-index Chinese string literals; preserve their UTF-8 text exactly.
- Do not edit historical plans or specs other than this plan's checkbox/status bookkeeping during execution.

---

## File Structure

**Existing production modules modified:**

- `rag_modules/graph_index/entity_index_builder.py`: thin entity-type orchestration plus private entity materializers.
- `rag_modules/generation/clients/adapter.py`: thin streaming retry loop plus private attempt state and stream helpers.
- `rag_modules/application/answering/answer_pipeline.py`: thin answer coordinator plus retrieval/generation span helpers.
- `rag_modules/evidence_processing/extraction.py`: explicit, graph, fallback, and deduplication stages.

**Pressure package created:**

- `scripts/pressure/__init__.py`: package docstring only.
- `scripts/pressure/scenario.py`: `PressureScenario`, canonical default, and scenario normalization.
- `scripts/pressure/metrics.py`: metric dataclasses and percentile calculation.
- `scripts/pressure/thresholds.py`: threshold/check dataclasses, defaults, and check evaluation.
- `scripts/pressure/reporter.py`: `PressureReport`, report construction, and rendering.
- `scripts/pressure/runner.py`: deterministic harnesses and scenario execution.
- `scripts/pressure/cli.py`: parser and process boundary.
- `scripts/pressure_api_service.py`: direct-script bootstrap only.

**Tests modified or created:**

- `tests/test_hotspot_function_ratchets.py`: one red/green line-count ratchet per named hotspot plus the thin-script ratchet.
- `tests/test_pressure_thresholds.py`: pressure contracts, checks, status, and serialization.
- `tests/test_pressure_runner.py`: scenario defaults and deterministic scenario execution.
- `tests/test_pressure_cli.py`: parser, rendering, exit status, direct script, and console ownership.
- Delete `tests/test_pressure_api_service.py` after every test method has moved exactly once.
- `tests/test_module_boundary_facades.py`: retain the direct-script import smoke and assert retired pressure ownership is absent.

---

### Task 1: Reduce Entity Index Materialization

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/graph_index/entity_index_builder.py`
- Test: `tests/test_graph_indexing_module.py`

**Interfaces:**

- Consumes: `GraphIndexStore.add_entity(entity_id, entity_kv, extra_keys=...)`, `EntityKeyValue`, and `dedupe_preserve_order`.
- Produces: unchanged `EntityIndexBuilder.build(*, recipes, ingredients, cooking_steps, store) -> Dict[str, EntityKeyValue]`; private `_add_recipe_entity`, `_add_ingredient_entity`, and `_add_cooking_step_entity` helpers.

- [ ] **Step 1: Add the failing entity hotspot ratchet**

Add this entry to `limits` in `HotspotFunctionRatchetsTests.test_named_hotspot_functions_stay_small_enough_to_review`:

```python
(
    "rag_modules/graph_index/entity_index_builder.py",
    "EntityIndexBuilder.build",
): 25,
```

- [ ] **Step 2: Run the ratchet and verify RED**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
```

Expected: FAIL containing `EntityIndexBuilder.build is 134 lines > 25`.

- [ ] **Step 3: Extract private entity materializers**

Keep `EntityIndexBuilder.build()` as the only class method and replace its body with this coordinator:

```python
logger.info("开始构建实体键值索引...")
for recipe in recipes:
    _add_recipe_entity(recipe, store)
for ingredient in ingredients:
    _add_ingredient_entity(ingredient, store)
for step in cooking_steps:
    _add_cooking_step_entity(step, store)
logger.info("实体键值索引构建完成，共 %s 个实体", len(store.entity_kv_store))
return store.entity_kv_store
```

Add these module-private interfaces above the class:

```python
def _recipe_content_parts(entity_name: str, props: Dict[str, Any]) -> List[str]:
    parts = [f"菜品名称: {entity_name}"]
    scalar_fields = (
        ("description", "描述"),
        ("category", "分类"),
        ("cuisineType", "菜系"),
        ("difficulty", "难度"),
        ("cookingTime", "烹饪时间"),
    )
    tag_fields = (
        ("health_tags", "健康标签"),
        ("cuisine_style_tags", "菜系风格标签"),
        ("ingredient_category_tags", "食材类别标签"),
        ("time_profile_tags", "时间轮廓标签"),
        ("difficulty_level_tags", "难度标签"),
    )
    for field, label in scalar_fields:
        if props.get(field):
            parts.append(f"{label}: {props[field]}")
    for field, label in tag_fields:
        if props.get(field):
            parts.append(f"{label}: {', '.join(props.get(field) or [])}")
    return parts


def _recipe_index_keys(entity_name: str, props: Dict[str, Any]) -> List[str]:
    return dedupe_preserve_order(
        [
            entity_name,
            props.get("category"),
            props.get("cuisineType"),
            *list(props.get("flavor_tags", []) or []),
            *list(props.get("technique_tags", []) or []),
            *list(props.get("diet_tags", []) or []),
            *list(props.get("health_tags", []) or []),
            *list(props.get("cuisine_style_tags", []) or []),
            *list(props.get("ingredient_category_tags", []) or []),
            *list(props.get("time_profile_tags", []) or []),
            *list(props.get("difficulty_level_tags", []) or []),
        ]
    )


def _add_recipe_entity(recipe: Any, store: GraphIndexStore) -> None:
    entity_id = str(recipe.node_id)
    entity_name = recipe.name or f"菜谱_{entity_id}"
    props = getattr(recipe, "properties", {}) or {}
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=_recipe_index_keys(entity_name, props),
            value_content="\n".join(_recipe_content_parts(entity_name, props)),
            entity_type="Recipe",
            metadata={"node_id": entity_id, "properties": props},
        ),
        extra_keys=[entity_name],
    )


def _add_ingredient_entity(ingredient: Any, store: GraphIndexStore) -> None:
    entity_id = str(ingredient.node_id)
    entity_name = ingredient.name or f"食材_{entity_id}"
    props = getattr(ingredient, "properties", {}) or {}
    content_parts = [f"食材名称: {entity_name}"]
    for field, label in (("category", "类别"), ("nutrition", "营养信息"), ("storage", "储存方式")):
        if props.get(field):
            content_parts.append(f"{label}: {props[field]}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order(
                [entity_name, props.get("category"), props.get("nutrition"), props.get("storage")]
            ),
            value_content="\n".join(content_parts),
            entity_type="Ingredient",
            metadata={"node_id": entity_id, "properties": props},
        ),
        extra_keys=[entity_name],
    )


def _add_cooking_step_entity(step: Any, store: GraphIndexStore) -> None:
    entity_id = str(step.node_id)
    entity_name = f"步骤_{entity_id}"
    props = getattr(step, "properties", {}) or {}
    content_parts = [f"烹饪步骤: {entity_name}"]
    for field, label in (("description", "步骤描述"), ("order", "步骤顺序"), ("technique", "技巧"), ("time", "时间")):
        if props.get(field):
            content_parts.append(f"{label}: {props[field]}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order(
                [entity_name, props.get("technique"), props.get("time")]
            ),
            value_content="\n".join(content_parts),
            entity_type="CookingStep",
            metadata={"node_id": entity_id, "properties": props},
        ),
        extra_keys=[entity_name],
    )
```

Run Ruff formatting after the edit; it may wrap the two long tuple/list lines without changing semantics.

- [ ] **Step 4: Verify entity GREEN**

Run:

```powershell
python -m pytest tests/test_graph_indexing_module.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/graph_index/entity_index_builder.py tests/test_hotspot_function_ratchets.py
```

Expected: both commands exit 0; graph entity content, keys, sparse fallbacks, snapshots, and the 25-line ratchet pass.

- [ ] **Step 5: Commit the entity extraction**

```powershell
git add rag_modules/graph_index/entity_index_builder.py tests/test_hotspot_function_ratchets.py
git commit -m "refactor: split entity index materialization"
```

---

### Task 2: Reduce Streaming Retry Orchestration

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/generation/clients/adapter.py`
- Test: `tests/test_generation_client.py`
- Test: `tests/test_generation_executor.py`

**Interfaces:**

- Consumes: `RequestControl`, `CircuitBreaker`, provider stream chunks, and `GenerationTokenUsageTracker`.
- Produces: unchanged `stream_prompt(...) -> Generator[str, None, None]`; private `_StreamingRequest` and `_StreamingAttemptState` dataclasses and private attempt helpers.

- [ ] **Step 1: Add the failing streaming hotspot ratchet**

Add this entry to the same `limits` mapping:

```python
(
    "rag_modules/generation/clients/adapter.py",
    "GenerationClientAdapter.stream_prompt",
): 35,
```

- [ ] **Step 2: Run the streaming ratchet and verify RED**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
```

Expected: FAIL containing `GenerationClientAdapter.stream_prompt is 99 lines > 35`.

- [ ] **Step 3: Add private stream request and attempt state**

Import `dataclass` and add these module-private types before `GenerationClientAdapter`:

```python
@dataclass(frozen=True)
class _StreamingRequest:
    temperature: float
    attempts: int
    deadline: float


@dataclass
class _StreamingAttemptState:
    circuit_started: bool = False
    emitted_content: bool = False
    reported_usage: bool = False
    emitted_chunks: list[str] = field(default_factory=list)
```

Update the import to `from dataclasses import dataclass, field`.

- [ ] **Step 4: Replace `stream_prompt` with the thin retry coordinator**

Use this exact coordinator and helpers inside `GenerationClientAdapter`:

```python
def stream_prompt(
    self,
    *,
    prompt: str,
    max_tokens: int,
    retries: int,
    temperature: float | None = None,
    timeout_seconds: float | None = None,
    control: RequestControl | None = None,
) -> Generator[str, None, None]:
    request = self._resolve_stream_request(
        retries=retries,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
        control=control,
    )
    last_exc: Exception | None = None
    for attempt in range(request.attempts):
        self._attempt_count.set(attempt + 1)
        state = _StreamingAttemptState()
        try:
            yield from self._stream_attempt(
                prompt=prompt,
                max_tokens=max_tokens,
                request=request,
                state=state,
                control=control,
            )
            return
        except (RequestCancelled, RequestBudgetExceeded):
            raise
        except Exception as exc:
            last_exc = exc
            if not self._prepare_stream_retry(exc, attempt, request, state):
                break
    if last_exc:
        raise last_exc

def _resolve_stream_request(
    self,
    *,
    retries: int,
    temperature: float | None,
    timeout_seconds: float | None,
    control: RequestControl | None,
) -> _StreamingRequest:
    resolved_timeout = (
        max(0.1, float(timeout_seconds))
        if timeout_seconds is not None
        else float(self.stream_timeout_seconds)
    )
    configured_deadline = time.perf_counter() + resolved_timeout
    return _StreamingRequest(
        temperature=self.default_temperature if temperature is None else temperature,
        attempts=max(1, int(retries or 1)),
        deadline=(
            min(configured_deadline, control.deadline)
            if control is not None
            else configured_deadline
        ),
    )

def _stream_attempt(
    self,
    *,
    prompt: str,
    max_tokens: int,
    request: _StreamingRequest,
    state: _StreamingAttemptState,
    control: RequestControl | None,
) -> Generator[str, None, None]:
    if control is not None:
        control.raise_if_cancelled()
    remaining = request.deadline - time.perf_counter()
    if remaining <= 0:
        raise GenerationLatencyBudgetExceeded(
            "Streaming generation deadline was exhausted."
        )
    self.circuit_breaker.before_call()
    state.circuit_started = True
    response = self.client.chat.completions.create(
        model=self.model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=request.temperature,
        max_tokens=max_tokens,
        stream=True,
        timeout=max(0.1, remaining),
        **self._provider_request_options(),
    )
    yield from self._stream_chunks(response=response, state=state, control=control)
    if not state.emitted_content:
        raise GenerationProviderResponseError(
            "Generation provider returned no stream content.",
            failure_code="generation_provider_empty_content",
        )
    if not state.reported_usage:
        self._record_estimated_usage(prompt=prompt, completion="".join(state.emitted_chunks))
    self.circuit_breaker.record_success()

def _stream_chunks(
    self,
    *,
    response: Any,
    state: _StreamingAttemptState,
    control: RequestControl | None,
) -> Generator[str, None, None]:
    for chunk in response:
        if control is not None:
            control.raise_if_cancelled()
        state.reported_usage = self._record_token_usage(chunk) or state.reported_usage
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        delta = getattr(choices[0], "delta", None)
        content = getattr(delta, "content", None)
        if content:
            state.emitted_content = True
            state.emitted_chunks.append(str(content))
            yield content

def _prepare_stream_retry(
    self,
    exc: Exception,
    attempt: int,
    request: _StreamingRequest,
    state: _StreamingAttemptState,
) -> bool:
    if state.circuit_started:
        self.circuit_breaker.record_failure()
    logger.warning("Streaming generation attempt failed: attempt=%s", attempt + 1)
    log_failure(
        logger,
        logging.WARNING,
        "generation_attempt_failed",
        code="GENERATION_FAILED",
        error=exc,
    )
    if state.emitted_content or attempt >= request.attempts - 1:
        return False
    if not is_retryable_generation_error(exc):
        return False
    remaining = request.deadline - time.perf_counter()
    if remaining <= 0:
        return False
    time.sleep(min(attempt + 1, 2, remaining))
    return True
```

- [ ] **Step 5: Verify streaming GREEN**

Run:

```powershell
python -m pytest tests/test_generation_client.py tests/test_generation_executor.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/generation/clients/adapter.py tests/test_hotspot_function_ratchets.py
```

Expected: all generation tests pass, including cancellation between chunks, empty streams, retry-before-content, partial-output failure, preflight failure, usage tracking, and deadline exhaustion; the ratchet passes.

- [ ] **Step 6: Commit the streaming extraction**

```powershell
git add rag_modules/generation/clients/adapter.py tests/test_hotspot_function_ratchets.py
git commit -m "refactor: split streaming retry orchestration"
```

---

### Task 3: Reduce Answer Pipeline Execution

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/application/answering/answer_pipeline.py`
- Test: `tests/test_answer_workflow.py`
- Test: `tests/test_application_use_cases.py`

**Interfaces:**

- Consumes: `AnswerPipelineState`, `RouteResolution`, `RouteSnapshot`, telemetry spans, router trace adapter, and generation trace adapter.
- Produces: unchanged `AnswerPipelineService.execute(state) -> AnswerPipelineState`; private prelude, retrieval, state-application, no-evidence, and generation helpers.

- [ ] **Step 1: Add the failing answer hotspot ratchet**

Add this entry:

```python
(
    "rag_modules/application/answering/answer_pipeline.py",
    "AnswerPipelineService.execute",
): 35,
```

- [ ] **Step 2: Run the answer ratchet and verify RED**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
```

Expected: FAIL containing `AnswerPipelineService.execute is 99 lines > 35`.

- [ ] **Step 3: Extract the pipeline stages**

Import `RouteResolution` and `RouteSnapshot` from `...contracts.runtime`. Replace `execute()` with:

```python
def execute(self, state: AnswerPipelineState) -> AnswerPipelineState:
    control = state.request_control
    if control is not None:
        control.raise_if_cancelled()
    self._emit_request_prelude(state)
    resolution, route_trace = self._retrieve(state)
    self._apply_route_resolution(state, resolution, route_trace)
    if not state.has_evidence:
        return self._complete_without_evidence(state)
    self._emit(
        state.message_callback,
        self._format_document_summary(state.evidence_documents),
    )
    self._emit(state.message_callback, self.answer_workflow_copy.answer_generation_started)
    self._generate_with_telemetry(state)
    return state
```

Add these private methods without changing `_generate_answer()`:

```python
def _emit_request_prelude(self, state: AnswerPipelineState) -> None:
    self._emit(
        state.message_callback,
        self.answer_workflow_copy.user_question_template.format(question=state.question),
    )
    if state.explain_routing and isinstance(
        self.query_router,
        ExplainableQueryRouterProtocol,
    ):
        self._emit(
            state.message_callback,
            self.query_router.explain_routing_decision(state.question),
        )
    self._emit(state.message_callback, self.answer_workflow_copy.query_routing_started)

def _retrieve(self, state: AnswerPipelineState) -> tuple[RouteResolution, RouteSnapshot]:
    retrieval_span = (
        self.telemetry.span("rag.retrieval", attributes={"rag.top_k": self.top_k})
        if self.telemetry is not None
        else nullcontext(None)
    )
    with retrieval_span as span:
        resolution, route_trace = self.router_traces.route_with_trace(
            state.question,
            self.top_k,
            control=state.request_control,
        )
        if span is not None:
            span.set_attribute(
                "rag.document.count",
                len(resolution.retrieval.evidence_documents),
            )
            if resolution.analysis is not None:
                span.set_attribute("rag.strategy", resolution.analysis.strategy_name)
    return resolution, route_trace

def _apply_route_resolution(
    self,
    state: AnswerPipelineState,
    resolution: RouteResolution,
    route_trace: RouteSnapshot,
) -> None:
    state.route_resolution = resolution
    state.retrieval_outcome = resolution.retrieval
    state.analysis = resolution.analysis
    state.answer_context = AnswerContext.from_route_resolution(resolution)
    state.route_trace = route_trace
    state.graph_trace = self.router_traces.graph_trace_for_question(
        state.route_trace,
        state.question,
    )
    if state.analysis:
        self._emit(state.message_callback, self._format_strategy_summary(state.analysis))

def _complete_without_evidence(self, state: AnswerPipelineState) -> AnswerPipelineState:
    state.generation_trace = GenerationSnapshot(
        status="failed",
        mode=GenerationMode.EMPTY,
        decision_reason="no_evidence",
        failure_code="no_evidence",
        total_evidence_items=0,
        selected_evidence_items=0,
    )
    state.answer = self.answer_workflow_copy.no_evidence_answer
    return state

def _generate_with_telemetry(self, state: AnswerPipelineState) -> None:
    generation_span = (
        self.telemetry.span(
            "rag.generation",
            attributes={"gen_ai.operation.name": "chat"},
        )
        if self.telemetry is not None
        else nullcontext(None)
    )
    with generation_span as span:
        state.answer, state.generation_trace = self._generate_answer(
            answer_context=state.answer_context,
            stream=state.stream,
            chunk_callback=state.chunk_callback,
            message_callback=state.message_callback,
            control=state.request_control,
        )
        if span is not None:
            span.set_attribute(
                "gen_ai.usage.input_tokens",
                state.generation_trace.prompt_tokens,
            )
            span.set_attribute(
                "gen_ai.usage.output_tokens",
                state.generation_trace.completion_tokens,
            )
            span.set_attribute(
                "rag.generation.mode",
                state.generation_trace.mode_value or "unknown",
            )
```

- [ ] **Step 4: Verify answer GREEN**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py tests/test_application_use_cases.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/application/answering/answer_pipeline.py tests/test_hotspot_function_ratchets.py
```

Expected: all tests pass; no-evidence, successful traces, request-scoped concurrency, streaming fallback, callback copy, and telemetry remain unchanged.

- [ ] **Step 5: Commit the answer extraction**

```powershell
git add rag_modules/application/answering/answer_pipeline.py tests/test_hotspot_function_ratchets.py
git commit -m "refactor: split answer pipeline execution stages"
```

---

### Task 4: Reduce Evidence Extraction Stages

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/evidence_processing/extraction.py`
- Test: `tests/test_evidence_extraction.py`

**Interfaces:**

- Consumes: `EvidenceUnit`, document helpers, graph evidence metadata, and stable hashes.
- Produces: unchanged `extract_evidence_units(doc, metadata=None) -> List[Dict[str, Any]]`; private explicit, graph, fallback, and deduplication helpers.

- [ ] **Step 1: Add the failing evidence hotspot ratchet**

Add these entries:

```python
(
    "rag_modules/evidence_processing/extraction.py",
    "extract_evidence_units",
): 35,
(
    "rag_modules/evidence_processing/extraction.py",
    "_graph_relationship_units",
): 45,
```

- [ ] **Step 2: Run the evidence ratchets and verify RED**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
```

Expected: FAIL for `extract_evidence_units` at 101 lines and `_graph_relationship_units` at 76 lines.

- [ ] **Step 3: Extract explicit, graph, relationship, fallback, and dedupe stages**

Implement these private interfaces and move the current field mapping into them unchanged:

```python
def _explicit_units(metadata: Dict[str, Any], source: str, score: float) -> List[EvidenceUnit]:
    units: List[EvidenceUnit] = []
    for item in metadata.get("evidence_units") or []:
        if isinstance(item, EvidenceUnit):
            units.append(item)
        elif isinstance(item, dict) and item.get("claim"):
            claim = str(item.get("claim") or "")
            units.append(
                EvidenceUnit(
                    unit_id=str(item.get("unit_id") or f"unit::{stable_hash(claim)}"),
                    evidence_type=str(item.get("evidence_type") or "text"),
                    claim=claim,
                    source=str(item.get("source") or source),
                    score=float(item.get("score") or score),
                    recipe_id=str(item.get("recipe_id") or metadata.get("recipe_id") or ""),
                    recipe_name=str(
                        item.get("recipe_name") or metadata.get("recipe_name") or ""
                    ),
                    relation_type=str(item.get("relation_type") or ""),
                    entities=[str(value) for value in item.get("entities") or [] if value],
                    is_graph_evidence=bool(item.get("is_graph_evidence")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
    return units

def _graph_payloads(graph_evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    if graph_evidence.get("primary") or graph_evidence.get("merged"):
        payloads = [graph_evidence.get("primary") or {}]
        payloads.extend(
            item for item in graph_evidence.get("merged") or [] if isinstance(item, dict)
        )
        return payloads
    return [graph_evidence]

def _relationship_claim(
    relationship: Any,
    labels_by_id: Dict[str, str],
) -> tuple[str, str, List[str]] | None:
    if isinstance(relationship, str):
        return relationship, "", []
    if not isinstance(relationship, dict):
        return None
    relation_type = str(
        relationship.get("type") or relationship.get("relation_type") or "RELATED"
    )
    start_id = str(relationship.get("startNodeId") or relationship.get("source_id") or "")
    end_id = str(relationship.get("endNodeId") or relationship.get("target_id") or "")
    start = str(
        relationship.get("source_name") or labels_by_id.get(start_id) or start_id or ""
    )
    end = str(relationship.get("target_name") or labels_by_id.get(end_id) or end_id or "")
    if start and end:
        return f"{start} -[{relation_type}]-> {end}", relation_type, [start, end]
    return relation_type, relation_type, [item for item in (start, end) if item]

def _fallback_unit(
    *,
    content: str,
    metadata: Dict[str, Any],
    source: str,
    score: float,
) -> EvidenceUnit | None:
    claim = content.strip()[:260]
    if not claim:
        return None
    recipe_name = str(metadata.get("recipe_name") or "")
    return EvidenceUnit(
        unit_id=f"unit::{stable_hash(claim)}",
        evidence_type=infer_evidence_type(metadata),
        claim=claim,
        source=source,
        score=score,
        recipe_id=str(metadata.get("recipe_id") or metadata.get("node_id") or ""),
        recipe_name=recipe_name,
        entities=[recipe_name] if recipe_name else [],
        is_graph_evidence=False,
        metadata={"search_type": metadata.get("search_type")},
    )

def _dedupe_units(units: List[EvidenceUnit]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for unit in units:
        key = unit.unit_id or unit.claim
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(unit.to_dict())
    return deduped[:30]
```

Rewrite `_graph_relationship_units()` to retain the existing graph-summary construction, then loop over `relationships[:20]`, call `_relationship_claim()`, skip falsey/`None` results, and construct the existing `graph_relation` `EvidenceUnit` from the returned claim, relation type, and stable-deduped entities.

Replace `extract_evidence_units()` with this coordinator:

```python
content = document_content(doc)
metadata = document_metadata(doc, metadata)
source = str(first_value(metadata, ["search_source", "search_method", "search_type"], "unknown"))
score = float(
    first_value(
        metadata,
        ["final_score", "relevance_score", "constraint_score", "score"],
        0.0,
    )
    or 0.0
)
units = _explicit_units(metadata, source, score)
graph_evidence = metadata.get("graph_evidence") or {}
if isinstance(graph_evidence, dict):
    for payload in _graph_payloads(graph_evidence):
        units.extend(
            _graph_relationship_units(
                metadata=metadata,
                graph_evidence=payload,
                source=source,
                score=score,
            )
        )
if not units:
    fallback = _fallback_unit(content=content, metadata=metadata, source=source, score=score)
    if fallback is not None:
        units.append(fallback)
return _dedupe_units(units)
```

- [ ] **Step 4: Verify evidence GREEN**

Run:

```powershell
python -m pytest tests/test_evidence_extraction.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/evidence_processing/extraction.py tests/test_hotspot_function_ratchets.py
```

Expected: direct, primary, merged, explicit, malformed, fallback, stable dedupe, 20-relationship, and 30-unit behavior pass with both ratchets.

- [ ] **Step 5: Commit the evidence extraction**

```powershell
git add rag_modules/evidence_processing/extraction.py tests/test_hotspot_function_ratchets.py
git commit -m "refactor: split evidence extraction stages"
```

---

### Task 5: Establish Canonical Pressure Contracts and Reporting

**Files:**

- Create: `scripts/pressure/__init__.py`
- Create: `scripts/pressure/scenario.py`
- Create: `scripts/pressure/metrics.py`
- Create: `scripts/pressure/thresholds.py`
- Create: `scripts/pressure/reporter.py`
- Modify: `scripts/pressure_api_service.py`
- Create: `tests/test_pressure_thresholds.py`
- Modify: `tests/test_pressure_api_service.py`

**Interfaces:**

- Produces: canonical `PressureScenario`, `DEFAULT_PRESSURE_SCENARIO`, `default_pressure_scenario`, metric dataclasses, `PressureStatus`, `PressureThresholds`, `PressureCheck`, `default_pressure_thresholds`, `PressureReport`, and `build_pressure_report`.
- Consumes: no earlier pressure package task; the old script temporarily imports canonical contracts while it still owns runners and CLI.

- [ ] **Step 1: Add failing canonical pressure imports**

Create `tests/test_pressure_thresholds.py` with this prelude, then move the listed existing
methods unchanged from `PressureApiServiceTests`:

```python
from __future__ import annotations

import unittest
```

```text
test_threshold_equality_passes_for_maximum_and_minimum_limits
test_threshold_failures_identify_the_failed_check_names
test_warning_thresholds_produce_warn_without_failures
test_report_status_prefers_fail_over_warn_over_pass
test_report_exit_code_is_nonzero_only_for_fail
test_report_json_contract_uses_structured_sections
```

Move `_metrics()` with them and use this canonical import block:

```python
from scripts.pressure.metrics import (
    ModelMetrics,
    PressureMetrics,
    RetrievalMetrics,
    SseMetrics,
    TraceMetrics,
)
from scripts.pressure.reporter import PressureReport, build_pressure_report
from scripts.pressure.scenario import PressureScenario, default_pressure_scenario
from scripts.pressure.thresholds import (
    PressureCheck,
    PressureThresholds,
    default_pressure_thresholds,
)
```

Remove those six methods and `_metrics()` from `tests/test_pressure_api_service.py`; keep its remaining imports and methods temporarily.
Replace that temporary file's pressure import block with:

```python
from scripts.pressure_api_service import (
    DEFAULT_PRESSURE_SCENARIO,
    _parse_args,
    default_pressure_scenario,
    main,
    run_pressure_test,
)
```

- [ ] **Step 2: Run canonical contract tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_thresholds.py -q
```

Expected: collection ERROR because `scripts.pressure` does not exist.

- [ ] **Step 3: Create the pressure contract modules by exact symbol ownership**

Create `scripts/pressure/__init__.py` with only:

```python
"""Deterministic local API pressure scenarios and reporting."""
```

Move definitions from the current `scripts/pressure_api_service.py` without changing fields,
defaults, rounding, messages, order, or serialization:

```text
scenario.py:
  PressureScenario
  DEFAULT_PRESSURE_SCENARIO
  default_pressure_scenario

metrics.py:
  TraceMetrics
  SseMetrics
  ModelMetrics
  RetrievalMetrics
  PressureMetrics
  _percentile

thresholds.py:
  PressureStatus
  PressureThresholds
  PressureCheck
  _max_check
  _min_check
  _warn_max_check
  _evaluate_pressure_checks
  default_pressure_thresholds

reporter.py:
  PressureReport
  build_pressure_report
  print_human_report
  print_json_report
```

Rename `_print_human_report(payload)` to `print_human_report(report)` and construct
`payload = report.to_dict()` as its first statement. Add:

```python
def print_json_report(report: PressureReport) -> None:
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
```

Use these dependency imports and no package-root imports:

```python
# thresholds.py
from .metrics import PressureMetrics
from .scenario import PressureScenario

# reporter.py
from .metrics import PressureMetrics
from .scenario import PressureScenario
from .thresholds import PressureCheck, PressureStatus, PressureThresholds, _evaluate_pressure_checks
```

In the temporary monolith, replace moved definitions with direct canonical imports so its runner
and CLI continue working during this task:

```python
from scripts.pressure.metrics import ModelMetrics, PressureMetrics, RetrievalMetrics, SseMetrics, TraceMetrics, _percentile
from scripts.pressure.reporter import PressureReport, build_pressure_report, print_human_report, print_json_report
from scripts.pressure.scenario import DEFAULT_PRESSURE_SCENARIO, PressureScenario, default_pressure_scenario
from scripts.pressure.thresholds import PressureCheck, PressureThresholds, default_pressure_thresholds
```

Remove now-unused `json`, `dataclass`, `field`, and `Literal` imports from the temporary monolith;
retain `argparse`, `Sequence`, threading, time, and runtime-service imports until Tasks 6 and 7
move their remaining owners.

Update the temporary monolith's final rendering branch so it calls the canonical reporter with
the report object:

```python
if args.json:
    print_json_report(report)
else:
    print_human_report(report)
return report.exit_code
```

- [ ] **Step 4: Verify canonical contracts GREEN**

Run:

```powershell
python -m pytest tests/test_pressure_thresholds.py tests/test_pressure_api_service.py -q
python -m ruff check scripts/pressure scripts/pressure_api_service.py tests/test_pressure_thresholds.py tests/test_pressure_api_service.py
```

Expected: both commands exit 0 and the report payload is byte-for-byte equivalent after JSON decoding.

- [ ] **Step 5: Commit pressure contracts and reporting**

```powershell
git add scripts/pressure scripts/pressure_api_service.py tests/test_pressure_thresholds.py tests/test_pressure_api_service.py
git commit -m "refactor: extract pressure contracts and reporting"
```

---

### Task 6: Extract the Deterministic Pressure Runner

**Files:**

- Create: `scripts/pressure/runner.py`
- Modify: `scripts/pressure_api_service.py`
- Create: `tests/test_pressure_runner.py`
- Modify: `tests/test_pressure_api_service.py`
- Modify: `tests/test_hotspot_function_ratchets.py`

**Interfaces:**

- Consumes: canonical scenario, metric, threshold, and reporter modules from Task 5.
- Produces: `scripts.pressure.runner.run_pressure_test(...) -> PressureReport`; private normal and SSE scenario runners whose orchestration functions are at most 45 lines.

- [ ] **Step 1: Add failing runner ownership and size tests**

Create `tests/test_pressure_runner.py` with this complete prelude and canonical imports:

```python
from __future__ import annotations

import unittest

from scripts.pressure.runner import run_pressure_test
from scripts.pressure.scenario import DEFAULT_PRESSURE_SCENARIO, default_pressure_scenario
```

Move these existing methods unchanged into `PressureRunnerTests`:

```text
test_saturation_run_reports_admission_rejections_and_balanced_accounting
test_default_run_returns_new_report_contract
test_default_scenario_has_one_cross_platform_baseline
test_default_run_is_a_healthy_repeatable_baseline
test_retrieval_degraded_budget_can_warn_without_live_dependencies
test_retrieval_degraded_budget_fails_when_single_source_limit_is_exceeded
test_model_call_budget_reports_synthetic_latency_tokens_and_cost
test_model_call_budget_fails_when_synthetic_budget_exceeds_fixed_thresholds
test_sse_runner_capacity_records_terminal_events_without_http
```

Remove those methods from `tests/test_pressure_api_service.py`. Add these ratchets:

```python
(
    "scripts/pressure/runner.py",
    "run_pressure_test",
): 45,
(
    "scripts/pressure/runner.py",
    "_run_answer_pressure_scenario",
): 45,
(
    "scripts/pressure/runner.py",
    "_run_sse_pressure_scenario",
): 45,
```

- [ ] **Step 2: Run runner tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_runner.py tests/test_hotspot_function_ratchets.py -q
```

Expected: collection ERROR because `scripts.pressure.runner` does not exist.

- [ ] **Step 3: Move harnesses and split mutable run state**

Move these exact existing symbols into `scripts/pressure/runner.py`:

```text
_SlowCaptureTraceSink
_diagnostics
_PressureTestSystem
_build_tracer
_retrieval_metrics_from_scenario
_model_metrics_from_scenario
_empty_pressure_metrics
```

Add private run-state dataclasses:

```python
@dataclass
class _AnswerRunState:
    scenario: PressureScenario
    next_request: int = 0
    completed_requests: int = 0
    rejected_requests: int = 0
    latencies: list[float] = field(default_factory=list)
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    counts_lock: threading.Lock = field(default_factory=threading.Lock)
    latencies_lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_request(self) -> int | None:
        with self.request_lock:
            if self.next_request >= self.scenario.requests:
                return None
            request_id = self.next_request
            self.next_request += 1
            return request_id


@dataclass
class _SseRunState:
    scenario: PressureScenario
    next_request: int = 0
    done_events: int = 0
    result_events: int = 0
    error_events: int = 0
    rate_limited_error_events: int = 0
    unfinished_streams: int = 0
    request_lock: threading.Lock = field(default_factory=threading.Lock)
    counts_lock: threading.Lock = field(default_factory=threading.Lock)

    def claim_request(self) -> int | None:
        with self.request_lock:
            if self.next_request >= self.scenario.requests:
                return None
            request_id = self.next_request
            self.next_request += 1
            return request_id
```

Split the existing two nested worker loops into `_run_answer_worker(service, state, worker_id)` and
`_run_sse_worker(service, state, worker_id)`. Preserve the exact question format, event counting,
`ApiBackpressureError` handling, and lock boundaries.

Use these public/private orchestration signatures:

```python
def run_pressure_test(
    *,
    scenario_name: str | None = None,
    requests: int | None = None,
    workers: int | None = None,
    answer_delay_ms: float | None = None,
    trace_delay_ms: float | None = None,
    trace_queue_size: int | None = None,
    max_concurrent_answers: int | None = None,
    answer_acquire_timeout_seconds: float | None = None,
    synthetic_model_latency_ms: float | None = None,
    synthetic_input_tokens_per_request: int | None = None,
    synthetic_output_tokens_per_request: int | None = None,
    input_cost_per_million_tokens: float | None = None,
    output_cost_per_million_tokens: float | None = None,
    retrieval_degraded_every: int | None = None,
    retrieval_degraded_source: str | None = None,
) -> PressureReport:
    scenario = default_pressure_scenario(
        scenario_name=scenario_name,
        requests=requests,
        workers=workers,
        answer_delay_ms=answer_delay_ms,
        trace_delay_ms=trace_delay_ms,
        trace_queue_size=trace_queue_size,
        max_concurrent_answers=max_concurrent_answers,
        answer_acquire_timeout_seconds=answer_acquire_timeout_seconds,
        synthetic_model_latency_ms=synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=input_cost_per_million_tokens,
        output_cost_per_million_tokens=output_cost_per_million_tokens,
        retrieval_degraded_every=retrieval_degraded_every,
        retrieval_degraded_source=retrieval_degraded_source,
    )
    if scenario.name == "sse_runner_capacity":
        return _run_sse_pressure_scenario(scenario)
    return _run_answer_pressure_scenario(scenario)
```

If Ruff formatting leaves `run_pressure_test` above 45 physical lines solely because of the
keyword list, introduce a private `_scenario_from_options(**kwargs) -> PressureScenario` wrapper
and keep the public signature unchanged. Do not raise the ratchet.

`_run_answer_pressure_scenario()` and `_run_sse_pressure_scenario()` each perform only setup,
thread launch via a shared `_run_threads(name, workers, target)`, shutdown, and report construction.
Move metrics construction to `_answer_metrics(...)` and `_sse_metrics(...)` so both orchestration
functions stay within 45 lines.

Replace the old runner definitions in `scripts/pressure_api_service.py` with:

```python
from scripts.pressure.runner import run_pressure_test
```

After removing the runner, reduce the temporary monolith's imports to `argparse`, `Sequence`, the
canonical `DEFAULT_PRESSURE_SCENARIO`, reporter functions, and `run_pressure_test`; remove all
threading, timing, dataclass, runtime-service, metrics, and threshold imports. Replace the
remaining temporary test module's pressure import block with:

```python
from scripts.pressure_api_service import DEFAULT_PRESSURE_SCENARIO, _parse_args, main
```

- [ ] **Step 4: Verify runner GREEN**

Run:

```powershell
python -m pytest tests/test_pressure_runner.py tests/test_pressure_thresholds.py tests/test_pressure_api_service.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check scripts/pressure scripts/pressure_api_service.py tests/test_pressure_runner.py tests/test_pressure_api_service.py tests/test_hotspot_function_ratchets.py
```

Expected: all deterministic scenarios and every runner ratchet pass; no live dependency is used.

- [ ] **Step 5: Commit the runner extraction**

```powershell
git add scripts/pressure/runner.py scripts/pressure_api_service.py tests/test_pressure_runner.py tests/test_pressure_api_service.py tests/test_hotspot_function_ratchets.py
git commit -m "refactor: extract deterministic pressure runner"
```

---

### Task 7: Hard-Cut Pressure CLI, Entrypoints, Tests, and Documentation

**Files:**

- Create: `scripts/pressure/cli.py`
- Replace: `scripts/pressure_api_service.py`
- Modify: `pyproject.toml`
- Create: `tests/test_pressure_cli.py`
- Delete: `tests/test_pressure_api_service.py`
- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `README.md`
- Modify: `docs/api_capacity_and_pressure_thresholds.md`

**Interfaces:**

- Consumes: `DEFAULT_PRESSURE_SCENARIO`, `run_pressure_test`, `print_human_report`, and `print_json_report`.
- Produces: `scripts.pressure.cli._parse_args(argv)`, `scripts.pressure.cli.main(argv) -> int`, thin direct script, and `graph-rag-pressure = "scripts.pressure.cli:main"`.

- [ ] **Step 1: Add failing CLI ownership and thin-entrypoint tests**

Create `tests/test_pressure_cli.py` with these imports:

```python
import importlib
import io
import json
import subprocess
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.pressure.cli import _parse_args, main
from scripts.pressure.scenario import DEFAULT_PRESSURE_SCENARIO
```

Move these existing methods unchanged into `PressureCliTests`:

```text
test_cli_parser_reads_defaults_from_canonical_scenario
test_main_returns_one_and_preserves_json_for_failed_report
test_main_returns_zero_after_human_pass_report
test_script_process_exits_one_and_emits_failed_json
```

Add these hard-cutover tests:

```python
def test_console_entrypoint_targets_canonical_cli(self) -> None:
    project_root = Path(__file__).resolve().parents[1]
    payload = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    self.assertEqual(
        payload["project"]["scripts"]["graph-rag-pressure"],
        "scripts.pressure.cli:main",
    )

def test_legacy_script_does_not_export_pressure_business_symbols(self) -> None:
    module = importlib.import_module("scripts.pressure_api_service")
    retired = {
        "PressureScenario",
        "PressureMetrics",
        "PressureThresholds",
        "PressureReport",
        "build_pressure_report",
        "default_pressure_scenario",
        "default_pressure_thresholds",
        "run_pressure_test",
    }
    self.assertEqual({name for name in retired if hasattr(module, name)}, set())

def test_pressure_package_root_has_no_aggregate_exports(self) -> None:
    module = importlib.import_module("scripts.pressure")
    self.assertEqual(getattr(module, "__all__", None), None)
    self.assertFalse(hasattr(module, "PressureScenario"))
```

Add a `_file_line_count()` helper to `tests/test_hotspot_function_ratchets.py` and this assertion:

```python
def test_pressure_script_stays_a_thin_direct_entrypoint(self) -> None:
    path = ROOT / "scripts/pressure_api_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 20)
    self.assertEqual(definitions, [])
```

- [ ] **Step 2: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_cli.py tests/test_hotspot_function_ratchets.py -q
```

Expected: collection ERROR for missing `scripts.pressure.cli`, or failures showing the old console target and legacy exports.

- [ ] **Step 3: Create the canonical CLI**

Move the existing parser arguments unchanged into `scripts/pressure/cli.py` and use this boundary:

```python
from __future__ import annotations

import argparse
from collections.abc import Sequence

from .reporter import print_human_report, print_json_report
from .runner import run_pressure_test
from .scenario import DEFAULT_PRESSURE_SCENARIO


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = DEFAULT_PRESSURE_SCENARIO
    parser = argparse.ArgumentParser(
        description=(
            "Local pressure test for GraphRAGServingApiService concurrency "
            "and trace backpressure."
        )
    )
    parser.add_argument("--requests", type=int, default=defaults.requests)
    parser.add_argument("--workers", type=int, default=defaults.workers)
    parser.add_argument("--answer-delay-ms", type=float, default=defaults.answer_delay_ms)
    parser.add_argument("--trace-delay-ms", type=float, default=defaults.trace_delay_ms)
    parser.add_argument("--trace-queue-size", type=int, default=defaults.trace_queue_size)
    parser.add_argument("--scenario-name", default=defaults.name)
    parser.add_argument(
        "--max-concurrent-answers",
        type=int,
        default=defaults.max_concurrent_answers,
    )
    parser.add_argument(
        "--answer-acquire-timeout-seconds",
        type=float,
        default=defaults.answer_acquire_timeout_seconds,
    )
    parser.add_argument(
        "--synthetic-model-latency-ms",
        type=float,
        default=defaults.synthetic_model_latency_ms,
    )
    parser.add_argument(
        "--synthetic-input-tokens-per-request",
        type=int,
        default=defaults.synthetic_input_tokens_per_request,
    )
    parser.add_argument(
        "--synthetic-output-tokens-per-request",
        type=int,
        default=defaults.synthetic_output_tokens_per_request,
    )
    parser.add_argument(
        "--input-cost-per-million-tokens",
        type=float,
        default=defaults.input_cost_per_million_tokens,
    )
    parser.add_argument(
        "--output-cost-per-million-tokens",
        type=float,
        default=defaults.output_cost_per_million_tokens,
    )
    parser.add_argument(
        "--retrieval-degraded-every",
        type=int,
        default=defaults.retrieval_degraded_every,
    )
    parser.add_argument(
        "--retrieval-degraded-source",
        default=defaults.retrieval_degraded_source,
    )
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_pressure_test(
        scenario_name=args.scenario_name,
        requests=args.requests,
        workers=args.workers,
        answer_delay_ms=args.answer_delay_ms,
        trace_delay_ms=args.trace_delay_ms,
        trace_queue_size=args.trace_queue_size,
        max_concurrent_answers=args.max_concurrent_answers,
        answer_acquire_timeout_seconds=args.answer_acquire_timeout_seconds,
        synthetic_model_latency_ms=args.synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=args.synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=args.synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=args.input_cost_per_million_tokens,
        output_cost_per_million_tokens=args.output_cost_per_million_tokens,
        retrieval_degraded_every=args.retrieval_degraded_every,
        retrieval_degraded_source=args.retrieval_degraded_source,
    )
    if args.json:
        print_json_report(report)
    else:
        print_human_report(report)
    return report.exit_code
```

- [ ] **Step 4: Replace the direct script and console target**

Replace `scripts/pressure_api_service.py` completely with:

```python
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.pressure.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

Change `pyproject.toml` to:

```toml
graph-rag-pressure = "scripts.pressure.cli:main"
```

Delete `tests/test_pressure_api_service.py`; at this point all 19 original test methods exist
exactly once across `test_pressure_thresholds.py`, `test_pressure_runner.py`, and
`test_pressure_cli.py`.

In `tests/test_module_boundary_facades.py`, keep the existing import smoke for
`scripts.pressure_api_service` and add the same retired-symbol set assertion used above so the
boundary suite independently enforces the hard cutover.

- [ ] **Step 5: Update current operator documentation**

Keep every command in `README.md` and `docs/api_capacity_and_pressure_thresholds.md` unchanged.
Add one sentence beside the pressure command in each current document:

```markdown
The direct script and `graph-rag-pressure` console command both delegate to the canonical
`scripts.pressure.cli` entrypoint; scenario, runner, metrics, thresholds, and reporting contracts
are owned by their matching `scripts.pressure` modules.
```

Do not edit historical files under `docs/superpowers/plans` or `docs/superpowers/specs`.

- [ ] **Step 6: Verify CLI hard cutover GREEN**

Run:

```powershell
python -m pytest tests/test_pressure_thresholds.py tests/test_pressure_runner.py tests/test_pressure_cli.py tests/test_hotspot_function_ratchets.py tests/test_module_boundary_facades.py tests/test_entrypoints.py -q
python -m ruff check scripts/pressure scripts/pressure_api_service.py tests/test_pressure_thresholds.py tests/test_pressure_runner.py tests/test_pressure_cli.py tests/test_hotspot_function_ratchets.py tests/test_module_boundary_facades.py
python scripts/pressure_api_service.py --json --requests 4 --workers 2 --answer-delay-ms 0 --trace-delay-ms 0
```

Expected: tests and Ruff exit 0; the direct script emits valid schema-version-1 JSON and exits 0.

- [ ] **Step 7: Commit the pressure hard cutover**

```powershell
git add -A -- pyproject.toml README.md docs/api_capacity_and_pressure_thresholds.md scripts/pressure scripts/pressure_api_service.py tests/test_pressure_api_service.py tests/test_pressure_thresholds.py tests/test_pressure_runner.py tests/test_pressure_cli.py tests/test_hotspot_function_ratchets.py tests/test_module_boundary_facades.py
git commit -m "refactor: split pressure tool by responsibility"
```

---

### Task 8: Repository-Wide Verification and Plan Closure

**Files:**

- Verify: all files changed by Tasks 1-7
- Modify only if a verification failure proves a scoped defect in those files.

**Interfaces:**

- Consumes: every behavior-preserving extraction and pressure hard cutover from Tasks 1-7.
- Produces: fresh focused, structural, full-suite, release-gate, and local-gate evidence.

- [ ] **Step 1: Run the combined focused suite**

Run:

```powershell
python -m pytest tests/test_graph_indexing_module.py tests/test_generation_client.py tests/test_generation_executor.py tests/test_answer_workflow.py tests/test_application_use_cases.py tests/test_evidence_extraction.py tests/test_pressure_thresholds.py tests/test_pressure_runner.py tests/test_pressure_cli.py tests/test_hotspot_function_ratchets.py tests/test_module_boundary_facades.py tests/test_entrypoints.py -q --basetemp=.pytest_hotspot_final
```

Expected: exit 0 with no failures or errors.

- [ ] **Step 2: Run formatting, lint, and whitespace checks**

Run:

```powershell
pre-commit run --all-files
git diff --check
```

Expected: all hooks and whitespace checks exit 0. Inspect `git status --short` because Ruff hooks may modify files; rerun the focused tests after any hook edit.

- [ ] **Step 3: Run complete pytest**

Run:

```powershell
python -m pytest -q --basetemp=.pytest_hotspot_full
```

Expected: the complete suite exits 0 with no failed tests.

- [ ] **Step 4: Run release-sensitive gates**

Run:

```powershell
python scripts/release_gate.py
python scripts/local_gate.py
```

Expected: both commands exit 0. Record the exact summaries and any environment-specific skips.

- [ ] **Step 5: Inspect final ownership and diff**

Run:

```powershell
git status --short --branch
git diff --stat HEAD~7..HEAD
python -c "import scripts.pressure_api_service as entry; assert not hasattr(entry, 'PressureScenario')"
python -c "from scripts.pressure.cli import main; from scripts.pressure.runner import run_pressure_test; assert callable(main) and callable(run_pressure_test)"
```

Expected: only the planned files changed across the implementation commits; canonical imports succeed and the old business symbol is absent.

- [ ] **Step 6: Close verification findings at their owning task**

If Steps 1-5 expose a defect, return to the task that owns the affected file, add or strengthen
its focused regression test, rerun that task's exact verification commands, and use that task's
explicit staging list. Commit the correction as
`fix: close hotspot decomposition verification gaps`. If no correction is needed, do not create
an empty verification commit.
