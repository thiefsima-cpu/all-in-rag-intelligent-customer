# Policy Versioning Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered prompt, routing, scoring, relation, graph-question, trace, and eval policy with one validated, versioned policy bundle.

**Architecture:** The policy bundle lives under `rag_modules/query_policy/resources/<bundle>/` with `manifest.json`, `policy.json`, and prompt templates. `rag_modules.query_policy` exposes typed immutable policy models plus metadata hashes; runtime config selects a bundle but does not copy policy content. Routing, scoring, graph retrieval, generation, API debug DTOs, query tracing, and eval reporting consume the same `PolicySnapshot`.

**Tech Stack:** Python 3.11, dataclasses, stdlib JSON/pathlib/hashlib, Pydantic configuration models, FastAPI/Pydantic response schemas, unittest/pytest.

---

## File Structure

Create:

- `rag_modules/query_policy/models.py`: typed policy dataclasses and `PolicyLoadError`.
- `rag_modules/query_policy/resources/c9-default-v1/manifest.json`: bundle metadata and resource references.
- `rag_modules/query_policy/resources/c9-default-v1/policy.json`: lexicon, relation, scoring, routing, graph, generation, and runtime default policy.
- `rag_modules/query_policy/resources/c9-default-v1/prompts/query_planner.txt`: query planner prompt template.
- `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_plan.txt`: answer planning prompt template.
- `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_compose.txt`: answer composition prompt template.
- `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_direct.txt`: direct answer prompt template.
- `rag_modules/runtime/policy_models.py`: `PolicySnapshot` runtime DTO.

Modify:

- `rag_modules/query_policy/loader.py`: replace JSON-shaped loader with bundle loader and hash computation.
- `rag_modules/query_policy/__init__.py`: export typed bundle APIs and remove legacy `QueryPolicy` export.
- `rag_modules/configuration/model_sections/query_understanding.py`: add policy selector model.
- `rag_modules/configuration/env_specs/query_understanding.py`: add policy selector env mappings.
- `rag_modules/configuration/models.py`: include policy selector in domain config serialization.
- `rag_modules/contracts/query_settings.py`: load runtime defaults from `QueryPolicyBundle.runtime_defaults`.
- `rag_modules/query_understanding/registry.py`: consume `bundle.lexicon` and `bundle.relations`.
- `rag_modules/query_understanding/features.py`: replace direct `POLICY.term_group` and regex access with typed policy access.
- `rag_modules/query_understanding/scoring.py`: consume `ScoringPolicy` formula values.
- `rag_modules/query_understanding/graph_intent.py`: consume `GraphPolicy` depth/node profiles and fallback settings.
- `rag_modules/query_understanding/planning/prompting.py`: use `bundle.prompts.query_planner`.
- `rag_modules/query_understanding/planning/calibration.py`: consume `RoutingPolicy`.
- `rag_modules/query_understanding/planning/rule_based.py`: use typed routing fallback settings.
- `rag_modules/generation/models.py`: add policy metadata to `RenderedPrompt`, `GenerationTrace`, and related settings where needed.
- `rag_modules/generation/prompt_builder.py`: render resource prompt templates.
- `rag_modules/generation/planner.py`: consume `GenerationPolicy` for rule plans.
- `rag_modules/generation/decision.py`: consume policy-driven generation decision rules.
- `rag_modules/generation/module_builder.py`: pass the selected policy bundle to prompt builder, planner, and engine.
- `rag_modules/generation/execution/tracing.py`: attach policy metadata to generation snapshots.
- `rag_modules/generation/execution/direct.py`: preserve rendered prompt metadata.
- `rag_modules/generation/execution/two_stage.py`: preserve rendered prompt metadata.
- `rag_modules/graph/query_resolution.py`: render graph sub-questions from `GraphPolicy`.
- `rag_modules/graph/retrieval_runtime.py`: attach policy metadata to graph snapshots.
- `rag_modules/runtime/__init__.py`: export `PolicySnapshot`.
- `rag_modules/runtime/route_models.py`: add `policy` to `RouteSnapshot`.
- `rag_modules/runtime/graph_models.py`: add `policy` to `GraphRetrievalSnapshot`.
- `rag_modules/runtime/generation_models.py`: add `policy` to `GenerationSnapshot`.
- `rag_modules/runtime/trace_models.py`: add `policy` to `QueryTraceEvent`.
- `rag_modules/runtime/snapshot_utils.py`: clone snapshots with policy metadata.
- `rag_modules/routing/trace_recorder.py`: attach policy metadata to route snapshots and plan-stage details.
- `rag_modules/observability/tracing_event_builder.py`: build top-level query trace policy metadata.
- `rag_modules/trace_privacy.py`: ensure policy metadata is preserved by sanitization.
- `rag_modules/interfaces/api/answer_models.py`: expose policy metadata in debug trace schemas.
- `rag_modules/app/services/answer_models.py`: serialize traces with policy metadata through existing DTOs.
- `scripts/eval_queries.py`: include policy metadata in report, result, and summary.
- `tests/test_query_policy.py`: loader and bundle contract tests.
- `tests/test_query_understanding_config.py`: policy selector config tests.
- `tests/test_query_semantics.py`: policy-driven scoring/routing tests.
- `tests/test_generation_prompt_contract.py`: prompt metadata and resource rendering tests.
- `tests/test_generation_executor.py`: generation decision and trace policy tests.
- `tests/test_graph_retrieval_executor.py`: graph policy metadata and sub-question tests.
- `tests/test_query_tracer.py`: query trace policy tests.
- `tests/test_eval_queries.py`: eval report policy tests.
- `tests/test_answer_response_mapping.py`: response DTO policy serialization tests.
- `tests/test_api_app.py`: debug schema policy metadata tests.
- `tests/test_public_surface_boundaries.py`: ensure old policy files and legacy loader patterns are gone.
- `tests/test_public_api_manifest.py`: update public manifest expectations if exported names change.
- `tests/fixtures/generation_prompt_snapshots/*.txt`: update once after resource-rendered prompts are stable.

Delete after the new bundle is active:

- `rag_modules/query_policy/defaults.json`
- `rag_modules/query_policy/planner_prompt.txt`

---

### Task 1: Add Policy Bundle Loader Contract

**Files:**
- Create: `rag_modules/query_policy/models.py`
- Create: `rag_modules/query_policy/resources/c9-default-v1/manifest.json`
- Create: `rag_modules/query_policy/resources/c9-default-v1/policy.json`
- Create: `rag_modules/query_policy/resources/c9-default-v1/prompts/query_planner.txt`
- Create: `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_plan.txt`
- Create: `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_compose.txt`
- Create: `rag_modules/query_policy/resources/c9-default-v1/prompts/answer_direct.txt`
- Modify: `rag_modules/query_policy/loader.py`
- Modify: `rag_modules/query_policy/__init__.py`
- Test: `tests/test_query_policy.py`

- [ ] **Step 1: Write failing policy loader tests**

Add these tests to `tests/test_query_policy.py`:

```python
def test_policy_bundle_exposes_versions_and_hashes(self) -> None:
    from rag_modules.query_policy import get_query_policy

    bundle = get_query_policy()

    self.assertEqual(bundle.metadata.schema_version, "policy-bundle-v1")
    self.assertEqual(bundle.metadata.policy_version, "c9-default-policy-v1")
    self.assertEqual(bundle.metadata.prompt_version, "c9-default-prompts-v1")
    self.assertTrue(bundle.metadata.policy_hash.startswith("sha256:"))
    self.assertTrue(bundle.metadata.prompt_hash.startswith("sha256:"))
    self.assertEqual(bundle.metadata.bundle_name, "c9-default-v1")
    self.assertIn("relation_markers", bundle.lexicon.term_sets)
    self.assertIn("CONTRIBUTES_TO", bundle.relations.graph_relation_types)


def test_policy_loader_rejects_unversioned_schema(self) -> None:
    import json
    import tempfile
    from pathlib import Path

    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        (root / "manifest.json").write_text(
            json.dumps({"policy": "policy.json"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "policy.json").write_text(
            json.dumps({"term_sets": {"relation_markers": ["relation"]}}, ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PolicyLoadError, "schema_version"):
            load_policy_bundle(root)


def test_policy_loader_rejects_missing_prompt_variable(self) -> None:
    import json
    import tempfile
    from pathlib import Path

    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        prompts = root / "prompts"
        prompts.mkdir()
        (prompts / "query_planner.txt").write_text("query={query}", encoding="utf-8")
        (prompts / "answer_plan.txt").write_text("question={question}", encoding="utf-8")
        (prompts / "answer_compose.txt").write_text("question={question}", encoding="utf-8")
        (prompts / "answer_direct.txt").write_text("question={question}", encoding="utf-8")
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "policy-bundle-v1",
                    "policy_version": "test-policy",
                    "prompt_version": "test-prompts",
                    "name": "test",
                    "policy_path": "policy.json",
                    "prompts": {
                        "query_planner": "prompts/query_planner.txt",
                        "answer_plan": "prompts/answer_plan.txt",
                        "answer_compose": "prompts/answer_compose.txt",
                        "answer_direct": "prompts/answer_direct.txt",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (root / "policy.json").write_text(
            json.dumps(_minimal_policy_payload(), ensure_ascii=False),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(PolicyLoadError, "relation_types_text"):
            load_policy_bundle(root)
```

Add `_minimal_policy_payload()` in the same test file:

```python
def _minimal_policy_payload() -> dict:
    return {
        "lexicon": {"term_sets": {}, "regex_rules": {}},
        "relations": {
            "graph_routing_strategies": ["hybrid_traditional", "graph_rag", "combined"],
            "graph_query_types": ["entity_relation", "multi_hop"],
            "graph_relation_types": ["CONTRIBUTES_TO", "REQUIRES"],
            "preferred_relation_excluded_types": ["REQUIRES"],
            "semantic_relation_hints": {},
            "relation_index_keywords": {},
            "relation_index_suffix_templates": {"REQUIRES": "{source_entity}_ingredient"},
            "relation_query_markers": {},
            "entity_linker": {
                "preferred_labels": ["Recipe"],
                "query_type_priorities": {"entity_relation": ["Recipe"]},
                "relation_priorities": {"CONTRIBUTES_TO": ["Recipe"]},
            },
        },
        "scoring": {
            "structural_relationship_factor": 0.5,
            "length_norm_chars": 140,
            "weights": {
                "relation_hit": 0.14,
                "constraint_hit": 0.1,
                "structural_hit": 0.12,
                "length": 0.28,
            },
            "boosts": {
                "intensity_base": 0.45,
                "intensity_step": 0.12,
                "complexity_base": 0.55,
                "complexity_step": 0.08,
            },
        },
        "routing": {
            "graph_first_query_types": ["path_finding", "subgraph", "clustering"],
            "multi_hop_graph_first_relation_hits": 2,
            "meaningful_constraint_fields": ["include_terms", "exclude_terms"],
            "validation_labels": {
                "strategy": "calibrated_strategy",
                "graph_query_type": "calibrated_graph_query_type",
                "source_entities": "calibrated_source_entities",
            },
        },
        "graph": {
            "max_depth": {"entity_relation": 1, "default": 2},
            "max_nodes": {"entity_relation": 20, "default": 50},
            "reasoning": {
                "causal_relation_types": ["CONTRIBUTES_TO"],
                "compositional_relation_types": [],
                "comparison_markers": ["compare"],
                "semantic_relation_key_specs": {
                    "CONTRIBUTES_TO": {
                        "target_field": "effect",
                        "key_fields": ["effect", "causes"],
                    }
                },
            },
            "sub_questions": [
                {"id": "fallback", "when": {"fallback": True}, "template": "Retrieve relevant graph evidence."}
            ],
        },
        "generation": {
            "answer_types": {"direct_answer": {"markers": []}},
            "relation_explanation_markers": ["relationship"],
            "rule_plan": {
                "default_outline": ["Answer directly."],
                "fallback_outline": ["Answer directly."],
                "graph_caution": "Keep graph conclusions bounded.",
                "missing_relation_evidence": "Graph evidence is missing.",
                "sparse_evidence": "Evidence is sparse.",
                "missing_information_caution": "State missing evidence.",
            },
            "decision": {
                "high_pressure_margin": 0.12,
                "reasons": {
                    "two_stage_disabled": "two_stage_disabled",
                    "no_route_analysis": "no_route_analysis",
                    "graph_without_analysis": "graph_evidence_present_without_route_analysis",
                    "graph_rag": "graph_rag_strategy",
                    "combined_pressure": "combined_strategy_with_reasoning_pressure",
                    "high_pressure": "high_complexity_or_dense_relations",
                    "simple": "simple_or_medium_question",
                },
            },
        },
        "runtime_defaults": {"planner": {}, "semantics": {}, "candidates": {}, "candidate_sources": {}, "postprocess": {}},
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_policy.py -q
```

Expected: FAIL because `load_policy_bundle`, `PolicyLoadError`, and typed bundle fields do not exist.

- [ ] **Step 3: Implement typed policy models**

Create `rag_modules/query_policy/models.py`:

```python
"""Typed policy bundle contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PolicyLoadError(RuntimeError):
    def __init__(self, message: str, *, bundle_path: str = "", field_path: str = "") -> None:
        parts = [message]
        if field_path:
            parts.append(f"field={field_path}")
        if bundle_path:
            parts.append(f"bundle={bundle_path}")
        super().__init__("; ".join(parts))
        self.bundle_path = bundle_path
        self.field_path = field_path


@dataclass(frozen=True)
class PolicyMetadata:
    schema_version: str
    policy_version: str
    prompt_version: str
    policy_hash: str
    prompt_hash: str
    bundle_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "policy_hash": self.policy_hash,
            "prompt_hash": self.prompt_hash,
            "bundle_name": self.bundle_name,
        }


@dataclass(frozen=True)
class PromptTemplates:
    query_planner: str
    answer_plan: str
    answer_compose: str
    answer_direct: str


@dataclass(frozen=True)
class LexiconPolicy:
    term_sets: dict[str, tuple[str, ...]]
    regex_rules: dict[str, tuple[str, ...]]

    def term_group(self, name: str) -> tuple[str, ...]:
        return tuple(self.term_sets.get(str(name), ()))

    def regex_group(self, name: str) -> tuple[str, ...]:
        return tuple(self.regex_rules.get(str(name), ()))


@dataclass(frozen=True)
class RelationPolicy:
    graph_routing_strategies: tuple[str, ...]
    graph_query_types: tuple[str, ...]
    graph_relation_types: tuple[str, ...]
    preferred_relation_excluded_types: tuple[str, ...]
    semantic_relation_hints: dict[str, str]
    relation_index_keywords: dict[str, tuple[str, ...]]
    relation_index_suffix_templates: dict[str, str]
    relation_query_markers: dict[str, tuple[str, ...]]
    entity_linker_preferred_labels: tuple[str, ...]
    entity_linker_query_type_priorities: dict[str, tuple[str, ...]]
    entity_linker_relation_priorities: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class ScoringPolicy:
    structural_relationship_factor: float
    length_norm_chars: int
    weights: dict[str, float]
    boosts: dict[str, float]


@dataclass(frozen=True)
class RoutingPolicy:
    graph_first_query_types: tuple[str, ...]
    multi_hop_graph_first_relation_hits: int
    meaningful_constraint_fields: tuple[str, ...]
    validation_labels: dict[str, str]


@dataclass(frozen=True)
class SemanticRelationKeySpec:
    target_field: str
    key_fields: tuple[str, ...]


@dataclass(frozen=True)
class GraphReasoningPolicy:
    causal_relation_types: tuple[str, ...]
    compositional_relation_types: tuple[str, ...]
    comparison_markers: tuple[str, ...]
    semantic_relation_key_specs: dict[str, SemanticRelationKeySpec]


@dataclass(frozen=True)
class GraphPolicy:
    max_depth: dict[str, int]
    max_nodes: dict[str, int]
    sub_questions: tuple[dict[str, Any], ...]
    reasoning: GraphReasoningPolicy


@dataclass(frozen=True)
class GenerationPolicy:
    answer_types: dict[str, dict[str, Any]]
    relation_explanation_markers: tuple[str, ...]
    rule_plan: dict[str, Any]
    decision: dict[str, Any]


@dataclass(frozen=True)
class QueryPolicyBundle:
    metadata: PolicyMetadata
    lexicon: LexiconPolicy
    relations: RelationPolicy
    scoring: ScoringPolicy
    routing: RoutingPolicy
    graph: GraphPolicy
    generation: GenerationPolicy
    runtime_defaults: dict[str, dict[str, Any]]
    prompts: PromptTemplates

    def runtime_section(self, name: str) -> dict[str, Any]:
        return dict(self.runtime_defaults.get(str(name), {}))
```

- [ ] **Step 4: Implement loader and default resources**

Replace `rag_modules/query_policy/loader.py` with a bundle loader. Keep helpers small:

```python
SUPPORTED_SCHEMA_VERSION = "policy-bundle-v1"
DEFAULT_BUNDLE_NAME = "c9-default-v1"

def default_policy_bundle_path() -> Path:
    return Path(__file__).parent / "resources" / DEFAULT_BUNDLE_NAME

@lru_cache(maxsize=8)
def load_policy_bundle(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    root = Path(bundle_path or default_policy_bundle_path()).resolve()
    manifest = _read_json(root / "manifest.json", root)
    _require_equal(manifest, "schema_version", SUPPORTED_SCHEMA_VERSION, root)
    policy = _read_json(root / str(manifest["policy_path"]), root)
    prompts = _load_prompts(root, dict(manifest["prompts"]))
    _verify_prompt_variables(prompts, root)
    bundle = _build_bundle(root, manifest, policy, prompts)
    _validate_references(bundle, root)
    return bundle


def get_query_policy(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    return load_policy_bundle(bundle_path)
```

Implementation details:

- `_read_json(path, root)` opens UTF-8 JSON and raises `PolicyLoadError` with `bundle_path=str(root)`.
- `_hash_payload(payload)` serializes with `json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
- `_hash_texts(texts)` hashes prompt names and contents in sorted prompt-name order.
- `_to_tuple(value)` and `_to_tuple_map(value)` keep the current cleaning behavior.
- `_build_bundle()` maps `policy["lexicon"]`, `policy["relations"]`, `policy["scoring"]`, `policy["routing"]`, `policy["graph"]`, `policy["generation"]`, and `policy["runtime_defaults"]`.
- `_verify_prompt_variables()` requires:
  - query planner: `{query}`, `{graph_query_types_text}`, `{relation_types_text}`, `{preferred_relation_types_text}`
  - answer plan: `{question}`, `{evidence_summary}`
  - answer compose: `{question}`, `{plan_json}`, `{evidence_text}`
  - answer direct: `{question}`, `{evidence_text}`

Create the resource files:

- Move current `defaults.json` content into `policy.json` under the new top-level keys.
- Move current `planner_prompt.txt` content into `prompts/query_planner.txt`.
- Move the three prompt bodies from `GenerationPromptBuilder` into `answer_plan.txt`, `answer_compose.txt`, and `answer_direct.txt`.
- Move generation rule-plan strings and graph sub-question strings into `policy.json`.

Update `rag_modules/query_policy/__init__.py`:

```python
"""Versioned policy bundle access."""

from .loader import default_policy_bundle_path, get_query_policy, load_policy_bundle
from .models import PolicyLoadError, PolicyMetadata, PromptTemplates, QueryPolicyBundle

__all__ = [
    "PolicyLoadError",
    "PolicyMetadata",
    "PromptTemplates",
    "QueryPolicyBundle",
    "default_policy_bundle_path",
    "get_query_policy",
    "load_policy_bundle",
]
```

- [ ] **Step 5: Run tests to verify green**

Run:

```powershell
python -m pytest tests/test_query_policy.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/query_policy tests/test_query_policy.py
git commit -m "feat: add versioned query policy bundle"
```

---

### Task 2: Add Policy Selector To Configuration

**Files:**
- Modify: `rag_modules/configuration/model_sections/query_understanding.py`
- Modify: `rag_modules/configuration/env_specs/query_understanding.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/contracts/query_settings.py`
- Test: `tests/test_query_understanding_config.py`

- [ ] **Step 1: Write failing selector tests**

Add to `tests/test_query_understanding_config.py`:

```python
def test_query_understanding_policy_selector_is_nested(self) -> None:
    config = load_config()

    payload = config.to_domain_dict()["query_understanding"]

    self.assertIn("policy", payload)
    self.assertEqual(payload["policy"]["bundle"], "c9-default-v1")
    self.assertEqual(config.query_understanding.policy.bundle, "c9-default-v1")
    self.assertEqual(config.query_understanding.policy.bundle_path, "")


def test_query_understanding_policy_selector_accepts_env_override(self) -> None:
    config = load_config(
        source=EnvConfigSource(environ={"QUERY_POLICY_BUNDLE": "c9-default-v1"})
    )

    self.assertEqual(config.query_understanding.policy.bundle, "c9-default-v1")


def test_query_understanding_policy_selector_rejects_flat_override(self) -> None:
    config = load_config()

    with self.assertRaises(ConfigurationError) as context:
        config.with_overrides({"query_policy_bundle": "c9-default-v1"})

    self.assertIn("query_policy_bundle", str(context.exception))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_understanding_config.py -q
```

Expected: FAIL because `query_understanding.policy` does not exist.

- [ ] **Step 3: Implement selector model**

In `rag_modules/configuration/model_sections/query_understanding.py`, add:

```python
class QueryPolicySelectorSettings(ConfigSection):
    bundle: str = "c9-default-v1"
    bundle_path: str = ""
```

Add to `QueryUnderstandingSettings`:

```python
policy: QueryPolicySelectorSettings = Field(default_factory=QueryPolicySelectorSettings)
```

Add `QueryPolicySelectorSettings` to `__all__` and `rag_modules/configuration/model_sections/__init__.py`.

- [ ] **Step 4: Add env specs**

Append to `QUERY_UNDERSTANDING_ENV_FIELD_SPECS`:

```python
_spec(
    "QUERY_POLICY_BUNDLE",
    ("query_understanding", "policy", "bundle"),
    "str",
),
_spec(
    "QUERY_POLICY_BUNDLE_PATH",
    ("query_understanding", "policy", "bundle_path"),
    "str",
),
```

- [ ] **Step 5: Update runtime settings default access**

In `rag_modules/contracts/query_settings.py`, replace module defaults with bundle defaults:

```python
_POLICY_BUNDLE = get_query_policy()
_PLANNER_DEFAULTS = _POLICY_BUNDLE.runtime_section("planner")
_SEMANTIC_DEFAULTS = _POLICY_BUNDLE.runtime_section("semantics")
```

Keep the existing config override behavior. Policy selector wiring into providers is completed in
Task 7 and Task 8 when generation services receive the selected policy bundle.

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_query_understanding_config.py tests/test_configuration_defaults.py tests/test_configuration_profiles.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/configuration rag_modules/contracts/query_settings.py tests/test_query_understanding_config.py
git commit -m "feat: add query policy selector configuration"
```

---

### Task 3: Migrate Lexicon And Registry Consumers

**Files:**
- Modify: `rag_modules/query_understanding/registry.py`
- Modify: `rag_modules/query_understanding/features.py`
- Modify: `rag_modules/query_understanding/planning/prompting.py`
- Test: `tests/test_query_policy.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: Write failing registry tests**

Add to `tests/test_query_policy.py`:

```python
def test_registry_reads_terms_from_typed_policy_bundle(self) -> None:
    from rag_modules.query_understanding.registry import POLICY, RELATION_MARKERS

    self.assertEqual(POLICY.metadata.policy_version, "c9-default-policy-v1")
    self.assertIn("关系", "".join(RELATION_MARKERS))
```

Use an existing clean UTF-8 term present in the migrated resource. If the current corpus text remains mojibake, use one exact existing relation marker string from the resource and assert that the registry value matches it.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py -q
```

Expected: FAIL because registry still expects the old `QueryPolicy.term_group` interface.

- [ ] **Step 3: Update registry**

In `rag_modules/query_understanding/registry.py`, replace old access:

```python
POLICY = get_query_policy()
GRAPH_ROUTING_STRATEGIES = POLICY.relations.graph_routing_strategies
GRAPH_QUERY_TYPES = POLICY.relations.graph_query_types
GRAPH_RELATION_TYPES = tuple(
    dict.fromkeys([*POLICY.relations.graph_relation_types, *SEMANTIC_RELATION_TYPES])
)
FLAVOR_TERMS = POLICY.lexicon.term_group("flavor_terms")
```

Apply the same `POLICY.lexicon.term_group(...)` pattern for all term sets, `POLICY.lexicon.regex_group(...)` for regex rules, and `POLICY.relations.*` for relation mappings.

- [ ] **Step 4: Update features**

In `rag_modules/query_understanding/features.py`, replace direct calls:

```python
POLICY.regex_group("time_minutes_patterns")
POLICY.lexicon.regex_group("time_minutes_patterns")
```

and:

```python
POLICY.term_group("clustering_markers")
POLICY.lexicon.term_group("clustering_markers")
```

- [ ] **Step 5: Update query planner prompt rendering**

In `rag_modules/query_understanding/planning/prompting.py`, replace:

```python
from ...query_policy import get_planner_prompt_template
```

with:

```python
from ...query_policy import get_query_policy
```

and render:

```python
return get_query_policy().prompts.query_planner.format(
    graph_query_types_text=graph_query_types_text,
    relation_types_text=relation_types_text,
    preferred_relation_types_text=preferred_relation_types_text,
    query=query,
)
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/query_understanding tests/test_query_policy.py tests/test_query_semantics.py
git commit -m "refactor: consume typed policy lexicon"
```

---

### Task 4: Migrate Scoring And Routing Rules

**Files:**
- Modify: `rag_modules/query_understanding/scoring.py`
- Modify: `rag_modules/query_understanding/graph_intent.py`
- Modify: `rag_modules/query_understanding/planning/calibration.py`
- Modify: `rag_modules/query_understanding/planning/rule_based.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: Write failing scoring and routing tests**

Add to `tests/test_query_semantics.py`:

```python
def test_scoring_uses_policy_structural_relationship_factor(self) -> None:
    from rag_modules.query_policy import get_query_policy
    from rag_modules.query_understanding.scoring import build_query_semantic_score_breakdown

    policy = get_query_policy()
    settings = QuerySemanticRuntimeSettings(relation_intensity_reference_ratio=1.0)

    score = build_query_semantic_score_breakdown(
        "relationship",
        settings=settings,
        relation_hits=[],
        structural_hits=["relationship"],
    )

    expected = min(
        1.0,
        policy.scoring.structural_relationship_factor
        / max(1.0, len(policy.lexicon.term_group("relation_markers"))),
    )
    self.assertEqual(score.lexical_relationship_intensity, expected)


def test_calibrator_uses_policy_validation_labels(self) -> None:
    from rag_modules.query_policy import get_query_policy

    plan = QueryPlan.from_dict(
        "relationship path question",
        {"strategy": "hybrid_traditional", "graph_query_type": "entity_relation"},
    )
    self.planner.calibrator.calibrate(plan)

    label = get_query_policy().routing.validation_labels["strategy"]
    self.assertTrue(any(item.startswith(label + ":") for item in plan.validation_errors))
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_semantics.py -q
```

Expected: FAIL because scoring still hardcodes the structural factor and calibrator still hardcodes labels.

- [ ] **Step 3: Update scoring**

In `rag_modules/query_understanding/scoring.py`, import the policy:

```python
from ..query_policy import get_query_policy
```

Inside `build_query_semantic_score_breakdown`, add:

```python
policy = get_query_policy().scoring
```

Replace:

```python
(relation_hit_count + structural_hit_count * 0.5) / reference_hits
```

with:

```python
(relation_hit_count + structural_hit_count * policy.structural_relationship_factor) / reference_hits
```

Keep runtime override weights in `QuerySemanticRuntimeSettings`, because profiles still own deployment knobs.

- [ ] **Step 4: Update graph intent profiles**

In `rag_modules/query_understanding/graph_intent.py`, load:

```python
graph_policy = get_query_policy().graph
```

Replace query-type string decision sets with policy-backed sets. For max depth and max nodes, resolve from `graph_policy.max_depth` and `graph_policy.max_nodes`, falling back only to validated policy keys:

```python
return int(graph_policy.max_depth.get(query_type, graph_policy.max_depth["default"]))
```

Keep profile overrides in `QuerySemanticRuntimeSettings` where the existing config model exposes them.

- [ ] **Step 5: Update calibration labels and rule sets**

In `rag_modules/query_understanding/planning/calibration.py`, add:

```python
from ...query_policy import get_query_policy
```

Store policy in `__init__`:

```python
self.policy = get_query_policy().routing
```

Replace hardcoded validation prefixes:

```python
self.policy.validation_labels["strategy"]
self.policy.validation_labels["graph_query_type"]
self.policy.validation_labels["source_entities"]
```

Replace graph-first query type sets with `set(self.policy.graph_first_query_types)`.

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_query_semantics.py tests/test_query_policy.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/query_understanding tests/test_query_semantics.py tests/test_query_policy.py
git commit -m "refactor: drive query scoring and routing from policy"
```

---

### Task 5: Add PolicySnapshot Runtime DTO And Trace Fields

**Files:**
- Create: `rag_modules/runtime/policy_models.py`
- Modify: `rag_modules/runtime/__init__.py`
- Modify: `rag_modules/runtime/route_models.py`
- Modify: `rag_modules/runtime/graph_models.py`
- Modify: `rag_modules/runtime/generation_models.py`
- Modify: `rag_modules/runtime/trace_models.py`
- Modify: `rag_modules/runtime/snapshot_utils.py`
- Test: `tests/test_query_tracer.py`
- Test: `tests/test_answer_response_mapping.py`

- [ ] **Step 1: Write failing snapshot tests**

Add to `tests/test_query_tracer.py`:

```python
def _policy_payload() -> dict:
    return {
        "schema_version": "policy-bundle-v1",
        "policy_version": "c9-default-policy-v1",
        "prompt_version": "c9-default-prompts-v1",
        "policy_hash": "sha256:policy",
        "prompt_hash": "sha256:prompt",
        "bundle_name": "c9-default-v1",
    }


def test_trace_snapshots_serialize_policy_metadata(self) -> None:
    from rag_modules.runtime import PolicySnapshot

    policy = PolicySnapshot.from_dict(_policy_payload())

    self.assertEqual(RouteSnapshot(policy=policy).to_dict()["policy"], _policy_payload())
    self.assertEqual(GraphRetrievalSnapshot(policy=policy).to_dict()["policy"], _policy_payload())
    self.assertEqual(GenerationSnapshot(policy=policy).to_dict()["policy"], _policy_payload())
    self.assertEqual(QueryTraceEvent(policy=policy).to_dict()["policy"], _policy_payload())
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_tracer.py tests/test_answer_response_mapping.py -q
```

Expected: FAIL because `PolicySnapshot` and `policy` fields do not exist.

- [ ] **Step 3: Implement PolicySnapshot**

Create `rag_modules/runtime/policy_models.py`:

```python
"""Policy metadata snapshots for traces and reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .json_types import JsonObject


@dataclass
class PolicySnapshot:
    schema_version: str = ""
    policy_version: str = ""
    prompt_version: str = ""
    policy_hash: str = ""
    prompt_hash: str = ""
    bundle_name: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "PolicySnapshot":
        payload = dict(data or {})
        return cls(
            schema_version=str(payload.get("schema_version") or ""),
            policy_version=str(payload.get("policy_version") or ""),
            prompt_version=str(payload.get("prompt_version") or ""),
            policy_hash=str(payload.get("policy_hash") or ""),
            prompt_hash=str(payload.get("prompt_hash") or ""),
            bundle_name=str(payload.get("bundle_name") or ""),
        )

    @classmethod
    def from_metadata(cls, metadata) -> "PolicySnapshot":
        return cls.from_dict(metadata.to_dict() if hasattr(metadata, "to_dict") else {})

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "policy_hash": self.policy_hash,
            "prompt_hash": self.prompt_hash,
            "bundle_name": self.bundle_name,
        }

    def is_recorded(self) -> bool:
        return bool(self.policy_version and self.prompt_version and self.policy_hash)
```

Export it from `rag_modules/runtime/__init__.py`.

- [ ] **Step 4: Add policy fields to snapshots**

In `RouteSnapshot`, `GraphRetrievalSnapshot`, `GenerationSnapshot`, and `QueryTraceEvent`:

```python
policy: PolicySnapshot = field(default_factory=PolicySnapshot)
```

In each `__post_init__`:

```python
if isinstance(self.policy, dict):
    self.policy = PolicySnapshot.from_dict(self.policy)
elif not isinstance(self.policy, PolicySnapshot):
    self.policy = PolicySnapshot()
```

In each `from_dict()`:

```python
policy=PolicySnapshot.from_dict(_mapping_or_none(payload.get("policy"))),
```

In each `to_dict()`:

```python
"policy": self.policy.to_dict(),
```

Update `GenerationSnapshot.is_recorded()` to include `self.policy.is_recorded()`.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_query_tracer.py tests/test_answer_response_mapping.py -q
```

Expected: PASS after response tests are adjusted to include explicit policy metadata where required.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/runtime tests/test_query_tracer.py tests/test_answer_response_mapping.py
git commit -m "feat: add policy metadata to runtime traces"
```

---

### Task 6: Attach Policy Metadata In Routing And Graph Retrieval

**Files:**
- Modify: `rag_modules/routing/trace_recorder.py`
- Modify: `rag_modules/graph/query_resolution.py`
- Modify: `rag_modules/graph/retrieval_runtime.py`
- Test: `tests/test_graph_retrieval_executor.py`
- Test: `tests/test_query_tracer.py`

- [ ] **Step 1: Write failing graph policy tests**

Add to `tests/test_graph_retrieval_executor.py`:

```python
def test_graph_runtime_records_policy_metadata_and_policy_sub_questions(self) -> None:
    from rag_modules.graph.query_resolution import GraphQueryFactory
    from rag_modules.graph.retrieval_runtime import GraphRetrievalRuntime

    runtime = GraphRetrievalRuntime(GraphQueryFactory())
    request = RetrievalRequest.from_inputs(
        query="why does sauce affect texture",
        top_k=2,
        strategy="graph_rag",
    )

    graph_query, goals = runtime.resolve_request_context(request)
    trace = runtime.start_trace(request.query, requested_top_k=2, retrieval_request=request)
    runtime.populate_trace_context(trace, graph_query=graph_query, evidence_goals=goals)

    self.assertTrue(trace.policy.is_recorded())
    self.assertTrue(trace.sub_questions)
    self.assertIn(trace.policy.policy_version, trace.to_dict()["policy"]["policy_version"])
```

Add to `tests/test_query_tracer.py`:

```python
def test_route_trace_policy_is_preserved_in_query_trace(self) -> None:
    tracer = QueryTracer(self._build_config(), sink=_CapturingSink())
    policy = PolicySnapshot.from_dict(_policy_payload())

    event = tracer.record(
        query="policy route",
        analysis=None,
        documents=[EvidenceDocument(content="evidence")],
        latency_ms=1.0,
        route_trace=RouteSnapshot(query="policy route", policy=policy),
        generation_trace=GenerationSnapshot(status="success", mode="direct", policy=policy),
    )

    self.assertEqual(event.policy.policy_version, policy.policy_version)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_graph_retrieval_executor.py tests/test_query_tracer.py -q
```

Expected: FAIL because graph/runtime and tracer do not attach policy metadata.

- [ ] **Step 3: Update RouteTraceRecorder**

In `rag_modules/routing/trace_recorder.py`, import:

```python
from ..query_policy import get_query_policy
from ..runtime import PolicySnapshot
```

Set policy in `__init__`:

```python
self.policy = PolicySnapshot.from_metadata(get_query_policy().metadata)
self.snapshot = RouteSnapshot(query=query, requested_top_k=requested_top_k, policy=self.policy)
```

Add to `record_plan()` details:

```python
"policy": self.policy.to_dict(),
```

- [ ] **Step 4: Update graph sub-question rendering**

In `rag_modules/graph/query_resolution.py`, load `graph_policy = get_query_policy().graph`.

Replace inline `sub_questions.append(...)` blocks with ordered policy rules:

```python
for rule in graph_policy.sub_questions:
    if _sub_question_rule_matches(rule, query, graph_query, profile, entities, relation_types):
        sub_questions.append(_render_sub_question(rule["template"], entities=entities, query=query))
    if len(sub_questions) >= int(rule.get("max_total", 6)):
        break
```

Implement `_sub_question_rule_matches()` in the same module. It must support these condition keys:

- `entities_present`
- `relation_types_any`
- `constraints_present`
- `relationship_intensity_at_least`
- `query_markers_any`
- `fallback`

Implement `_render_sub_question()` with `str.format()` variables:

```python
{
    "query": query,
    "entities": ", ".join(entities[:4]),
    "relation_types": ", ".join(relation_types),
}
```

- [ ] **Step 5: Update GraphRetrievalRuntime**

In `rag_modules/graph/retrieval_runtime.py`, attach policy:

```python
from ..query_policy import get_query_policy
from ..runtime import PolicySnapshot

@staticmethod
def _policy_snapshot() -> PolicySnapshot:
    return PolicySnapshot.from_metadata(get_query_policy().metadata)
```

Use it in `start_trace()`:

```python
policy=GraphRetrievalRuntime._policy_snapshot()
```

and ensure `populate_trace_context()` preserves existing `trace.policy`.

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_graph_retrieval_executor.py tests/test_query_tracer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/routing rag_modules/graph tests/test_graph_retrieval_executor.py tests/test_query_tracer.py
git commit -m "feat: attach policy metadata to route and graph traces"
```

---

### Task 7: Migrate Generation Prompts And Rule Planning

**Files:**
- Modify: `rag_modules/generation/models.py`
- Modify: `rag_modules/generation/prompt_builder.py`
- Modify: `rag_modules/generation/planner.py`
- Modify: `rag_modules/generation/module_builder.py`
- Test: `tests/test_generation_prompt_contract.py`
- Test: `tests/test_generation_executor.py`

- [ ] **Step 1: Write failing prompt metadata tests**

Add to `tests/test_generation_prompt_contract.py`:

```python
def test_direct_prompt_render_includes_policy_metadata(self) -> None:
    builder = GenerationPromptBuilder(settings=GenerationSettings(), evidence_max_chars=700)

    rendered = builder.render_direct_answer_prompt_from_context(self._build_context())

    self.assertEqual(rendered.metadata["policy_version"], "c9-default-policy-v1")
    self.assertEqual(rendered.metadata["prompt_version"], "c9-default-prompts-v1")
    self.assertTrue(rendered.metadata["policy_hash"].startswith("sha256:"))
    self.assertIn("Recipe Evidence 1", rendered.text)


def test_rule_plan_uses_policy_missing_information_template(self) -> None:
    planner = GenerationPlanner(
        settings=GenerationSettings(planner_mode="rule"),
        client_adapter=object(),
        prompt_builder=GenerationPromptBuilder(settings=GenerationSettings(), evidence_max_chars=700),
    )

    plan = planner.build_answer_plan_from_context(self._build_context())

    self.assertTrue(plan.outline)
    self.assertIsInstance(plan.missing_information, list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py tests/test_generation_executor.py -q
```

Expected: FAIL because prompt metadata and resource rendering are not implemented.

- [ ] **Step 3: Update RenderedPrompt**

In `rag_modules/generation/models.py`, make `RenderedPrompt.metadata` always include policy metadata when the builder provides it. No default empty version should be added in the model; the builder owns that.

- [ ] **Step 4: Update GenerationPromptBuilder**

In `rag_modules/generation/prompt_builder.py`, add to `__init__`:

```python
from ..query_policy import get_query_policy
from ..runtime import PolicySnapshot

self.policy_bundle = get_query_policy()
self.policy_snapshot = PolicySnapshot.from_metadata(self.policy_bundle.metadata)
self.prompts = self.policy_bundle.prompts
```

Add:

```python
def _policy_metadata(self) -> dict[str, str]:
    return self.policy_snapshot.to_dict()
```

Render prompt text from resources:

```python
return self.prompts.answer_plan.format(
    question=question,
    evidence_summary=evidence_summary,
)
```

```python
return self.prompts.answer_compose.format(
    question=question,
    plan_json=json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
    evidence_text=evidence_text,
)
```

```python
return self.prompts.answer_direct.format(
    question=question,
    evidence_text=evidence_text,
)
```

Merge `self._policy_metadata()` into each `RenderedPrompt.metadata`.

- [ ] **Step 5: Update rule-based planner**

In `rag_modules/generation/planner.py`, load:

```python
self.generation_policy = prompt_builder.policy_bundle.generation
```

Replace inline outline/caution/missing-information strings with:

```python
rule_plan = self.generation_policy.rule_plan
outline = list(rule_plan["default_outline"])
```

Replace `infer_answer_type()` and `question_needs_relation_explanation()` usage with policy methods on `GenerationPromptBuilder`:

```python
def infer_answer_type(self, question: str) -> str:
    for answer_type, rule in self.policy_bundle.generation.answer_types.items():
        if any(marker in question for marker in rule.get("markers", [])):
            return answer_type
    return "direct_answer"
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_generation_prompt_contract.py tests/test_generation_executor.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/generation tests/test_generation_prompt_contract.py tests/test_generation_executor.py
git commit -m "refactor: render generation prompts from policy resources"
```

---

### Task 8: Migrate Generation Decision Policy And Trace Metadata

**Files:**
- Modify: `rag_modules/generation/decision.py`
- Modify: `rag_modules/generation/execution/tracing.py`
- Modify: `rag_modules/generation/execution/direct.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Test: `tests/test_generation_executor.py`

- [ ] **Step 1: Write failing decision policy tests**

Add to `tests/test_generation_executor.py`:

```python
def test_generation_decision_uses_policy_reason_strings(self) -> None:
    decision = decide_generation_mode(
        package=self._build_package(),
        settings=GenerationSettings(enable_two_stage=False),
    )

    self.assertEqual(decision.reason, "two_stage_disabled")


def test_generation_trace_records_policy_metadata(self) -> None:
    engine = GenerationExecutionEngine(
        settings=GenerationSettings(enable_two_stage=False),
        client_adapter=_FakeClientAdapter([_FakeResponse("answer")]),
        prompt_builder=GenerationPromptBuilder(settings=GenerationSettings(), evidence_max_chars=700),
        planner=_FakePlanner(),
        empty_evidence_answer="empty",
    )

    _answer, trace = engine.generate_with_trace(
        question="policy trace",
        package=self._build_package(),
    )

    self.assertTrue(trace.policy.is_recorded())
    self.assertEqual(trace.policy.policy_version, "c9-default-policy-v1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_generation_executor.py -q
```

Expected: FAIL because decision still hardcodes margin/reasons and trace does not copy policy metadata.

- [ ] **Step 3: Update generation decision**

In `rag_modules/generation/decision.py`, import `get_query_policy()` and load:

```python
decision_policy = get_query_policy().generation.decision
reasons = dict(decision_policy["reasons"])
margin = float(decision_policy["high_pressure_margin"])
```

Replace all reason literals with `reasons[...]`.

Replace:

```python
settings.two_stage_complexity_threshold + 0.12
```

with:

```python
settings.two_stage_complexity_threshold + margin
```

Apply the same replacement to relationship intensity.

- [ ] **Step 4: Copy prompt policy metadata into traces**

In `rag_modules/generation/execution/tracing.py`, set policy in `_new_trace()`:

```python
policy=getattr(self.prompt_builder, "policy_snapshot", PolicySnapshot())
```

In `_record_empty_trace()`, use the same policy snapshot.

In direct/two-stage execution, keep rendered prompt in a local variable:

```python
rendered = self.prompt_builder.render_direct_answer_prompt_from_context(answer_context)
prompt = rendered.text
```

Use `rendered.metadata` only for trace policy validation; the snapshot policy should come from `prompt_builder.policy_snapshot`.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m pytest tests/test_generation_executor.py tests/test_generation_prompt_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/generation tests/test_generation_executor.py tests/test_generation_prompt_contract.py
git commit -m "feat: drive generation decisions from policy"
```

---

### Task 9: Normalize Query Trace Policy Metadata

**Files:**
- Modify: `rag_modules/observability/tracing_event_builder.py`
- Modify: `rag_modules/trace_privacy.py`
- Test: `tests/test_query_tracer.py`

- [ ] **Step 1: Write failing query trace tests**

Add to `tests/test_query_tracer.py`:

```python
def test_query_trace_event_uses_generation_policy_snapshot(self) -> None:
    tracer = QueryTracer(self._build_config(), sink=_CapturingSink())
    policy = PolicySnapshot.from_dict(_policy_payload())

    event = tracer.record(
        query="policy generation",
        analysis=None,
        documents=[EvidenceDocument(content="evidence")],
        latency_ms=2.0,
        generation_trace=GenerationSnapshot(status="success", mode="direct", policy=policy),
    )

    self.assertEqual(event.policy.to_dict(), policy.to_dict())


def test_query_trace_records_contract_failure_for_missing_policy(self) -> None:
    tracer = QueryTracer(self._build_config(), sink=_CapturingSink())

    event = tracer.record(
        query="missing policy",
        analysis=None,
        documents=[EvidenceDocument(content="evidence")],
        latency_ms=2.0,
        generation_trace=GenerationSnapshot(status="success", mode="direct"),
    )

    self.assertIn("policy_metadata_missing", event.diagnostics.failure_reasons)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_query_tracer.py -q
```

Expected: FAIL because top-level policy selection and contract failure are not implemented.

- [ ] **Step 3: Implement policy selection**

In `rag_modules/observability/tracing_event_builder.py`, add:

```python
def _select_policy_snapshot(
    self,
    route_trace: RouteSnapshot,
    graph_trace: GraphRetrievalSnapshot,
    generation_trace: GenerationSnapshot,
) -> PolicySnapshot:
    candidates = [
        generation_trace.policy,
        route_trace.policy,
        graph_trace.policy,
    ]
    recorded = [candidate for candidate in candidates if candidate.is_recorded()]
    if not recorded:
        return PolicySnapshot()
    first = recorded[0]
    if any(candidate.to_dict() != first.to_dict() for candidate in recorded[1:]):
        return PolicySnapshot()
    return first
```

Pass `policy=policy_snapshot` into `QueryTraceEvent`.

- [ ] **Step 4: Add diagnostics failure reason**

After diagnostics are built, append:

```python
if not policy_snapshot.is_recorded():
    diagnostics.failure_reasons.append("policy_metadata_missing")
```

If multiple recorded snapshots disagree, append `policy_metadata_mismatch`.

- [ ] **Step 5: Preserve policy metadata in sanitization**

In `rag_modules/trace_privacy.py`, ensure the sanitizer does not redact keys:

```python
{"schema_version", "policy_version", "prompt_version", "policy_hash", "prompt_hash", "bundle_name"}
```

- [ ] **Step 6: Run tests**

Run:

```powershell
python -m pytest tests/test_query_tracer.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add rag_modules/observability rag_modules/trace_privacy.py tests/test_query_tracer.py
git commit -m "feat: normalize policy metadata in query traces"
```

---

### Task 10: Expose Policy Metadata In API Debug Schemas

**Files:**
- Modify: `rag_modules/interfaces/api/answer_models.py`
- Test: `tests/test_api_app.py`
- Test: `tests/test_answer_response_mapping.py`

- [ ] **Step 1: Write failing API schema tests**

Add to `tests/test_api_app.py` near existing schema tests:

```python
def test_debug_trace_schemas_expose_policy_metadata(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem())

    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    schemas = schema["components"]["schemas"]
    self.assertIn("PolicySnapshotResponseModel", schemas)
    self.assertIn(
        "policy",
        schemas["GenerationSnapshotResponseModel"]["properties"],
    )
    self.assertIn(
        "policy",
        schemas["QueryTraceEventResponseModel"]["properties"],
    )
```

Add to `tests/test_answer_response_mapping.py`:

```python
def test_answer_response_trace_payload_includes_policy_metadata(self) -> None:
    result = _complete_result()
    policy = PolicySnapshot.from_dict(_policy_payload())
    result.generation_trace.policy = policy
    result.route_trace.policy = policy
    result.graph_trace.policy = policy
    result.trace_event.policy = policy

    payload = result.to_response().to_dict()

    self.assertEqual(
        payload["traces"]["generation_trace"]["policy"]["policy_version"],
        "c9-default-policy-v1",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_answer_response_mapping.py -q
```

Expected: FAIL because response models do not expose policy fields.

- [ ] **Step 3: Add PolicySnapshotResponseModel**

In `rag_modules/interfaces/api/answer_models.py`, add:

```python
class PolicySnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ""
    policy_version: str = ""
    prompt_version: str = ""
    policy_hash: str = ""
    prompt_hash: str = ""
    bundle_name: str = ""

    @classmethod
    def from_dto(cls, snapshot: PolicySnapshot) -> "PolicySnapshotResponseModel":
        return cls(**snapshot.to_dict())
```

Add `policy: PolicySnapshotResponseModel = Field(default_factory=PolicySnapshotResponseModel)` to:

- `RouteSnapshotResponseModel`
- `GraphRetrievalSnapshotResponseModel`
- `GenerationSnapshotResponseModel`
- `QueryTraceEventResponseModel`

Populate each from DTO.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_answer_response_mapping.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add rag_modules/interfaces/api/answer_models.py tests/test_api_app.py tests/test_answer_response_mapping.py
git commit -m "feat: expose policy metadata in debug traces"
```

---

### Task 11: Add Policy Metadata To Eval Reports

**Files:**
- Modify: `scripts/eval_queries.py`
- Test: `tests/test_eval_queries.py`

- [ ] **Step 1: Write failing eval tests**

Add to `tests/test_eval_queries.py`:

```python
def test_eval_report_includes_policy_metadata(self) -> None:
    config = load_config()
    policy = {
        "schema_version": "policy-bundle-v1",
        "policy_version": "c9-default-policy-v1",
        "prompt_version": "c9-default-prompts-v1",
        "policy_hash": "sha256:policy",
        "prompt_hash": "sha256:prompt",
        "bundle_name": "c9-default-v1",
    }

    report = build_eval_report(
        metrics={"case_count": 1},
        results=[{"query": "q", "policy": policy}],
        failures=[],
        config=config,
        corpus_path="tests/fixtures/curated_eval_corpus.json",
        top_k=3,
        generate=True,
    )

    self.assertEqual(report["policy"], policy)
```

Add:

```python
def test_eval_case_fails_when_generated_response_lacks_policy(self) -> None:
    response_payload = {"summary": {}, "traces": {"generation_trace": {}}}
    result = _answer_resilience_signals(response_payload, {})

    self.assertIn("policy_metadata_missing", result["fallback_reasons"])
```

If `_answer_resilience_signals` is not the right location, add a small helper `_response_policy_metadata()` and test that directly.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -q
```

Expected: FAIL because reports do not include `policy`.

- [ ] **Step 3: Implement report metadata extraction**

In `scripts/eval_queries.py`, add:

```python
def _policy_metadata_from_response(
    response_payload: dict[str, Any],
    route_resolution_payload: dict[str, Any],
) -> dict[str, Any]:
    traces = _mapping(response_payload.get("traces"))
    for payload in (
        _mapping(_mapping(traces.get("trace_event")).get("policy")),
        _mapping(_mapping(traces.get("generation_trace")).get("policy")),
        _mapping(_mapping(traces.get("route_trace")).get("policy")),
        _mapping(_mapping(traces.get("graph_trace")).get("policy")),
        _mapping(_mapping(_mapping(route_resolution_payload.get("retrieval")).get("route_trace")).get("policy")),
    ):
        if payload.get("policy_version") and payload.get("policy_hash"):
            return payload
    return {}
```

In `evaluate_case()`, include:

```python
policy = _policy_metadata_from_response(
    contracts["answer_response"],
    contracts["route_resolution"],
)
if not policy:
    failures.append("policy_metadata_missing")
```

Add `"policy": policy` to the returned result.

In `build_eval_report()`, compute a top-level policy:

```python
policy = next((dict(item.get("policy") or {}) for item in results if item.get("policy")), {})
```

Include `"policy": policy`.

In `_write_eval_report()`, add summary lines:

```python
policy = report.get("policy") or {}
f"- policy_version: {policy.get('policy_version', '')}",
f"- prompt_version: {policy.get('prompt_version', '')}",
f"- policy_hash: {policy.get('policy_hash', '')}",
f"- prompt_hash: {policy.get('prompt_hash', '')}",
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add scripts/eval_queries.py tests/test_eval_queries.py
git commit -m "feat: include policy metadata in eval reports"
```

---

### Task 12: Remove Old Policy Files And Legacy Accessors

**Files:**
- Delete: `rag_modules/query_policy/defaults.json`
- Delete: `rag_modules/query_policy/planner_prompt.txt`
- Modify: `rag_modules/query_policy/__init__.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `tests/test_public_api_manifest.py`
- Test: `tests/test_public_surface_boundaries.py`
- Test: `tests/test_public_api_manifest.py`

- [ ] **Step 1: Write failing boundary test**

Add to `tests/test_public_surface_boundaries.py`:

```python
def test_unversioned_query_policy_resources_are_retired(self) -> None:
    policy_dir = RAG_MODULES_DIR / "query_policy"

    self.assertFalse((policy_dir / "defaults.json").exists())
    self.assertFalse((policy_dir / "planner_prompt.txt").exists())
    loader_source = (policy_dir / "loader.py").read_text(encoding="utf-8")
    self.assertNotIn("get_planner_prompt_template", loader_source)
    self.assertNotIn("class QueryPolicy", loader_source)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: FAIL because old files still exist or exports still mention old accessors.

- [ ] **Step 3: Delete old resources**

Delete:

```text
rag_modules/query_policy/defaults.json
rag_modules/query_policy/planner_prompt.txt
```

Remove any remaining imports of:

```python
QueryPolicy
get_planner_prompt_template
flatten_term_groups
```

Use:

```powershell
rg -n "QueryPolicy|get_planner_prompt_template|flatten_term_groups|defaults\\.json|planner_prompt\\.txt" rag_modules tests
```

Expected after cleanup: only historical docs or the new boundary test mention retired names.

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add rag_modules/query_policy tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py
git commit -m "refactor: retire unversioned policy resources"
```

---

### Task 13: Update Prompt Snapshots And Smoke Fixtures

**Files:**
- Modify: `tests/fixtures/generation_prompt_snapshots/*.txt`
- Modify: `tests/fixtures/generation_prompt_snapshot_corpus.json` if resource prompt naming changes.
- Test: `tests/test_generation_prompt_smoke.py`
- Test: `tests/test_generation_prompt_contract.py`
- Test: `scripts/smoke_generation_prompts.py`

- [ ] **Step 1: Run prompt tests to capture current failures**

Run:

```powershell
python -m pytest tests/test_generation_prompt_smoke.py tests/test_generation_prompt_contract.py -q
```

Expected: FAIL only where resource-rendered prompt snapshots differ from old inline prompt snapshots.

- [ ] **Step 2: Regenerate snapshots through the project script**

Run the existing smoke script in its snapshot-update mode if available:

```powershell
python scripts/smoke_generation_prompts.py
```

If the script only reports diffs, update each file under `tests/fixtures/generation_prompt_snapshots/` by copying the rendered prompt output from the failing assertion into the matching snapshot file. Keep this as one fixture-only change.

- [ ] **Step 3: Re-run prompt tests**

Run:

```powershell
python -m pytest tests/test_generation_prompt_smoke.py tests/test_generation_prompt_contract.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add tests/fixtures/generation_prompt_snapshots tests/fixtures/generation_prompt_snapshot_corpus.json tests/test_generation_prompt_smoke.py tests/test_generation_prompt_contract.py
git commit -m "test: refresh generation prompt snapshots for policy resources"
```

---

### Task 14: Broad Verification And Release Gate

**Files:**
- No source edits unless verification exposes a regression.
- Test: focused and broad suites listed below.

- [ ] **Step 1: Run focused policy, generation, graph, trace, eval tests**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py tests/test_generation_prompt_contract.py tests/test_generation_executor.py tests/test_graph_retrieval_executor.py tests/test_query_tracer.py tests/test_eval_queries.py -q
```

Expected: PASS.

- [ ] **Step 2: Run API and public boundary tests**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_api_app.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 3: Run configuration tests touched by policy selector**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py -q
```

Expected: PASS.

- [ ] **Step 4: Run full tests**

Run:

```powershell
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Run hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect `git diff`, re-run focused tests for touched areas, then re-run pre-commit.

- [ ] **Step 6: Run release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 7: Final commit if verification changed files**

If verification caused fixture or formatting changes:

```powershell
git status --short
git add rag_modules tests scripts docs
git commit -m "chore: verify versioned policy governance"
```

If no files changed, do not create an empty commit.

---

## Self-Review Notes

- Spec coverage: tasks cover typed bundle resources, policy selector config, routing/scoring, graph templates, generation prompts and rule plans, generation decision rules, trace metadata, API debug schemas, eval reports, old schema removal, snapshot updates, and verification.
- Breaking-refactor constraint: the plan rejects old schema, deletes old resource files, and removes legacy exports instead of adding dual loaders.
- Type consistency: the plan uses `QueryPolicyBundle`, `PolicyMetadata`, `PolicySnapshot`, `PolicyLoadError`, `PromptTemplates`, `LexiconPolicy`, `RelationPolicy`, `ScoringPolicy`, `RoutingPolicy`, `GraphPolicy`, and `GenerationPolicy` consistently.
- Verification coverage: focused tests run before broad API/public/config suites, followed by full pytest, pre-commit, and release gate.
