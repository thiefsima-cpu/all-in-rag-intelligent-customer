# Production Function Length Ratchet Implementation Plan

**Status:** completed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce every production function under `rag_modules/` to at most 80 physical lines and enforce the limit with a repository-wide AST ratchet.

**Architecture:** Keep every public function and owner module intact, extracting only private in-file helpers or small private dataclasses. Extend the existing hotspot test with a global scanner, an empty reviewed state-machine allow-list, and a temporary exact migration-debt map that is removed before delivery so every intermediate commit stays green.

**Tech Stack:** Python 3.11, standard-library `ast` and dataclasses, pytest/unittest, Ruff, mypy, pre-commit, repository release and local gates.

## Global Constraints

- Base branch is the latest `development`; implementation branch is `codex/performance-hotspot-ratchet`.
- Scan every `ast.FunctionDef` and `ast.AsyncFunctionDef` under `rag_modules/**/*.py`.
- Count physical lines with `(node.end_lineno or node.lineno) - node.lineno + 1`.
- Default maximum is exactly 80 lines; decorators are excluded by the AST line-number convention.
- Final `STATE_MACHINE_FUNCTION_ALLOWLIST` is empty and may never contain more than three explicit, justified entries.
- Preserve every stricter named limit already present in `tests/test_hotspot_function_ratchets.py`.
- Preserve public APIs, imports, types, ordering, retries, cancellation, fallbacks, logs, traces, telemetry, and configuration semantics.
- Do not add dependencies, edit generated lock files, touch `agent/`, or modify generated/local-state directories.
- Use behavior-preserving private extraction only; no forwarding modules, compatibility aliases, public helper types, or aggregate facades.
- Run each RED command before changing the production code named by that task.

---

## File Structure

**Documentation modified or created:**

- `docs/superpowers/specs/2026-07-13-production-function-length-ratchet-design.md`: approved design and ratchet contract.
- `docs/superpowers/plans/2026-07-13-production-function-length-ratchet.md`: executable TDD plan.

**Structural governance modified:**

- `tests/test_hotspot_function_ratchets.py`: global scanner, state-machine exception validation, temporary migration debt, and existing named limits.

**Production modules modified:**

- `rag_modules/query_policy/parsers/runtime_defaults.py`: compact typed semantic-default construction.
- `rag_modules/contracts/query_plan.py`: typed parsing helpers for `QueryPlan.from_dict`.
- `rag_modules/retrieval/hybrid_components.py`: split hybrid search-stack assembly.
- `rag_modules/query_understanding/graph_intent.py`: split entity, topic, and signal preparation.
- `rag_modules/query_understanding/planning/calibration.py`: split mutation phases.
- `rag_modules/query_understanding/planning/rule_based.py`: split source-entity resolution.
- `rag_modules/generation/execution/engine.py`: split attempt execution and fallback recording.
- `rag_modules/generation/execution/two_stage.py`: split primary attempt and direct fallback.
- `rag_modules/routing/strategies/graph.py`: split graph, fallback, and supplement stages.
- `rag_modules/infra/milvus/writer.py`: split entity materialization and batch insertion.
- `rag_modules/domain/shared/semantic_schema.py`: split contribution/effect extraction.

---

### Task 1: Add the Repository-Wide Function Scanner

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Test: `tests/test_hotspot_function_ratchets.py`

**Interfaces:**

- Consumes: repository root, Python AST `lineno`/`end_lineno`, existing `_qualified_name_parts`.
- Produces: `_FunctionSpan`, `_production_function_spans()`, `STATE_MACHINE_FUNCTION_ALLOWLIST`, and a global 80-line test.

- [ ] **Step 1: Write the global scanner without migration debt**

Add `from dataclasses import dataclass`, then add this complete scanner above the test class:

```python
MAX_PRODUCTION_FUNCTION_LINES = 80
MAX_STATE_MACHINE_EXCEPTIONS = 3
STATE_MACHINE_FUNCTION_ALLOWLIST: dict[tuple[str, str], str] = {}
_MIGRATION_FUNCTION_LENGTH_DEBT: dict[tuple[str, str], int] = {}


@dataclass(frozen=True)
class _FunctionSpan:
    path: str
    qualified_name: str
    line_count: int

    @property
    def key(self) -> tuple[str, str]:
        return self.path, self.qualified_name


def _production_function_spans() -> list[_FunctionSpan]:
    spans: list[_FunctionSpan] = []
    for path in sorted((ROOT / "rag_modules").rglob("*.py")):
        relative_path = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            spans.append(
                _FunctionSpan(
                    path=relative_path,
                    qualified_name=".".join(_qualified_name_parts(tree, node)),
                    line_count=(node.end_lineno or node.lineno) - node.lineno + 1,
                )
            )
    return spans
```

Add this test method without changing the named limits:

```python
def test_all_production_functions_respect_default_limit(self) -> None:
    spans = _production_function_spans()
    by_key = {span.key: span for span in spans}
    self.assertLessEqual(
        len(STATE_MACHINE_FUNCTION_ALLOWLIST),
        MAX_STATE_MACHINE_EXCEPTIONS,
    )

    exception_errors: list[str] = []
    for key, reason in STATE_MACHINE_FUNCTION_ALLOWLIST.items():
        span = by_key.get(key)
        if span is None:
            exception_errors.append(f"missing state-machine exception target: {key!r}")
        elif span.line_count <= MAX_PRODUCTION_FUNCTION_LINES:
            exception_errors.append(f"stale state-machine exception: {key!r}")
        if not reason.startswith("state machine:"):
            exception_errors.append(f"invalid state-machine reason: {key!r}")

    debt_errors: list[str] = []
    for key, baseline in _MIGRATION_FUNCTION_LENGTH_DEBT.items():
        span = by_key.get(key)
        if span is None:
            debt_errors.append(f"missing migration debt target: {key!r}")
        elif span.line_count <= MAX_PRODUCTION_FUNCTION_LINES:
            debt_errors.append(f"stale migration debt: {key!r}")
        elif span.line_count > baseline:
            debt_errors.append(
                f"migration debt grew: {key!r} is {span.line_count} lines > {baseline}"
            )

    oversize = [
        f"{span.path}:{span.qualified_name} is "
        f"{span.line_count} lines > {MAX_PRODUCTION_FUNCTION_LINES}"
        for span in spans
        if span.line_count > MAX_PRODUCTION_FUNCTION_LINES
        and span.key not in STATE_MACHINE_FUNCTION_ALLOWLIST
        and span.key not in _MIGRATION_FUNCTION_LENGTH_DEBT
    ]
    self.assertEqual(exception_errors + debt_errors + oversize, [])
```

- [ ] **Step 2: Run the scanner and verify the complete RED baseline**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py::HotspotFunctionRatchetsTests::test_all_production_functions_respect_default_limit -q
```

Expected: FAIL listing exactly the 11 functions and counts recorded in the approved design: `116`, `114`, `110`, `95`, `94`, `92`, `91`, `83`, `83`, `82`, and `81`.

- [ ] **Step 3: Add the temporary exact migration debt**

Replace the empty migration map with:

```python
_MIGRATION_FUNCTION_LENGTH_DEBT = {
    ("rag_modules/query_policy/parsers/runtime_defaults.py", "_parse_semantic_defaults"): 116,
    ("rag_modules/contracts/query_plan.py", "QueryPlan.from_dict"): 114,
    (
        "rag_modules/query_understanding/graph_intent.py",
        "infer_query_semantic_profile",
    ): 110,
    (
        "rag_modules/infra/milvus/writer.py",
        "_MilvusWriterOperations.build_vector_index",
    ): 95,
    (
        "rag_modules/query_understanding/planning/calibration.py",
        "QueryPlanCalibrator.calibrate",
    ): 94,
    (
        "rag_modules/generation/execution/engine.py",
        "GenerationExecutionEngine.generate_with_trace",
    ): 92,
    (
        "rag_modules/routing/strategies/graph.py",
        "GraphRouteStrategy.execute",
    ): 91,
    (
        "rag_modules/query_understanding/planning/rule_based.py",
        "RuleBasedPlanner.plan",
    ): 83,
    (
        "rag_modules/domain/shared/semantic_schema.py",
        "infer_recipe_semantics",
    ): 83,
    (
        "rag_modules/generation/execution/two_stage.py",
        "TwoStageCompletionRunner.run",
    ): 82,
    (
        "rag_modules/retrieval/hybrid_components.py",
        "DefaultHybridRetrievalComponentFactory.build",
    ): 81,
}
```

This map is only an intermediate-commit device. It ratchets every current violation against its exact baseline and is deleted in Task 6.

- [ ] **Step 4: Run the structural suite and verify GREEN**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
python -m ruff check tests/test_hotspot_function_ratchets.py
```

Expected: both commands exit 0; the named strict limits still run unchanged.

- [ ] **Step 5: Commit the scanner scaffold**

```powershell
git add tests/test_hotspot_function_ratchets.py
git commit -m "test: add production function length ratchet"
```

---

### Task 2: Reduce Declarative Construction Hotspots

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/query_policy/parsers/runtime_defaults.py`
- Modify: `rag_modules/contracts/query_plan.py`
- Modify: `rag_modules/retrieval/hybrid_components.py`
- Test: `tests/test_query_policy.py`
- Test: `tests/test_query_semantics.py`
- Test: `tests/test_retrieval_service_factories.py`

**Interfaces:**

- Consumes: existing semantic field readers, `QuerySemanticProfile`, `QueryConstraints`, and typed hybrid collaborators.
- Produces: unchanged `RuntimeDefaultsPolicy`, `QueryPlan.from_dict(query, data, semantic_settings=..., schema_relation_types=...)`, and `HybridRetrievalComponents` public contracts.

- [ ] **Step 1: Remove the three targets from migration debt**

Delete only these entries from `_MIGRATION_FUNCTION_LENGTH_DEBT`:

```python
("rag_modules/query_policy/parsers/runtime_defaults.py", "_parse_semantic_defaults")
("rag_modules/contracts/query_plan.py", "QueryPlan.from_dict")
(
    "rag_modules/retrieval/hybrid_components.py",
    "DefaultHybridRetrievalComponentFactory.build",
)
```

- [ ] **Step 2: Run the ratchet and verify RED for exactly three targets**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py::HotspotFunctionRatchetsTests::test_all_production_functions_respect_default_limit -q
```

Expected: FAIL only for `_parse_semantic_defaults`, `QueryPlan.from_dict`, and `DefaultHybridRetrievalComponentFactory.build`.

- [ ] **Step 3: Compact semantic-default construction with bound typed readers**

Add `from functools import partial` and bind the current readers inside `_parse_semantic_defaults`:

```python
semantics = _section(payload, root, "semantics")
read_float = partial(_semantic_float, semantics)
read_int = partial(_semantic_int, semantics)
```

Use `read_float("field_name")` for every current float field and `read_int("field_name")` for every current integer field in the existing `QuerySemanticRuntimeDefaultsPolicy` constructor. Keep the constructor's current field order and values. The complete field classification is:

```python
float_fields = (
    "relation_intensity_reference_ratio",
    "complexity_relation_hit_weight",
    "complexity_constraint_hit_weight",
    "complexity_structural_hit_weight",
    "complexity_length_weight",
    "reasoning_complexity_threshold",
    "reasoning_relationship_threshold",
    "high_relationship_routing_threshold",
    "relation_hit_intensity_boost_base",
    "relation_hit_intensity_boost_step",
    "relation_hit_complexity_boost_base",
    "relation_hit_complexity_boost_step",
    "multi_hop_hint_relationship_threshold",
    "combined_strategy_relationship_threshold",
    "combined_strategy_complexity_threshold",
    "source_entity_seed_relationship_threshold",
    "source_entity_backfill_relationship_threshold",
    "rule_fallback_confidence",
    "path_finding_high_intensity_threshold",
    "subgraph_high_intensity_threshold",
    "default_high_intensity_threshold",
    "adaptive_multi_hop_subgraph_threshold",
    "adaptive_subgraph_multi_hop_threshold",
    "adaptive_entity_relation_multi_hop_threshold",
)
int_fields = (
    "complexity_length_norm_chars",
    "source_entity_limit",
    "entity_keyword_limit",
    "semantic_profile_entity_keyword_limit",
    "topic_keyword_limit",
    "semantic_profile_topic_keyword_start",
    "semantic_profile_topic_keyword_limit",
    "target_entity_limit",
    "multi_hop_hint_entity_count",
    "entity_relation_max_depth",
    "path_finding_max_depth",
    "path_finding_high_intensity_max_depth",
    "subgraph_max_depth",
    "subgraph_high_intensity_max_depth",
    "clustering_max_depth",
    "default_max_depth",
    "default_high_intensity_max_depth",
    "entity_relation_max_nodes",
    "path_finding_max_nodes",
    "subgraph_max_nodes",
    "clustering_max_nodes",
    "default_max_nodes",
    "graph_query_max_depth_cap",
    "graph_query_fallback_name_chars",
    "adaptive_subgraph_max_depth",
    "adaptive_subgraph_max_nodes",
    "adaptive_multi_hop_max_depth",
    "adaptive_multi_hop_max_nodes",
    "adaptive_entity_relation_max_depth",
    "adaptive_entity_relation_max_nodes",
)
```

Do not introduce these tuples in production; they document the exact reader selection for the direct constructor.

- [ ] **Step 4: Extract typed `QueryPlan.from_dict` parsing helpers**

Add these module-private helpers above `QueryPlan`:

```python
def _resolve_semantic_profile(data: Dict[str, Any]) -> QuerySemanticProfile:
    profile = data.get("semantic_profile")
    if isinstance(profile, QuerySemanticProfile):
        return profile
    return QuerySemanticProfile.from_dict(profile)


def _resolve_plan_strategy(
    data: Dict[str, Any],
    constraints: QueryConstraints,
    validation_errors: List[str],
) -> SearchStrategy:
    raw_strategy = str(data.get("strategy") or SearchStrategy.HYBRID_TRADITIONAL.value)
    try:
        return SearchStrategy(raw_strategy)
    except ValueError:
        validation_errors.append(f"invalid_strategy:{raw_strategy}")
        if constraints.has_constraints() or constraints.needs_recipe_recommendation:
            return SearchStrategy.COMBINED
        return SearchStrategy.HYBRID_TRADITIONAL


def _resolve_plan_graph_query_type(
    data: Dict[str, Any],
    profile: QuerySemanticProfile,
    validation_errors: List[str],
) -> GraphQueryType:
    raw_type = str(
        data.get("graph_query_type")
        or profile.query_type_value
        or GraphQueryType.SUBGRAPH.value
    )
    try:
        return GraphQueryType(raw_type)
    except ValueError:
        validation_errors.append(f"invalid_graph_query_type:{raw_type}")
        return graph_query_type_or_default(profile.query_type, GraphQueryType.SUBGRAPH)


def _profile_values(data: Dict[str, Any], key: str, fallback: Iterable[str]) -> List[str]:
    return as_list(data.get(key)) or list(fallback)
```

Rewrite `from_dict` as a coordinator that calls the three helpers, computes complexity/intensity/reasoning and recommendation exactly as today, filters relation types against `allowed_relation_types`, and constructs the `QueryPlan` instance with the current field order. Do not change validation error order or constraint mutation.

- [ ] **Step 5: Extract the hybrid search-stack assembly**

Add this private method to `DefaultHybridRetrievalComponentFactory`:

```python
def _build_search_stack(
    self,
    *,
    config: GraphRAGConfig,
    retrieval_profile: RetrievalRuntimeProfile,
    runtime: HybridRetrievalRuntime,
    fusion_ranker: FusionRanker,
    keyword_extractor: QueryKeywordExtractor,
    cache_store: RetrievalCacheStore,
    bm25_retriever: BM25Retriever,
) -> tuple[ConstraintRetriever, HybridSearchService, HybridRetrievalExecutor]:
    constraint_retriever = ConstraintRetriever(runtime.get_recipe_matcher)
    search_service = HybridSearchService(
        config=config,
        retrieval_profile=retrieval_profile,
        runtime=runtime,
        fusion_ranker=fusion_ranker,
        constraint_retriever=constraint_retriever,
        candidate_source_factory=DefaultHybridCandidateSourceFactory(),
    )
    executor = HybridRetrievalExecutor(
        runtime=runtime,
        search_service=search_service,
        keyword_extractor=keyword_extractor,
        cache_store=cache_store,
        bm25_tokenizer=tokenize_chinese,
    )
    return constraint_retriever, search_service, executor
```

Replace the corresponding inline block in `build()` with one call. Keep runtime and final component construction unchanged.

- [ ] **Step 6: Run focused behavior, structural, and Ruff checks**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py tests/test_retrieval_service_factories.py tests/test_hybrid_retrieval_runtime.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/query_policy/parsers/runtime_defaults.py rag_modules/contracts/query_plan.py rag_modules/retrieval/hybrid_components.py tests/test_hotspot_function_ratchets.py
```

Expected: all tests pass; the three functions are at most 80 lines; all remaining migration debt entries are still valid.

- [ ] **Step 7: Commit declarative construction reductions**

```powershell
git add tests/test_hotspot_function_ratchets.py rag_modules/query_policy/parsers/runtime_defaults.py rag_modules/contracts/query_plan.py rag_modules/retrieval/hybrid_components.py
git commit -m "refactor: reduce declarative construction hotspots"
```

---

### Task 3: Reduce Query-Understanding Hotspots

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/query_understanding/graph_intent.py`
- Modify: `rag_modules/query_understanding/planning/calibration.py`
- Modify: `rag_modules/query_understanding/planning/rule_based.py`
- Test: `tests/test_query_semantics.py`
- Test: `tests/test_query_calibration_branches.py`

**Interfaces:**

- Consumes: `QueryUnderstandingRegistry`, `QuerySemanticProfile`, `QueryConstraints`, marker and scoring helpers.
- Produces: unchanged semantic profiles, calibrated mutable plans, and rule-based plans.

- [ ] **Step 1: Remove the three query-understanding entries from migration debt**

Delete the entries for `infer_query_semantic_profile`, `QueryPlanCalibrator.calibrate`, and `RuleBasedPlanner.plan`.

- [ ] **Step 2: Run the ratchet and verify RED for exactly three targets**

Run the global ratchet test from Task 2.

Expected: FAIL only for the three removed query-understanding targets.

- [ ] **Step 3: Split semantic profile preparation**

Add private helpers with these exact responsibilities and signatures:

```python
def _profile_entities(
    normalized: str,
    query_type: str,
    *,
    settings: QuerySemanticRuntimeSettings,
    registry: QueryUnderstandingRegistry,
) -> tuple[List[str], List[str], List[str]]:
    phrase_candidates = fallback_entity_phrases(normalized, registry=registry)
    keyword_candidates = extract_entity_candidates(normalized, registry=registry)
    candidates = dedupe_preserve_order([*phrase_candidates, *keyword_candidates])
    source_entities, target_entities = split_graph_entities(
        normalized,
        query_type,
        candidates,
        settings=settings,
        registry=registry,
    )
    keyword_seed = dedupe_preserve_order(
        [*source_entities, *target_entities, *candidates]
    )
    entity_keywords = normalize_graph_sources(
        keyword_seed[: settings.semantic_profile_entity_keyword_limit],
        registry=registry,
    )
    return source_entities, target_entities, entity_keywords


def _profile_topics(
    normalized: str,
    *,
    entity_keywords: Sequence[str],
    source_entities: Sequence[str],
    target_entities: Sequence[str],
    settings: QuerySemanticRuntimeSettings,
    registry: QueryUnderstandingRegistry,
) -> List[str]:
    topic_pool = [
        token
        for token in extract_query_tokens(normalized, registry=registry)
        if token not in entity_keywords
        and token not in source_entities
        and token not in target_entities
        and token not in registry.query_stopwords
        and token not in registry.graph_generic_terms
        and token not in registry.relation_markers
        and token not in registry.structural_reasoning_markers
    ]
    start = settings.semantic_profile_topic_keyword_start
    limit = settings.semantic_profile_topic_keyword_limit
    return dedupe_preserve_order(topic_pool[start : start + limit] or topic_pool[:limit])
```

Keep constraint, marker-hit, and score construction in `infer_query_semantic_profile`; with entity/topic preparation extracted, it becomes shorter than 80 lines without changing output ordering.

- [ ] **Step 4: Split calibration mutation phases**

Add these complete private methods to `QueryPlanCalibrator`:

```python
def _apply_profile(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
    plan.semantic_profile = profile
    plan.complexity = max(plan.complexity, profile.complexity)
    plan.relationship_intensity = max(
        plan.relationship_intensity,
        profile.relationship_intensity,
    )
    plan.reasoning_required = bool(
        plan.reasoning_required
        or profile.reasoning_required
        or plan.complexity >= self.settings.reasoning_complexity_threshold
        or plan.relationship_intensity >= self.settings.reasoning_relationship_threshold
    )
    plan.constraints.needs_recipe_recommendation = bool(
        plan.constraints.needs_recipe_recommendation
        or profile.needs_recipe_recommendation
    )


def _calibrate_strategy(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
    resolved = self.resolve_strategy(
        current_strategy=plan.strategy,
        profile=profile,
        constraints=plan.constraints,
        complexity=plan.complexity,
        relationship_intensity=plan.relationship_intensity,
    )
    current = _strategy_value(plan.strategy)
    if resolved == current:
        return
    label = self.policy.validation_labels["strategy"]
    plan.validation_errors.append(f"{label}:{current}->{resolved}")
    plan.strategy = SearchStrategy(resolved)


def _calibrate_graph_query_type(
    self, plan: QueryPlan, profile: QuerySemanticProfile
) -> None:
    resolved = self.resolve_graph_query_type(plan.graph_query_type, profile)
    if resolved == plan.graph_query_type:
        return
    label = self.policy.validation_labels["graph_query_type"]
    plan.validation_errors.append(
        f"{label}:{plan.graph_query_type_value}->{resolved.value}"
    )
    plan.graph_query_type = resolved


def _fill_missing_terms(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
    for relation_type in profile.relation_types:
        if relation_type not in plan.relation_types:
            plan.relation_types.append(relation_type)
    if not plan.entity_keywords:
        plan.entity_keywords = list(
            profile.entity_keywords[: self.settings.entity_keyword_limit]
        )
    if not plan.topic_keywords:
        plan.topic_keywords = list(
            profile.topic_keywords[: self.settings.topic_keyword_limit]
        )
    if not plan.target_entities:
        plan.target_entities = list(
            profile.target_entities[: self.settings.target_entity_limit]
        )


def _fill_graph_sources(self, plan: QueryPlan, profile: QuerySemanticProfile) -> None:
    if _strategy_value(plan.strategy) not in {
        SearchStrategy.GRAPH_RAG.value,
        SearchStrategy.COMBINED.value,
    } or plan.source_entities:
        return
    query = plan.query or ""
    fallback_candidates = (
        profile.source_entities
        or fallback_entity_phrases(query)
        or profile.entity_keywords
        or fallback_keywords(query)
    )
    plan.source_entities = normalize_graph_sources(
        fallback_candidates[: self.settings.source_entity_limit]
    )
    if plan.source_entities:
        plan.validation_errors.append(
            self.policy.validation_labels["source_entities"]
        )


def _clamp_max_depth(self, plan: QueryPlan) -> None:
    inferred = plan.max_depth or infer_graph_max_depth(
        plan.graph_query_type_value,
        plan.relationship_intensity,
        settings=self.settings,
        policy_bundle=self.policy_bundle,
    )
    plan.max_depth = max(
        1,
        min(int(inferred), self.settings.graph_query_max_depth_cap),
    )
```

`calibrate()` resolves the semantic profile, then calls these methods in the listed order. The strategy and graph-query-type helpers append the current validation strings before mutation; `_fill_graph_sources` preserves fallback candidate order.

- [ ] **Step 5: Extract rule-based source entity resolution**

Add this method to `RuleBasedPlanner`:

```python
def _resolve_source_entities(
    self,
    *,
    query: str,
    profile: QuerySemanticProfile,
    strategy: str,
    relationship_intensity: float,
) -> list[str]:
    source_candidates = (
        profile.source_entities
        if relationship_intensity >= self.settings.source_entity_seed_relationship_threshold
        else []
    )
    if not source_candidates and (
        strategy != SearchStrategy.HYBRID_TRADITIONAL.value
        or relationship_intensity
        >= self.settings.source_entity_backfill_relationship_threshold
    ):
        source_candidates = (
            profile.source_entities or profile.entity_keywords or fallback_keywords(query)
        )
    source_entities = normalize_graph_sources(
        source_candidates[: self.settings.source_entity_limit]
    )
    if (
        strategy == SearchStrategy.HYBRID_TRADITIONAL.value
        and relationship_intensity
        < self.settings.source_entity_seed_relationship_threshold
    ):
        return []
    return source_entities
```

Add `QuerySemanticProfile` to the existing relative contracts import, call this method after resolving strategy, and keep the existing `QueryPlan` construction unchanged.

- [ ] **Step 6: Run focused behavior, structural, and Ruff checks**

Run:

```powershell
python -m pytest tests/test_query_semantics.py tests/test_query_calibration_branches.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/query_understanding/graph_intent.py rag_modules/query_understanding/planning/calibration.py rag_modules/query_understanding/planning/rule_based.py tests/test_hotspot_function_ratchets.py
```

Expected: all tests pass; profile fields, hit ordering, validation ordering, and rule fallbacks remain unchanged.

- [ ] **Step 7: Commit query-understanding reductions**

```powershell
git add tests/test_hotspot_function_ratchets.py rag_modules/query_understanding/graph_intent.py rag_modules/query_understanding/planning/calibration.py rag_modules/query_understanding/planning/rule_based.py
git commit -m "refactor: reduce query understanding hotspots"
```

---

### Task 4: Reduce Online Execution Hotspots

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/generation/execution/engine.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Modify: `rag_modules/routing/strategies/graph.py`
- Test: `tests/test_generation_executor.py`
- Test: `tests/test_route_execution_strategies.py`

**Interfaces:**

- Consumes: `GenerationDecision`, `GenerationAttemptResult`, generation trace recorder, and route stage/result contracts.
- Produces: unchanged synchronous generation result/trace, two-stage fallback behavior, and graph route outcome.

- [ ] **Step 1: Remove the three execution entries from migration debt**

Delete the entries for `GenerationExecutionEngine.generate_with_trace`, `TwoStageCompletionRunner.run`, and `GraphRouteStrategy.execute`.

- [ ] **Step 2: Run the ratchet and verify RED for exactly three targets**

Run the global ratchet test.

Expected: FAIL only for the three removed online execution targets.

- [ ] **Step 3: Extract selected generation attempt and evidence fallback**

Import `GenerationDecision`, `GenerationAttemptResult`, and `GenerationExecutionDeadline`, then add:

```python
def _run_selected_attempt(
    self,
    *,
    decision: GenerationDecision,
    answer_context: AnswerContext,
    deadline: GenerationExecutionDeadline,
    control: RequestControl | None,
) -> GenerationAttemptResult:
    if decision.mode is GenerationMode.TWO_STAGE:
        return self._two_stage_runner.run(
            answer_context,
            deadline=deadline,
            control=control,
        )
    return self._direct_runner.run(
        answer_context,
        deadline=deadline,
        control=control,
    )


def _record_generation_fallback(
    self,
    *,
    trace: GenerationSnapshot,
    package: AnswerEvidencePackage,
    error: Exception,
    deadline: GenerationExecutionDeadline,
) -> tuple[str, GenerationSnapshot]:
    answer = self._fallback_handler.build_evidence_only_answer(package=package, error=error)
    self._trace_recorder.record_evidence_fallback(
        trace,
        error=error,
        total_latency_ms=deadline.total_elapsed_ms(),
    )
    return answer, self._trace_recorder.finalize_trace(trace)
```

`GenerationTraceRecorder.new_trace` returns `GenerationSnapshot`, so the trace annotation above is the concrete owner type. In `generate_with_trace`, call `_run_selected_attempt`, retain the separate `GenerationAttemptFailed` retry addition, retain cancellation propagation, and keep unexpected-error logging plus retry draining before `_record_generation_fallback`.

- [ ] **Step 4: Extract two-stage primary and fallback paths**

Add `from dataclasses import dataclass` and:

```python
@dataclass
class _TwoStageAttemptState:
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    request_retries: int = 0
```

Add these complete methods:

```python
def _run_primary_attempt(
    self,
    state: _TwoStageAttemptState,
    answer_context: AnswerContext,
    *,
    deadline: GenerationExecutionDeadline,
    control: RequestControl | None,
) -> GenerationAttemptResult:
    plan, state.plan_latency_ms, plan_retries = self.run_plan_stage(
        answer_context,
        deadline=deadline,
        control=control,
    )
    state.request_retries += plan_retries
    compose_start = time.perf_counter()
    answer = self._composer.compose_from_context(
        answer_context,
        plan,
        timeout_seconds=deadline.remaining_timeout(self._settings.timeout_seconds),
        control=control,
    )
    if control is not None:
        control.raise_if_cancelled()
    state.compose_latency_ms = deadline.elapsed_ms_since(compose_start)
    state.request_retries += self._usage_collector.drain_retry_count()
    return GenerationAttemptResult(
        answer=answer,
        plan_latency_ms=state.plan_latency_ms,
        compose_latency_ms=state.compose_latency_ms,
        request_retries=state.request_retries,
    )


def _run_direct_fallback(
    self,
    state: _TwoStageAttemptState,
    answer_context: AnswerContext,
    failure: Exception,
    *,
    deadline: GenerationExecutionDeadline,
    control: RequestControl | None,
) -> GenerationAttemptResult:
    try:
        direct = self._direct_runner.run(
            answer_context,
            deadline=deadline,
            control=control,
        )
        return GenerationAttemptResult(
            answer=direct.answer,
            plan_latency_ms=state.plan_latency_ms,
            compose_latency_ms=state.compose_latency_ms,
            direct_latency_ms=direct.direct_latency_ms,
            request_retries=state.request_retries + direct.request_retries,
            status="degraded",
            fallback_used=True,
            fallback_reason="two_stage_to_direct_model",
            failure=failure,
        )
    except (RequestCancelled, RequestBudgetExceeded):
        raise
    except Exception as fallback_exc:
        log_failure(
            logger,
            logging.WARNING,
            "generation_fallback_failed",
            code="GENERATION_FAILED",
            error=fallback_exc,
        )
        state.request_retries += self._usage_collector.drain_retry_count()
        raise GenerationAttemptFailed(
            fallback_exc,
            request_retries=state.request_retries,
        ) from fallback_exc
```

`run()` creates `_TwoStageAttemptState`, calls `_run_primary_attempt`, preserves cancellation and budget propagation, logs the primary failure, drains retry count, calls `_run_direct_fallback` only when `should_attempt_model_fallback` is true, and otherwise raises `GenerationAttemptFailed` from the primary exception.

- [ ] **Step 5: Extract graph route stages**

Import `EvidenceDocument` and `RetrievalRequest` from `...contracts`, then add these complete private methods:

```python
def _run_graph_stage(
    self,
    request: RouteExecutionRequestPort,
    services: RouteRetrievalServices,
    stages: List[RouteExecutionStageResult],
) -> tuple[RetrievalRequest, List[EvidenceDocument]]:
    graph_start = time.perf_counter()
    graph_request = request.retrieval_request.copy_with(
        top_k=request.top_k,
        candidate_k=request.top_k,
        strategy=SearchStrategy.GRAPH_RAG.value,
    )
    if graph_request.control is not None:
        graph_request.control.raise_if_cancelled()
    graph_documents, graph_trace = (
        services.graph_rag_retrieval.graph_rag_evidence_search_with_trace(graph_request)
    )
    stages.append(
        RouteExecutionStageResult(
            name="graph_rag",
            documents=list(graph_documents),
            latency_ms=_elapsed_ms(graph_start),
            extra=graph_trace,
        )
    )
    documents = services.traditional_retrieval.enrich_to_parent_evidence_documents(
        graph_request,
        graph_documents,
        top_n=request.top_k,
    )
    return graph_request, list(documents)

def _hybrid_fallback(
    self,
    request: RouteExecutionRequestPort,
    services: RouteRetrievalServices,
    stages: List[RouteExecutionStageResult],
) -> RouteExecutionOutcome:
    fallback_start = time.perf_counter()
    outcome = services.traditional_retrieval.hybrid_evidence_search(
        request.retrieval_request
    )
    documents = list(outcome.documents)
    stages.append(
        RouteExecutionStageResult(
            name="hybrid_fallback",
            documents=documents,
            latency_ms=_elapsed_ms(fallback_start),
            details=coerce_json_object(outcome.to_stage_details()),
        )
    )
    return RouteExecutionOutcome(
        documents=documents,
        stages=stages,
        fallbacks=["graph_empty_to_hybrid"],
    )

def _supplement_documents(
    self,
    request: RouteExecutionRequestPort,
    services: RouteRetrievalServices,
    documents: List[EvidenceDocument],
    stages: List[RouteExecutionStageResult],
) -> List[EvidenceDocument]:
    supplement_k = services.retrieval_profile.candidates.graph_supplement_candidate_k(
        request.top_k
    )
    supplement_start = time.perf_counter()
    outcome = services.traditional_retrieval.hybrid_evidence_search(
        build_route_retrieval_request(
            query=request.query,
            top_k=supplement_k,
            candidate_k=supplement_k,
            constraints=request.constraints,
            query_plan=request.query_plan,
            control=request.retrieval_request.control,
        )
    )
    supplement_docs = list(outcome.documents)
    stages.append(
        RouteExecutionStageResult(
            name="hybrid_supplement",
            documents=supplement_docs,
            latency_ms=_elapsed_ms(supplement_start),
            details=coerce_json_object(outcome.to_stage_details()),
        )
    )
    return merge_route_documents(documents, supplement_docs, limit=supplement_k)
```

`execute()` initializes `stages`, calls `_run_graph_stage`, returns `_hybrid_fallback` on empty documents, calls `_supplement_documents` when fewer than `top_k` documents remain, and constructs the final outcome with an empty fallback list. The concrete request returned by `copy_with` is `RetrievalRequest`.

- [ ] **Step 6: Run focused behavior, structural, and Ruff checks**

Run:

```powershell
python -m pytest tests/test_generation_executor.py tests/test_route_execution_strategies.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/generation/execution/engine.py rag_modules/generation/execution/two_stage.py rag_modules/routing/strategies/graph.py tests/test_hotspot_function_ratchets.py
```

Expected: all tests pass, including cancellation, retry accounting, empty evidence, model fallback, graph fallback, supplement, stage ordering, and trace assertions.

- [ ] **Step 7: Commit online execution reductions**

```powershell
git add tests/test_hotspot_function_ratchets.py rag_modules/generation/execution/engine.py rag_modules/generation/execution/two_stage.py rag_modules/routing/strategies/graph.py
git commit -m "refactor: reduce online execution hotspots"
```

---

### Task 5: Reduce Infrastructure and Domain Transformation Hotspots

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `rag_modules/infra/milvus/writer.py`
- Modify: `rag_modules/domain/shared/semantic_schema.py`
- Test: `tests/test_milvus_writer.py`
- Test: `tests/test_milvus_blue_green.py`
- Test: `tests/test_semantic_schema_branches.py`

**Interfaces:**

- Consumes: `TextDocument`, Milvus operation host/client, semantic term tables.
- Produces: unchanged Milvus boolean write contract and semantic dictionary schema.

- [ ] **Step 1: Remove the final two migration entries**

Delete the entries for `_MilvusWriterOperations.build_vector_index` and `infer_recipe_semantics`. `_MIGRATION_FUNCTION_LENGTH_DEBT` must now be empty.

- [ ] **Step 2: Run the ratchet and verify RED for exactly two targets**

Run the global ratchet test.

Expected: FAIL only for the Milvus writer and recipe semantic inference targets.

- [ ] **Step 3: Extract Milvus entity and batch preparation**

Add these private methods to `_MilvusWriterOperations`:

```python
def _vector_entity(
    self,
    chunk: TextDocument,
    vector: object,
    index: int,
) -> dict[str, object]:
    return {
        "id": self._safe_truncate(chunk.metadata.get("chunk_id", f"chunk_{index}"), 150),
        "vector": vector,
        "text": self._safe_truncate(chunk.page_content, 15000),
        "node_id": self._safe_truncate(chunk.metadata.get("node_id", ""), 100),
        "recipe_name": self._safe_truncate(chunk.metadata.get("recipe_name", ""), 300),
        "node_type": self._safe_truncate(chunk.metadata.get("node_type", ""), 100),
        "category": self._safe_truncate(chunk.metadata.get("category", ""), 100),
        "cuisine_type": self._safe_truncate(chunk.metadata.get("cuisine_type", ""), 200),
        "difficulty": int(chunk.metadata.get("difficulty", 0)),
        "doc_type": self._safe_truncate(chunk.metadata.get("doc_type", ""), 50),
        "chunk_id": self._safe_truncate(
            chunk.metadata.get("chunk_id", f"chunk_{index}"), 150
        ),
        "parent_id": self._safe_truncate(chunk.metadata.get("parent_id", ""), 100),
    }


def _insert_vector_batches(
    self,
    collection_name: str,
    entities: list[dict[str, object]],
) -> None:
    batch_size = 100
    for index in range(0, len(entities), batch_size):
        batch = entities[index : index + batch_size]
        self.client.insert(collection_name=collection_name, data=batch)
        logger.info(
            "已插入 %s/%s 条数据",
            min(index + batch_size, len(entities)),
            len(entities),
        )
```

Build `entities` with a list comprehension over `enumerate(zip(chunks, vectors))`, then call `_insert_vector_batches`. Preserve collection creation, flush, index, load, wait, logs, and the existing catch-all false result.

- [ ] **Step 4: Extract semantic contributions and technique effects**

Add:

```python
def _contribution_relations(
    haystack: str,
) -> tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    contribution_hints: List[Dict[str, Any]] = []
    ingredient_contributions: List[Dict[str, str]] = []
    for effect, causes in _CONTRIBUTION_HINTS.items():
        matched_causes = _contains_terms(haystack, causes)
        if not matched_causes:
            continue
        contribution_hints.append({"effect": effect, "causes": _unique(matched_causes)})
        ingredient_contributions.extend(
            {"source": cause, "effect": effect} for cause in matched_causes
        )
    return contribution_hints, ingredient_contributions


def _technique_effects(haystack: str) -> List[Dict[str, str]]:
    effects: List[Dict[str, str]] = []
    for effect, techniques in _TECHNIQUE_EFFECT_HINTS.items():
        matched = _contains_terms(haystack, techniques)
        effects.extend({"source": item, "effect": effect} for item in _unique(matched))
    return effects
```

Call these helpers after tag extraction and build the same `semantic_relations` dictionary and public return dictionary in the current key order.

- [ ] **Step 5: Run focused behavior, structural, and Ruff checks**

Run:

```powershell
python -m pytest tests/test_milvus_writer.py tests/test_milvus_blue_green.py tests/test_semantic_schema_branches.py tests/test_hotspot_function_ratchets.py -q
python -m ruff check rag_modules/infra/milvus/writer.py rag_modules/domain/shared/semantic_schema.py tests/test_hotspot_function_ratchets.py
```

Expected: all tests pass; metadata truncation, batch order, operational degradation, semantic ordering, and schemas remain unchanged.

- [ ] **Step 6: Commit infrastructure and domain reductions**

```powershell
git add tests/test_hotspot_function_ratchets.py rag_modules/infra/milvus/writer.py rag_modules/domain/shared/semantic_schema.py
git commit -m "refactor: close production function length debt"
```

---

### Task 6: Remove Migration Scaffolding and Verify the Hard Ratchet

**Files:**

- Modify: `tests/test_hotspot_function_ratchets.py`
- Modify: `docs/superpowers/specs/2026-07-13-production-function-length-ratchet-design.md`
- Modify: `docs/superpowers/plans/2026-07-13-production-function-length-ratchet.md`

**Interfaces:**

- Consumes: completed production refactors and the global AST scanner.
- Produces: final empty state-machine allow-list, no migration-debt mechanism, completed plan/spec status, and release evidence.

- [ ] **Step 1: Delete the temporary migration mechanism**

Delete `_MIGRATION_FUNCTION_LENGTH_DEBT` and every debt-validation/debt-exclusion branch. The final oversize predicate must be exactly:

```python
oversize = [
    f"{span.path}:{span.qualified_name} is "
    f"{span.line_count} lines > {MAX_PRODUCTION_FUNCTION_LINES}"
    for span in spans
    if span.line_count > MAX_PRODUCTION_FUNCTION_LINES
    and span.key not in STATE_MACHINE_FUNCTION_ALLOWLIST
]
```

Keep `STATE_MACHINE_FUNCTION_ALLOWLIST = {}` and its strict validation.

- [ ] **Step 2: Verify the hard structural ratchet**

Run:

```powershell
python -m pytest tests/test_hotspot_function_ratchets.py -q
```

Expected: PASS with zero production functions over 80 lines and every stricter named limit passing.

- [ ] **Step 3: Run all focused behavior suites together**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py tests/test_query_calibration_branches.py tests/test_retrieval_service_factories.py tests/test_hybrid_retrieval_runtime.py tests/test_generation_executor.py tests/test_route_execution_strategies.py tests/test_milvus_writer.py tests/test_milvus_blue_green.py tests/test_semantic_schema_branches.py tests/test_hotspot_function_ratchets.py -q --basetemp=.pytest_p0_function_ratchet_focused
```

Expected: exit 0 with no failures or errors.

- [ ] **Step 4: Run formatting, lint, types, and repository hooks**

Run:

```powershell
python -m ruff check rag_modules tests/test_hotspot_function_ratchets.py
python -m ruff format --check rag_modules tests/test_hotspot_function_ratchets.py
python -m mypy --config-file pyproject.toml
pre-commit run --all-files
git diff --check
```

Expected: every command exits 0. If pre-commit modifies files, inspect the diff and repeat all affected focused tests and formatting checks.

- [ ] **Step 5: Run full pytest with a unique Windows base temp**

Run:

```powershell
python -m pytest -q --basetemp=.pytest_p0_function_ratchet_full
```

Expected: exit 0 with no failures or errors.

- [ ] **Step 6: Run release-sensitive gates**

Run:

```powershell
python scripts/release_gate.py
python scripts/local_gate.py
python scripts/pressure_api_service.py --json
```

Expected: release gate and local gate exit 0; pressure output is valid JSON and reports no default-baseline failure.

- [ ] **Step 7: Mark the documents completed**

Change the spec status to `completed` and add `**Status:** completed` beneath this plan title only after all required verification succeeds.

- [ ] **Step 8: Commit final governance and evidence state**

```powershell
git add tests/test_hotspot_function_ratchets.py docs/superpowers/specs/2026-07-13-production-function-length-ratchet-design.md docs/superpowers/plans/2026-07-13-production-function-length-ratchet.md
git commit -m "test: enforce production function length limit"
git status --short --branch
git log --oneline development..HEAD
```

Expected: the commit succeeds; only the three pre-existing untracked pytest temporary directories may remain outside the branch diff; the branch log contains the focused documentation, ratchet, and refactor commits.

---

## Plan Self-Review

- Spec coverage: Task 1 implements scan scope, counting, explicit exceptions, and initial RED evidence. Tasks 2-5 reduce all 11 recorded violations without public API changes. Task 6 removes migration scaffolding and executes every completion gate.
- Type consistency: generation trace helpers use `GenerationSnapshot`; graph stage helpers use `RetrievalRequest` and `EvidenceDocument`; all helper names and types match their owner contracts.
- Scope: changes remain under the approved 11 production owners, one structural test, and the design/plan documents.
- Completion invariant: no migration debt remains, `STATE_MACHINE_FUNCTION_ALLOWLIST` is empty, and the live repository scan reports zero functions over 80 lines.
