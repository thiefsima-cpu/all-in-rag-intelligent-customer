# DTO Type Island Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace stable internal `Any` and `dict[str, Any]` payloads in runtime diagnostics, query policy, graph DTOs, and build-pipeline graph preparation with explicit DTOs and expand the strict type ratchet.

**Architecture:** Keep dynamic data only at JSON, Neo4j, and FastAPI serialization boundaries. Convert boundary payloads into dataclasses at the service or loader edge, update all touched callers to use attributes, and keep `to_dict()` only for serialization. Expand `tests/test_type_contract_ratchets.py` and mypy strict overrides as each island becomes typed.

**Tech Stack:** Python 3.11, dataclasses, Pydantic `JsonValue`, existing `rag_modules.runtime.json_types`, pytest, mypy 2.1.0, Ruff/pre-commit.

---

## File Structure

- Modify `tests/test_type_contract_ratchets.py`: add converted modules to `NO_EXPLICIT_ANY_TARGETS`.
- Modify `tests/test_runtime_diagnostics_service.py`: assert runtime diagnostics expose DTO attributes and preserve response JSON.
- Modify `tests/test_query_policy.py`: assert policy nested sections are DTOs, not raw dictionaries.
- Modify `tests/test_graph_cache_stats.py`: assert graph cache entities round-trip as DTOs.
- Modify `tests/test_graph_reasoning_strategy.py`: assert reasoning accepts graph node/relationship snapshots.
- Modify `tests/test_graph_data_preparation_module.py`: assert load counts and preparation stats are typed DTOs.
- Modify `tests/test_build_pipeline_stats_presenter.py`: assert presenter reads typed stats through the runtime stats adapter boundary.
- Modify `tests/typecheck/type_contracts.py`: add representative assignments for diagnostics, policy, graph, and build-preparation DTOs.
- Modify `rag_modules/app/diagnostics.py`: introduce diagnostics DTOs and remove dict-shaped stable fields.
- Modify `rag_modules/app/services/runtime_diagnostics_service.py`: convert adapter stats into diagnostics DTOs once.
- Modify `rag_modules/query_policy/models.py`: replace raw nested policy dict fields with typed policy dataclasses.
- Modify `rag_modules/query_policy/loader.py`: validate policy JSON into typed policy dataclasses.
- Modify `rag_modules/configuration/model_sections/query_understanding.py`: read typed policy defaults.
- Modify `rag_modules/contracts/query_settings.py`: read typed policy defaults.
- Modify `rag_modules/retrieval/runtime_profile/shared.py`: read typed runtime defaults.
- Modify `rag_modules/generation/decision.py`: use typed generation decision policy.
- Modify `rag_modules/generation/planner.py`: use typed generation rule-plan policy.
- Modify `rag_modules/generation/prompt_builder.py`: use typed answer-type policy.
- Modify `rag_modules/graph/query_resolution.py`: use typed graph sub-question policies.
- Modify `rag_modules/graph/cache_stats.py`: add `GraphCacheEntityStats` and type cache entity lists.
- Modify `rag_modules/graph/retrieval_types.py`: add graph node/relationship snapshots and type `GraphPath`/`KnowledgeSubgraph`.
- Modify `rag_modules/graph/retrieval_postprocess.py`: build graph snapshots at the Neo4j adapter edge.
- Modify `rag_modules/graph/evidence_builder.py`: consume graph snapshot DTOs and serialize only when building evidence metadata.
- Modify `rag_modules/graph/reasoning_strategy.py`: consume graph snapshot DTOs.
- Modify `rag_modules/build_pipeline/graph_preparation/models.py`: use `JsonObject` for raw properties and add document input DTOs.
- Modify `rag_modules/build_pipeline/graph_preparation/loader.py`: type loaded graph records at the loader edge.
- Modify `rag_modules/build_pipeline/graph_preparation/document_builder.py`: consume prepared ingredient and step DTOs.
- Modify `rag_modules/build_pipeline/graph_preparation/statistics.py`: return `GraphPreparationStats`.
- Modify `rag_modules/build_pipeline/graph_preparation/module.py`: return typed load counts and stats.
- Modify `rag_modules/runtime/stats_adapters.py`: serialize typed stats objects at the runtime stats boundary.
- Modify `pyproject.toml`: add the converted modules to the strict mypy override.

## Execution Notes

- Do not add overloads that accept both old dictionaries and new DTOs for the same internal concept.
- Keep public JSON shapes stable by preserving `to_dict()` output keys.
- Use `object`, `Mapping[str, object]`, `JsonObject`, and concrete DTOs instead of `Any`.
- Commit after each task only when the task tests pass.

### Task 1: Runtime Diagnostics DTOs

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/test_runtime_diagnostics_service.py`
- Modify: `tests/typecheck/type_contracts.py`
- Modify: `rag_modules/app/diagnostics.py`
- Modify: `rag_modules/app/services/runtime_diagnostics_service.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing ratchet test**

In `tests/test_type_contract_ratchets.py`, append these paths to `NO_EXPLICIT_ANY_TARGETS`:

```python
    ROOT / "rag_modules" / "app" / "diagnostics.py",
    ROOT / "rag_modules" / "app" / "services" / "runtime_diagnostics_service.py",
```

- [ ] **Step 2: Run the ratchet and verify it fails**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py -q
```

Expected: FAIL with entries from `rag_modules/app/diagnostics.py` that mention explicit `Any`.

- [ ] **Step 3: Write the failing diagnostics behavior test**

In `tests/test_runtime_diagnostics_service.py`, add assertions to `test_collect_system_stats_uses_runtime_stats_access`:

```python
        self.assertEqual(stats.models.llm_model, build_test_config().models.llm_model)
        self.assertEqual(stats.trace_stats.dropped_events, 2)
        self.assertEqual(stats.trace_stats.queued_events, 1)
        self.assertTrue(stats.trace_stats.async_enabled)
        self.assertEqual(stats.data_stats.total_recipes, 2)
        self.assertEqual(stats.index_stats.row_count, 4)
        self.assertEqual(stats.route_stats.total_queries, 3)
        self.assertEqual(
            stats.manifest.build_metadata.config_profile.name,
            "eval_fast",
        )
        payload = stats.to_dict()
        self.assertEqual(payload["models"]["llm_model"], stats.models.llm_model)
        self.assertEqual(payload["trace_stats"]["dropped_events"], 2)
        self.assertEqual(payload["artifact_manifest"]["build_metadata"]["config_profile"]["name"], "eval_fast")
```

In `test_collect_startup_diagnostics_returns_typed_snapshot`, add:

```python
        self.assertEqual(diagnostics.trace_stats.dropped_events, 0)
        self.assertTrue(diagnostics.trace_stats.async_enabled)
        payload = diagnostics.to_dict()
        self.assertEqual(payload["trace_stats"]["queued_events"], 0)
```

- [ ] **Step 4: Run the diagnostics test and verify it fails**

Run:

```powershell
python -m pytest tests/test_runtime_diagnostics_service.py -q
```

Expected: FAIL because `trace_stats`, `data_stats`, `index_stats`, `route_stats`, and `models` are still dictionaries.

- [ ] **Step 5: Implement diagnostics DTOs**

In `rag_modules/app/diagnostics.py`, replace `from typing import Any, Dict, List, Optional` with:

```python
from typing import Optional

from ..runtime.json_types import JsonObject, coerce_json_int, coerce_json_object
```

Add these dataclasses above `ArtifactManifestDiagnostics`:

```python
@dataclass(slots=True)
class ModelDiagnostics:
    embedding_model: str = ""
    llm_model: str = ""
    rerank_model: str = ""

    def to_dict(self) -> JsonObject:
        return {
            "embedding_model": self.embedding_model,
            "llm_model": self.llm_model,
            "rerank_model": self.rerank_model,
        }


@dataclass(slots=True)
class TraceStatsDiagnostics:
    dropped_events: int = 0
    queued_events: int = 0
    emitted_events: int = 0
    failed_events: int = 0
    async_enabled: bool = False

    @classmethod
    def from_payload(cls, payload: object) -> "TraceStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            dropped_events=coerce_json_int(data.get("dropped_events"), 0),
            queued_events=coerce_json_int(data.get("queued_events"), 0),
            emitted_events=coerce_json_int(data.get("emitted_events"), 0),
            failed_events=coerce_json_int(data.get("failed_events"), 0),
            async_enabled=bool(data.get("async_enabled", False)),
        )

    def to_dict(self) -> JsonObject:
        return {
            "dropped_events": self.dropped_events,
            "queued_events": self.queued_events,
            "emitted_events": self.emitted_events,
            "failed_events": self.failed_events,
            "async_enabled": self.async_enabled,
        }
```

Add the remaining stable diagnostics DTOs:

```python
@dataclass(slots=True)
class DataStatsDiagnostics:
    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    cuisines: dict[str, int] = field(default_factory=dict)
    difficulties: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0

    @classmethod
    def from_payload(cls, payload: object) -> "DataStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            total_recipes=coerce_json_int(data.get("total_recipes"), 0),
            total_ingredients=coerce_json_int(data.get("total_ingredients"), 0),
            total_cooking_steps=coerce_json_int(data.get("total_cooking_steps"), 0),
            total_documents=coerce_json_int(data.get("total_documents"), 0),
            total_chunks=coerce_json_int(data.get("total_chunks"), 0),
            categories=_int_map(data.get("categories")),
            cuisines=_int_map(data.get("cuisines")),
            difficulties=_int_map(data.get("difficulties")),
            avg_content_length=float(data.get("avg_content_length") or 0.0),
            avg_chunk_size=float(data.get("avg_chunk_size") or 0.0),
        )

    def to_dict(self) -> JsonObject:
        return {
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "categories": dict(self.categories),
            "cuisines": dict(self.cuisines),
            "difficulties": dict(self.difficulties),
            "avg_content_length": self.avg_content_length,
            "avg_chunk_size": self.avg_chunk_size,
        }


@dataclass(slots=True)
class IndexStatsDiagnostics:
    row_count: int = 0

    @classmethod
    def from_payload(cls, payload: object) -> "IndexStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(row_count=coerce_json_int(data.get("row_count"), 0))

    def to_dict(self) -> JsonObject:
        return {"row_count": self.row_count}


@dataclass(slots=True)
class RouteStatsDiagnostics:
    total_queries: int = 0

    @classmethod
    def from_payload(cls, payload: object) -> "RouteStatsDiagnostics":
        data = coerce_json_object(payload)
        return cls(total_queries=coerce_json_int(data.get("total_queries"), 0))

    def to_dict(self) -> JsonObject:
        return {"total_queries": self.total_queries}
```

Add helper and metadata DTO:

```python
@dataclass(slots=True)
class ConfigProfileDiagnostics:
    name: str = ""
    path: str = ""
    hash: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> "ConfigProfileDiagnostics":
        data = coerce_json_object(payload)
        return cls(
            name=str(data.get("name") or ""),
            path=str(data.get("path") or ""),
            hash=str(data.get("hash") or ""),
        )

    def to_dict(self) -> JsonObject:
        return {"name": self.name, "path": self.path, "hash": self.hash}


@dataclass(slots=True)
class ArtifactBuildMetadataDiagnostics:
    config_profile: ConfigProfileDiagnostics = field(default_factory=ConfigProfileDiagnostics)
    extra: JsonObject = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: object) -> "ArtifactBuildMetadataDiagnostics":
        data = coerce_json_object(payload)
        config_profile = ConfigProfileDiagnostics.from_payload(data.get("config_profile"))
        extra = {key: value for key, value in data.items() if key != "config_profile"}
        return cls(config_profile=config_profile, extra=extra)

    def to_dict(self) -> JsonObject:
        payload = dict(self.extra)
        payload["config_profile"] = self.config_profile.to_dict()
        return payload


def _int_map(payload: object) -> dict[str, int]:
    data = coerce_json_object(payload)
    return {str(key): coerce_json_int(value, 0) for key, value in data.items()}
```

Update `ArtifactManifestDiagnostics.build_metadata` to `ArtifactBuildMetadataDiagnostics`, call `ArtifactBuildMetadataDiagnostics.from_payload(manifest.build_metadata)`, and serialize with `self.build_metadata.to_dict()`.

Update `StartupDiagnostics.trace_stats` to `TraceStatsDiagnostics`, `SystemStatsDiagnostics.models` to `ModelDiagnostics`, `SystemStatsDiagnostics.trace_stats` to `TraceStatsDiagnostics`, `SystemStatsDiagnostics.data_stats` to `DataStatsDiagnostics`, `SystemStatsDiagnostics.index_stats` to `IndexStatsDiagnostics`, and `SystemStatsDiagnostics.route_stats` to `RouteStatsDiagnostics`. Replace dictionary `.get(...)` uses in `to_lines()` with DTO attributes.

- [ ] **Step 6: Convert service output once**

In `rag_modules/app/services/runtime_diagnostics_service.py`, wrap adapter payloads before constructing diagnostics:

```python
            models=ModelDiagnostics(
                embedding_model=models.embedding_model,
                llm_model=models.llm_model,
                rerank_model=models.rerank_model,
            ),
            trace_stats=TraceStatsDiagnostics.from_payload(trace_stats),
            retrieval_runtime_profile=coerce_json_object(runtime_profile),
            data_stats=DataStatsDiagnostics.from_payload(data_stats),
            index_stats=IndexStatsDiagnostics.from_payload(index_stats),
            route_stats=RouteStatsDiagnostics.from_payload(route_stats),
```

For `StartupDiagnostics`, pass `TraceStatsDiagnostics.from_payload(trace_stats)`.

- [ ] **Step 7: Add typecheck fixture assignments**

In `tests/typecheck/type_contracts.py`, add:

```python
from rag_modules.app.diagnostics import DataStatsDiagnostics, TraceStatsDiagnostics

trace_stats: TraceStatsDiagnostics = TraceStatsDiagnostics.from_payload({"dropped_events": 1})
data_stats: DataStatsDiagnostics = DataStatsDiagnostics.from_payload({"total_recipes": 2})
```

- [ ] **Step 8: Expand strict mypy modules**

In `pyproject.toml`, add:

```toml
  "rag_modules.app.diagnostics",
  "rag_modules.app.services.runtime_diagnostics_service",
```

- [ ] **Step 9: Run the task checks**

Run:

```powershell
python -m pytest tests/test_runtime_diagnostics_service.py tests/test_type_contract_ratchets.py -q
python -m mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 10: Commit runtime diagnostics convergence**

Run:

```powershell
git add tests/test_type_contract_ratchets.py tests/test_runtime_diagnostics_service.py tests/typecheck/type_contracts.py rag_modules/app/diagnostics.py rag_modules/app/services/runtime_diagnostics_service.py pyproject.toml
git commit -m "refactor: type runtime diagnostics dto island"
```

### Task 2: Query Policy DTOs and Callers

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/test_query_policy.py`
- Modify: `tests/typecheck/type_contracts.py`
- Modify: `rag_modules/query_policy/models.py`
- Modify: `rag_modules/query_policy/loader.py`
- Modify: `rag_modules/configuration/model_sections/query_understanding.py`
- Modify: `rag_modules/contracts/query_settings.py`
- Modify: `rag_modules/retrieval/runtime_profile/shared.py`
- Modify: `rag_modules/generation/decision.py`
- Modify: `rag_modules/generation/planner.py`
- Modify: `rag_modules/generation/prompt_builder.py`
- Modify: `rag_modules/graph/query_resolution.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing query policy tests**

In `tests/test_query_policy.py`, replace the raw-dict assertions in `test_policy_bundle_preserves_structured_policy_sections` with:

```python
        sub_question = bundle.graph.sub_questions[0]
        self.assertEqual("fallback", sub_question.id)
        self.assertTrue(sub_question.when.fallback)
        self.assertIn("direct_answer", bundle.generation.answer_types)
        self.assertEqual((), bundle.generation.answer_types["direct_answer"].markers)
        self.assertEqual(
            "direct_answer",
            bundle.generation.decision.default_answer_type,
        )
        self.assertEqual(
            bundle.generation.decision.reasons.graph_rag,
            "graph_rag",
        )
        self.assertTrue(bundle.generation.rule_plan.default_outline)
        self.assertEqual("test", _minimal_policy_payload()["runtime_defaults"]["planner"]["model_name"])
```

Add a new test:

```python
def test_policy_runtime_defaults_are_typed_sections(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import load_policy_bundle

    _write_bundle(tmp_path)
    load_policy_bundle.cache_clear()
    bundle = load_policy_bundle(tmp_path)

    self.assertEqual(bundle.runtime_defaults.planner.model_name, "test")
    self.assertEqual(bundle.runtime_defaults.semantics.default_max_depth, 2)
```

- [ ] **Step 2: Write the failing ratchet test**

In `tests/test_type_contract_ratchets.py`, append:

```python
    ROOT / "rag_modules" / "query_policy" / "models.py",
    ROOT / "rag_modules" / "query_policy" / "loader.py",
```

- [ ] **Step 3: Run query policy tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_type_contract_ratchets.py -q
```

Expected: FAIL because `sub_questions`, `answer_types`, `rule_plan`, `decision`, and `runtime_defaults` still expose raw dictionaries and explicit `Any`.

- [ ] **Step 4: Implement typed query policy models**

In `rag_modules/query_policy/models.py`, replace raw nested policy fields with DTOs:

```python
@dataclass(frozen=True)
class GraphSubQuestionCondition:
    fallback: bool = False
    entities_present: bool | None = None
    relation_types_any: Tuple[str, ...] = ()
    constraints_present: Tuple[str, ...] = ()
    constraints_present_any: bool = False
    relationship_intensity_at_least: float | None = None
    query_markers_any: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GraphSubQuestionPolicy:
    id: str
    template: str
    when: GraphSubQuestionCondition

    def render(
        self,
        *,
        query: str,
        entities: Sequence[str],
        relation_types: Sequence[str],
    ) -> str:
        return self.template.format(
            query=query,
            entities=", ".join(list(entities)[:4]),
            relation_types=", ".join(relation_types),
        )


@dataclass(frozen=True)
class GenerationAnswerTypePolicy:
    markers: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GenerationRulePlanPolicy:
    default_outline: Tuple[str, ...]
    fallback_outline: Tuple[str, ...]
    graph_caution: str
    missing_relation_evidence: str
    sparse_evidence: str
    missing_information_caution: str
    fallback_claim_template: str


@dataclass(frozen=True)
class GenerationDecisionReasonsPolicy:
    two_stage_disabled: str
    no_route_analysis: str
    graph_without_analysis: str
    graph_rag: str
    combined_pressure: str
    high_pressure: str
    simple: str


@dataclass(frozen=True)
class GenerationDecisionPolicy:
    default_answer_type: str
    high_pressure_margin: float
    reasons: GenerationDecisionReasonsPolicy
```

Add typed runtime defaults:

```python
@dataclass(frozen=True)
class PlannerRuntimeDefaultsPolicy:
    model_name: str = "qwen3.7-plus"
    cache_size: int = 128
    timeout_seconds: int = 20
    fast_rule_planning: bool = True
    llm_temperature: float = 0.0
    llm_max_tokens: int = 1200


@dataclass(frozen=True)
class RuntimeDefaultsPolicy:
    planner: PlannerRuntimeDefaultsPolicy
    semantics: QuerySemanticRuntimeDefaultsPolicy
    candidates: CandidateRuntimeDefaultsPolicy
    candidate_sources: CandidateSourceRuntimeDefaultsPolicy
    postprocess: PostProcessRuntimeDefaultsPolicy
```

Define `QuerySemanticRuntimeDefaultsPolicy`, `CandidateRuntimeDefaultsPolicy`, `CandidateSourceRuntimeDefaultsPolicy`, and `PostProcessRuntimeDefaultsPolicy` with the field names currently read through `_SEMANTIC_DEFAULTS`, `_CANDIDATE_DEFAULTS`, `_CANDIDATE_SOURCE_DEFAULTS`, and `_POSTPROCESS_DEFAULTS`.

Update existing dataclasses:

```python
@dataclass(frozen=True)
class GraphPolicy:
    max_depth: Dict[str, int]
    max_nodes: Dict[str, int]
    sub_questions: Tuple[GraphSubQuestionPolicy, ...]
    reasoning: GraphReasoningPolicy


@dataclass(frozen=True)
class GenerationPolicy:
    answer_types: Dict[str, GenerationAnswerTypePolicy]
    relation_explanation_markers: Tuple[str, ...]
    rule_plan: GenerationRulePlanPolicy
    decision: GenerationDecisionPolicy
    fallback_answer: Dict[str, str]


@dataclass(frozen=True)
class QueryPolicyBundle:
    metadata: PolicyMetadata
    lexicon: LexiconPolicy
    relations: RelationPolicy
    scoring: ScoringPolicy
    routing: RoutingPolicy
    graph: GraphPolicy
    generation: GenerationPolicy
    runtime_defaults: RuntimeDefaultsPolicy
    prompts: PromptTemplates
```

Remove `QueryPolicyBundle.runtime_section()`.

- [ ] **Step 5: Implement typed loader conversion**

In `rag_modules/query_policy/loader.py`, replace `Any` with `object` and `Mapping[str, object]`. Add loader helpers:

```python
def _mapping(value: object, root: Path, field_path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy field must be an object: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    return value


def _to_sub_question_condition(
    value: object,
    root: Path,
    field_path: str,
) -> GraphSubQuestionCondition:
    payload = _mapping(value or {}, root, field_path)
    constraints_rule = payload.get("constraints_present")
    constraints_any = bool(constraints_rule) if isinstance(constraints_rule, bool) else False
    constraint_fields = () if isinstance(constraints_rule, bool) else _to_tuple(constraints_rule)
    return GraphSubQuestionCondition(
        fallback=bool(payload.get("fallback", False)),
        entities_present=(
            bool(payload["entities_present"]) if "entities_present" in payload else None
        ),
        relation_types_any=_to_tuple(payload.get("relation_types_any")),
        constraints_present=constraint_fields,
        constraints_present_any=constraints_any,
        relationship_intensity_at_least=(
            float(payload["relationship_intensity_at_least"])
            if payload.get("relationship_intensity_at_least") is not None
            else None
        ),
        query_markers_any=_to_tuple(payload.get("query_markers_any")),
    )
```

Replace `_to_sub_question_items()` so it returns `Tuple[GraphSubQuestionPolicy, ...]`.

Add `_to_generation_answer_types()`, `_to_generation_rule_plan()`, `_to_generation_decision()`, and `_to_runtime_defaults()` that return the DTOs from Step 4.

- [ ] **Step 6: Update policy callers**

Update `rag_modules/configuration/model_sections/query_understanding.py`, `rag_modules/contracts/query_settings.py`, and `rag_modules/retrieval/runtime_profile/shared.py` to read typed defaults:

```python
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_defaults.planner
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_defaults.semantics
```

Replace `.get("field", default)` default reads with attributes, for example:

```python
cache_size: int = _PLANNER_DEFAULTS.cache_size
fast_rule_planning: bool = _PLANNER_DEFAULTS.fast_rule_planning
relation_intensity_reference_ratio: float = _SEMANTIC_DEFAULTS.relation_intensity_reference_ratio
```

Update `rag_modules/generation/decision.py`:

```python
    decision_policy = get_query_policy().generation.decision
    reasons = decision_policy.reasons
    high_pressure_margin = decision_policy.high_pressure_margin
```

Then replace `str(reasons["graph_rag"])` with `reasons.graph_rag`, and do the same for each reason.

Update `rag_modules/generation/planner.py`:

```python
    def _rule_plan_list(self, key: str) -> list[str]:
        values = getattr(self.rule_plan_policy, key)
        return [str(item) for item in values if str(item).strip()]

    def _rule_plan_text(self, key: str) -> str:
        return str(getattr(self.rule_plan_policy, key))
```

Update `rag_modules/generation/prompt_builder.py`:

```python
        for answer_type, config in self.generation_policy.answer_types.items():
            markers = config.markers
            if markers and any(marker in question for marker in markers):
                return answer_type
        return self.generation_policy.decision.default_answer_type
```

Update `rag_modules/graph/query_resolution.py` so `decompose_graph_question()` iterates `GraphSubQuestionPolicy` values and calls `rule.render(...)`.

- [ ] **Step 7: Add typecheck fixture assignments**

In `tests/typecheck/type_contracts.py`, add:

```python
from rag_modules.query_policy import get_query_policy
from rag_modules.query_policy.models import GraphSubQuestionPolicy, GenerationDecisionPolicy

policy_bundle = get_query_policy()
first_sub_question: GraphSubQuestionPolicy = policy_bundle.graph.sub_questions[0]
generation_decision_policy: GenerationDecisionPolicy = policy_bundle.generation.decision
```

- [ ] **Step 8: Expand strict mypy modules**

In `pyproject.toml`, add:

```toml
  "rag_modules.query_policy.models",
  "rag_modules.query_policy.loader",
```

- [ ] **Step 9: Run the task checks**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_generation_prompt_contract.py tests/test_generation_plan_smoke.py tests/test_graph_retrieval_executor.py tests/test_type_contract_ratchets.py -q
python -m mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 10: Commit query policy convergence**

Run:

```powershell
git add tests/test_query_policy.py tests/test_type_contract_ratchets.py tests/typecheck/type_contracts.py rag_modules/query_policy/models.py rag_modules/query_policy/loader.py rag_modules/configuration/model_sections/query_understanding.py rag_modules/contracts/query_settings.py rag_modules/retrieval/runtime_profile/shared.py rag_modules/generation/decision.py rag_modules/generation/planner.py rag_modules/generation/prompt_builder.py rag_modules/graph/query_resolution.py pyproject.toml
git commit -m "refactor: type query policy dto island"
```

### Task 3: Graph Cache and Retrieval DTOs

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/test_graph_cache_stats.py`
- Modify: `tests/test_graph_reasoning_strategy.py`
- Modify: `tests/typecheck/type_contracts.py`
- Modify: `rag_modules/graph/cache_stats.py`
- Modify: `rag_modules/graph/retrieval_types.py`
- Modify: `rag_modules/graph/retrieval_postprocess.py`
- Modify: `rag_modules/graph/evidence_builder.py`
- Modify: `rag_modules/graph/reasoning_strategy.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing graph DTO tests**

In `tests/test_graph_cache_stats.py`, update construction and assertions:

```python
from rag_modules.graph.cache import GraphCacheEntityStats, GraphCacheStats, GraphCacheStatsStore
```

Use DTO entities:

```python
                entities=[
                    GraphCacheEntityStats(name="mapo tofu", label="Recipe"),
                    GraphCacheEntityStats(name="pepper", label="Ingredient"),
                ],
```

Add:

```python
            self.assertEqual(loaded.entities[0].name, "mapo tofu")
            self.assertEqual(loaded.to_dict()["entities"][0]["label"], "Recipe")
```

In `tests/test_graph_reasoning_strategy.py`, replace raw node and relationship dictionaries with:

```python
from rag_modules.graph.retrieval_types import (
    GraphNodeSnapshot,
    GraphRelationshipSnapshot,
    KnowledgeSubgraph,
)
```

Use:

```python
            central_nodes=[
                GraphNodeSnapshot(node_id="r1", name="mapo tofu", labels=("Recipe",))
            ],
            connected_nodes=[
                GraphNodeSnapshot(node_id="e1", name="umami", labels=("SemanticEffect",)),
                GraphNodeSnapshot(node_id="f1", name="spicy", labels=("Flavor",)),
            ],
            relationships=[
                GraphRelationshipSnapshot(
                    relation_type=causal_relation,
                    start_node_id="r1",
                    end_node_id="e1",
                ),
                GraphRelationshipSnapshot(
                    relation_type=compositional_relation,
                    start_node_id="r1",
                    end_node_id="f1",
                ),
            ],
```

- [ ] **Step 2: Write the failing ratchet test**

In `tests/test_type_contract_ratchets.py`, append:

```python
    ROOT / "rag_modules" / "graph" / "cache_stats.py",
    ROOT / "rag_modules" / "graph" / "retrieval_types.py",
    ROOT / "rag_modules" / "graph" / "retrieval_postprocess.py",
    ROOT / "rag_modules" / "graph" / "evidence_builder.py",
    ROOT / "rag_modules" / "graph" / "reasoning_strategy.py",
```

- [ ] **Step 3: Run graph tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_graph_cache_stats.py tests/test_graph_reasoning_strategy.py tests/test_type_contract_ratchets.py -q
```

Expected: FAIL because graph cache stats and retrieval subgraphs still use dictionaries and explicit `Any`.

- [ ] **Step 4: Implement graph retrieval snapshots**

In `rag_modules/graph/retrieval_types.py`, replace raw node and relationship dict fields with:

```python
from collections.abc import Mapping, Sequence

from ..runtime.json_types import JsonObject, coerce_json_object
```

Add:

```python
@dataclass(slots=True, frozen=True)
class GraphNodeSnapshot:
    node_id: str = ""
    name: str = ""
    labels: tuple[str, ...] = ()
    category: str = ""
    properties: JsonObject = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "GraphNodeSnapshot":
        labels = payload.get("labels") or payload.get("originalLabels") or ()
        if isinstance(labels, str):
            label_tuple = (labels,)
        elif isinstance(labels, Sequence):
            label_tuple = tuple(str(label) for label in labels if str(label).strip())
        else:
            label_tuple = ()
        node_id = str(payload.get("nodeId") or payload.get("id") or "")
        name = str(payload.get("name") or payload.get("title") or node_id)
        category = str(payload.get("category") or "")
        properties = coerce_json_object(payload.get("properties"))
        return cls(
            node_id=node_id,
            name=name,
            labels=label_tuple,
            category=category,
            properties=properties,
        )

    def has_label(self, label: str) -> bool:
        return label in self.labels

    def to_dict(self) -> JsonObject:
        payload = dict(self.properties)
        payload.update(
            {
                "nodeId": self.node_id,
                "id": self.node_id,
                "name": self.name,
                "labels": list(self.labels),
            }
        )
        if self.category:
            payload["category"] = self.category
        return payload


@dataclass(slots=True, frozen=True)
class GraphRelationshipSnapshot:
    relation_type: str = ""
    start_node_id: str = ""
    end_node_id: str = ""
    properties: JsonObject = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "GraphRelationshipSnapshot":
        return cls(
            relation_type=str(payload.get("type") or ""),
            start_node_id=str(payload.get("startNodeId") or ""),
            end_node_id=str(payload.get("endNodeId") or ""),
            properties=coerce_json_object(payload.get("properties")),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.properties)
        payload.update(
            {
                "type": self.relation_type,
                "startNodeId": self.start_node_id,
                "endNodeId": self.end_node_id,
            }
        )
        return payload
```

Update:

```python
@dataclass
class GraphPath:
    nodes: List[GraphNodeSnapshot] = field(default_factory=list)
    relationships: List[GraphRelationshipSnapshot] = field(default_factory=list)
    path_length: int = 0
    relevance_score: float = 0.0
    path_type: str = ""


@dataclass
class KnowledgeSubgraph:
    central_nodes: List[GraphNodeSnapshot] = field(default_factory=list)
    connected_nodes: List[GraphNodeSnapshot] = field(default_factory=list)
    relationships: List[GraphRelationshipSnapshot] = field(default_factory=list)
    graph_metrics: Dict[str, float] = field(default_factory=dict)
    reasoning_chains: List[List[str] | str] = field(default_factory=list)
```

- [ ] **Step 5: Implement graph cache entity DTOs**

In `rag_modules/graph/cache_stats.py`, add:

```python
@dataclass(slots=True, frozen=True)
class GraphCacheEntityStats:
    name: str = ""
    label: str = ""

    @classmethod
    def from_payload(cls, payload: object) -> "GraphCacheEntityStats":
        data = coerce_json_object(payload)
        return cls(name=str(data.get("name") or ""), label=str(data.get("label") or ""))

    def to_dict(self) -> JsonObject:
        return {"name": self.name, "label": self.label}
```

Change `GraphCacheStats.entities` to `List[GraphCacheEntityStats]`. Update `to_dict()` and `from_dict()` to call `entity.to_dict()` and `GraphCacheEntityStats.from_payload(item)`.

- [ ] **Step 6: Update graph post-processing and evidence builders**

In `rag_modules/graph/retrieval_postprocess.py`, construct DTOs:

```python
path_nodes.append(
    GraphNodeSnapshot(
        node_id=str(properties.get("nodeId") or ""),
        name=str(properties.get("name") or ""),
        labels=tuple(str(label) for label in getattr(node, "labels", []) if str(label)),
        properties=coerce_json_object(properties),
    )
)
```

For relationships:

```python
relationships.append(
    GraphRelationshipSnapshot(
        relation_type=str(rel.type),
        properties=coerce_json_object(dict(rel)),
    )
)
```

Update `merge_subgraphs()` to use `node.node_id`, `node.name`, `rel.start_node_id`, `rel.relation_type`, and `rel.end_node_id`.

In `rag_modules/graph/evidence_builder.py`, change protocols to use DTO lists and replace dictionary lookups:

```python
def node_labels(node: GraphNodeSnapshot) -> List[str]:
    return list(node.labels)


def node_name(node: GraphNodeSnapshot) -> str:
    return node.name or node.node_id or "unknown_node"
```

Serialize graph DTOs in metadata:

```python
graph_evidence = {
    "nodes": [node.to_dict() for node in path.nodes],
    "relationships": [rel.to_dict() for rel in path.relationships],
    "description": path_desc,
    "matched_ingredients": ingredient_names,
    "matched_steps": step_names,
    "semantic_nodes": semantic_names,
}
```

In `rag_modules/graph/reasoning_strategy.py`, replace `_node_labels(node)` and `_node_name(node)` with attribute-based helpers and make `GraphReasoningOutcome.summary` a `JsonObject`.

- [ ] **Step 7: Add typecheck fixture assignments**

In `tests/typecheck/type_contracts.py`, add:

```python
from rag_modules.graph.retrieval_types import GraphNodeSnapshot, GraphRelationshipSnapshot

graph_node_snapshot: GraphNodeSnapshot = GraphNodeSnapshot(node_id="r1", name="recipe")
graph_relationship_snapshot: GraphRelationshipSnapshot = GraphRelationshipSnapshot(
    relation_type="RELATED",
    start_node_id="r1",
    end_node_id="i1",
)
```

- [ ] **Step 8: Expand strict mypy modules**

In `pyproject.toml`, add:

```toml
  "rag_modules.graph.cache_stats",
  "rag_modules.graph.retrieval_types",
  "rag_modules.graph.retrieval_postprocess",
  "rag_modules.graph.evidence_builder",
  "rag_modules.graph.reasoning_strategy",
```

- [ ] **Step 9: Run the task checks**

Run:

```powershell
python -m pytest tests/test_graph_cache_stats.py tests/test_graph_reasoning_strategy.py tests/test_graph_retrieval_executor.py tests/test_type_contract_ratchets.py -q
python -m mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 10: Commit graph DTO convergence**

Run:

```powershell
git add tests/test_graph_cache_stats.py tests/test_graph_reasoning_strategy.py tests/test_type_contract_ratchets.py tests/typecheck/type_contracts.py rag_modules/graph/cache_stats.py rag_modules/graph/retrieval_types.py rag_modules/graph/retrieval_postprocess.py rag_modules/graph/evidence_builder.py rag_modules/graph/reasoning_strategy.py pyproject.toml
git commit -m "refactor: type graph dto island"
```

### Task 4: Build-Pipeline Graph Preparation DTOs

**Files:**
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/test_graph_data_preparation_module.py`
- Modify: `tests/test_build_pipeline_stats_presenter.py`
- Modify: `tests/typecheck/type_contracts.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/models.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/loader.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/document_builder.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/statistics.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/module.py`
- Modify: `rag_modules/runtime/stats_adapters.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing build-preparation tests**

In `tests/test_graph_data_preparation_module.py`, update `test_load_graph_data_normalizes_recipe_categories`:

```python
        counts = module.load_graph_data()

        self.assertEqual(counts.recipes, 1)
        self.assertEqual(counts.ingredients, 2)
        self.assertEqual(counts.cooking_steps, 1)
```

Update `test_chunking_and_statistics_follow_section_boundaries`:

```python
        self.assertEqual(stats.total_recipes, 1)
        self.assertEqual(stats.total_documents, 1)
        self.assertEqual(stats.total_chunks, 6)
        self.assertEqual(list(stats.categories.values()), [1])
        self.assertEqual(list(stats.cuisines.values()), [1])
        self.assertGreater(stats.avg_chunk_size, 0)
        self.assertEqual(stats.to_dict()["total_recipes"], 1)
```

In `tests/test_build_pipeline_stats_presenter.py`, update the fake stats access to call `to_dict()` when present:

```python
    def get_graph_data_stats(self, data_module):
        self.graph_stats_calls += 1
        stats = data_module.get_statistics()
        return stats.to_dict()
```

- [ ] **Step 2: Write the failing ratchet test**

In `tests/test_type_contract_ratchets.py`, append:

```python
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "models.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "statistics.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "document_builder.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "loader.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "module.py",
```

- [ ] **Step 3: Run build-preparation tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_graph_data_preparation_module.py tests/test_build_pipeline_stats_presenter.py tests/test_type_contract_ratchets.py -q
```

Expected: FAIL because load counts and statistics still return dictionaries and graph-preparation modules still use explicit `Any`.

- [ ] **Step 4: Implement graph-preparation DTOs**

In `rag_modules/build_pipeline/graph_preparation/models.py`, import `JsonObject` and add:

```python
@dataclass(slots=True, frozen=True)
class GraphLoadCounts:
    recipes: int = 0
    ingredients: int = 0
    cooking_steps: int = 0

    def to_dict(self) -> JsonObject:
        return {
            "recipes": self.recipes,
            "ingredients": self.ingredients,
            "cooking_steps": self.cooking_steps,
        }


@dataclass(slots=True, frozen=True)
class PreparedIngredientInput:
    recipe_id: str
    name: str = ""
    category: str = ""
    amount: str = ""
    unit: str = ""
    description: str = ""


@dataclass(slots=True, frozen=True)
class PreparedStepInput:
    recipe_id: str
    name: str = ""
    description: str = ""
    step_number: int = 0
    methods: str = ""
    tools: str = ""
    time_estimate: str = ""
    step_order: int = 0
```

Change `GraphNode.properties` and `GraphRelation.properties` to `JsonObject`.

- [ ] **Step 5: Implement typed loader records**

In `rag_modules/build_pipeline/graph_preparation/loader.py`, replace `session: Any` with a small protocol:

```python
class Neo4jSessionLike(Protocol):
    def run(self, query: str, parameters: Mapping[str, object] | None = None) -> Iterable[Mapping[str, object]]: ...
```

Update `LoadedGraphData.to_counts()` to return `GraphLoadCounts`.

In `rag_modules/build_pipeline/graph_preparation/document_builder.py`, return typed records:

```python
    ) -> dict[str, list[PreparedIngredientInput]]:
        ingredients_by_recipe: dict[str, list[PreparedIngredientInput]] = defaultdict(list)
        with driver.session(database=database) as session:
            for record in session.run(RECIPE_INGREDIENTS_QUERY, {"recipe_ids": recipe_ids}):
                ingredients_by_recipe[str(record["recipe_id"])].append(
                    PreparedIngredientInput(
                        recipe_id=str(record["recipe_id"]),
                        name=str(record.get("name") or ""),
                        category=str(record.get("category") or ""),
                        amount=str(record.get("amount") or ""),
                        unit=str(record.get("unit") or ""),
                        description=str(record.get("description") or ""),
                    )
                )
        return dict(ingredients_by_recipe)
```

Use `PreparedStepInput` for steps. Change `build_document()` to accept `list[PreparedIngredientInput]` and `list[PreparedStepInput]`. Update `_format_ingredient_line()` and `_format_step_text()` to use attributes.

- [ ] **Step 6: Implement typed preparation statistics**

In `rag_modules/build_pipeline/graph_preparation/statistics.py`, add:

```python
@dataclass(slots=True, frozen=True)
class GraphPreparationStats:
    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    cuisines: dict[str, int] = field(default_factory=dict)
    difficulties: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0

    def to_dict(self) -> JsonObject:
        return {
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "categories": dict(self.categories),
            "cuisines": dict(self.cuisines),
            "difficulties": dict(self.difficulties),
            "avg_content_length": self.avg_content_length,
            "avg_chunk_size": self.avg_chunk_size,
        }
```

Change `GraphPreparationStatisticsService.build()` to return `GraphPreparationStats`.

In `rag_modules/build_pipeline/graph_preparation/module.py`, change:

```python
    def load_graph_data(self) -> GraphLoadCounts:
        loaded = self.loader.load(self.driver, database=self.database)
        self.recipes = loaded.recipes
        self.ingredients = loaded.ingredients
        self.cooking_steps = loaded.cooking_steps
        return loaded.to_counts()

    def get_statistics(self) -> GraphPreparationStats:
        return self.statistics_service.build(self.state)
```

- [ ] **Step 7: Serialize typed stats at the runtime stats boundary**

In `rag_modules/runtime/stats_adapters.py`, keep the port returning `JsonObject` and rely on `coerce_json_object(data_module.get_statistics())`. The existing `coerce_json_value()` already calls `to_dict()` when present, so the adapter boundary remains the serialization point.

- [ ] **Step 8: Add typecheck fixture assignments**

In `tests/typecheck/type_contracts.py`, add:

```python
from rag_modules.build_pipeline.graph_preparation.models import GraphLoadCounts
from rag_modules.build_pipeline.graph_preparation.statistics import GraphPreparationStats

graph_load_counts: GraphLoadCounts = GraphLoadCounts(recipes=1)
graph_preparation_stats: GraphPreparationStats = GraphPreparationStats(total_recipes=1)
```

- [ ] **Step 9: Expand strict mypy modules**

In `pyproject.toml`, add:

```toml
  "rag_modules.build_pipeline.graph_preparation.models",
  "rag_modules.build_pipeline.graph_preparation.statistics",
  "rag_modules.build_pipeline.graph_preparation.document_builder",
  "rag_modules.build_pipeline.graph_preparation.loader",
  "rag_modules.build_pipeline.graph_preparation.module",
```

- [ ] **Step 10: Run the task checks**

Run:

```powershell
python -m pytest tests/test_graph_data_preparation_module.py tests/test_build_pipeline_stats_presenter.py tests/test_type_contract_ratchets.py -q
python -m mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 11: Commit build-preparation convergence**

Run:

```powershell
git add tests/test_graph_data_preparation_module.py tests/test_build_pipeline_stats_presenter.py tests/test_type_contract_ratchets.py tests/typecheck/type_contracts.py rag_modules/build_pipeline/graph_preparation/models.py rag_modules/build_pipeline/graph_preparation/loader.py rag_modules/build_pipeline/graph_preparation/document_builder.py rag_modules/build_pipeline/graph_preparation/statistics.py rag_modules/build_pipeline/graph_preparation/module.py rag_modules/runtime/stats_adapters.py pyproject.toml
git commit -m "refactor: type graph preparation dto island"
```

### Task 5: Final Ratchet and Release Checks

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/typecheck/type_contracts.py`

- [ ] **Step 1: Run the complete ratchet**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py tests/test_runtime_type_contracts.py -q
```

Expected: PASS.

- [ ] **Step 2: Run focused subsystem tests**

Run:

```powershell
python -m pytest tests/test_runtime_diagnostics_service.py tests/test_query_policy.py tests/test_graph_cache_stats.py tests/test_graph_reasoning_strategy.py tests/test_graph_retrieval_executor.py tests/test_graph_data_preparation_module.py tests/test_build_pipeline_stats_presenter.py -q
```

Expected: PASS.

- [ ] **Step 3: Run mypy**

Run:

```powershell
python -m mypy --config-file pyproject.toml
```

Expected: PASS.

- [ ] **Step 4: Run Ruff/pre-commit**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff rewrites files, inspect the diff and rerun the focused tests from Step 2.

- [ ] **Step 5: Run release-sensitive gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 6: Commit final verification cleanup**

If Step 4 changed formatting or Step 5 required a small checked-in fix, run:

```powershell
git add pyproject.toml tests/test_type_contract_ratchets.py tests/typecheck/type_contracts.py
git commit -m "test: ratchet dto type island"
```

If there are no changes after verification, do not create an empty commit.

## Self-Review

- Spec coverage: Task 1 covers runtime diagnostics DTOs. Task 2 covers typed query policy and internal caller migration. Task 3 covers graph cache/retrieval DTOs and Neo4j adapter isolation. Task 4 covers build-pipeline graph-preparation DTOs and typed stats. Task 5 covers ratchet, mypy, pre-commit, and release gate verification.
- Placeholder scan: no unresolved markers, no deferred code sections, and no dual-API compatibility step.
- Type consistency: DTO names used in tests match the production model names in the plan.
