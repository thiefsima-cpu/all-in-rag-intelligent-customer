from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from rag_modules.app.composition.serving_runtime_factory import ServingRuntimeFactory
from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import QueryPlannerRuntimeSettings, RetrievalRequest
from rag_modules.graph.query_resolution import GraphQueryFactory
from rag_modules.graph.retrieval_runtime import GraphRetrievalRuntime
from rag_modules.query_policy.loader import load_policy_bundle
from rag_modules.query_understanding.planning.service import QueryPlanner

QUERY_UNDERSTANDING_PACKAGE = Path("rag_modules/query_understanding")


def _policy_payload() -> dict:
    return {
        "lexicon": {
            "term_sets": {
                "relation_markers": ["custom relation marker"],
                "flavor_terms": ["umami"],
                "texture_effect_terms": [],
                "technique_terms": [],
                "diet_terms": [],
                "health_terms": [],
                "cuisine_style_terms": [],
                "ingredient_category_terms": [],
                "difficulty_terms": [],
                "time_markers": [],
                "path_markers": [],
                "subgraph_markers": [],
                "clustering_markers": [],
                "recommendation_markers": [],
                "explicit_recommendation_markers": [],
                "ambiguous_recommendation_markers": [],
                "filtering_markers": [],
                "structural_reasoning_markers": [],
                "fast_rule_markers": [],
                "constraint_markers": [],
                "entity_hints": [],
                "entity_phrase_markers": [],
                "entity_target_markers": [],
                "graph_generic_terms": [],
                "query_stopwords": [],
                "graph_source_prefixes": [],
                "graph_source_suffixes": [],
            },
            "regex_rules": {
                "recommendation_patterns": [],
                "time_minutes_patterns": [],
                "time_hours_patterns": [],
                "time_half_hour_patterns": [],
                "entity_cleanup_prefix_patterns": [],
                "graph_context_suffix_patterns": [],
                "entity_cleanup_suffix_patterns": [],
                "pairwise_entity_patterns": [],
                "excluded_term_patterns": [],
            },
        },
        "relations": {
            "graph_routing_strategies": ["graph_rag", "combined", "hybrid_traditional"],
            "graph_query_types": ["entity_relation", "subgraph"],
            "graph_relation_types": ["CUSTOM_REL"],
            "preferred_relation_excluded_types": [],
            "semantic_relation_hints": {"custom relation marker": "CUSTOM_REL"},
            "relation_index_keywords": {"CUSTOM_REL": ["custom relation marker"]},
            "relation_index_suffix_templates": {"CUSTOM_REL": "{source_entity}_custom"},
            "relation_query_markers": {"CUSTOM_REL": ["custom relation marker"]},
            "entity_linker": {
                "preferred_labels": ["Recipe"],
                "query_type_priorities": {"entity_relation": ["Recipe"]},
                "relation_priorities": {"CUSTOM_REL": ["Recipe"]},
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
            "graph_first_query_types": ["subgraph"],
            "multi_hop_graph_first_relation_hits": 2,
            "meaningful_constraint_fields": ["needs_recipe_recommendation"],
            "validation_labels": {
                "strategy": "strategy_adjusted",
                "graph_query_type": "query_type_adjusted",
                "source_entities": "source_entities_added",
            },
        },
        "graph": {
            "max_depth": {"default": 2, "subgraph": 3},
            "max_nodes": {"default": 50, "subgraph": 80},
            "reasoning": {
                "causal_relation_types": ["CUSTOM_REL"],
                "compositional_relation_types": [],
                "comparison_markers": ["compare"],
                "semantic_relation_key_specs": {
                    "CUSTOM_REL": {"target_field": "effect", "key_fields": ["effect"]}
                },
            },
            "sub_questions": [
                {
                    "id": "fallback",
                    "when": {"fallback": True},
                    "template": "CUSTOM_GRAPH_GOAL {query}",
                }
            ],
        },
        "generation": {
            "answer_types": {
                "direct_answer": {"markers": []},
                "recommendation": {"markers": []},
                "explanation": {"markers": []},
                "comparison": {"markers": []},
            },
            "relation_explanation_markers": ["custom relation marker"],
            "rule_plan": {
                "default_outline": ["Answer directly"],
                "fallback_outline": ["Fallback answer"],
                "graph_caution": "Use graph evidence carefully.",
                "missing_relation_evidence": "Missing graph evidence.",
                "sparse_evidence": "Sparse evidence.",
                "missing_information_caution": "Missing information caution.",
                "fallback_claim_template": "{recipe_name} evidence.",
            },
            "decision": {
                "default_answer_type": "direct_answer",
                "high_pressure_margin": 0.12,
                "reasons": {
                    "two_stage_disabled": "two_stage_disabled",
                    "no_route_analysis": "no_route_analysis",
                    "graph_without_analysis": "graph_without_analysis",
                    "graph_rag": "graph_rag",
                    "combined_pressure": "combined_pressure",
                    "high_pressure": "high_pressure",
                    "simple": "simple",
                },
            },
            "fallback_answer": {
                "empty_evidence": "No evidence.",
                "heading": "Evidence-only answer:",
                "item_line": "{index}. {title} ({citation})",
                "matched_terms": "Matched terms: {matched_terms}",
                "graph_claim": "Graph evidence: {claim}",
                "text_claim": "Text evidence: {claim}",
                "constraint_reasons": "Constraints: {constraint_reasons}",
                "boundary": "Evidence-only boundary.",
                "model_unavailable": "Model unavailable.",
            },
        },
        "runtime_defaults": {
            "planner": {"model_name": "test-policy-model"},
            "semantics": {"default_max_depth": 2, "default_max_nodes": 50},
        },
    }


def _write_policy_bundle(root: Path, *, name: str = "custom-bundle") -> None:
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    (root / "policy.json").write_text(
        json.dumps(_policy_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_payloads = {
        "query_planner": (
            "CUSTOM_PROMPT_MARKER {query} {graph_query_types_text} "
            "{relation_types_text} {preferred_relation_types_text}"
        ),
        "answer_plan": "{question} {evidence_summary}",
        "answer_compose": "{question} {plan_json} {evidence_text}",
        "answer_direct": "{question} {evidence_text}",
    }
    for prompt_name, text in prompt_payloads.items():
        (prompts / f"{prompt_name}.txt").write_text(text, encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "policy-bundle-v1",
                "policy_version": f"{name}-policy",
                "prompt_version": f"{name}-prompts",
                "name": name,
                "policy_path": "policy.json",
                "prompts": {
                    prompt_name: f"prompts/{prompt_name}.txt" for prompt_name in prompt_payloads
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _iter_python_paths(path: Path) -> tuple[Path, ...]:
    if path.is_file():
        return (path,)
    return tuple(sorted(path.rglob("*.py")))


def _iter_package_nodes(path: Path, node_types):
    for module_path in _iter_python_paths(path):
        source = module_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(module_path))
        for node in ast.walk(tree):
            if isinstance(node, node_types):
                yield module_path, node


def _attribute_path(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def _assignment_targets(node: ast.AST) -> tuple[ast.AST, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    if isinstance(node, ast.AnnAssign):
        return (node.target,)
    return ()


def _node_location(path: Path, node: ast.AST) -> str:
    return f"{path}:{getattr(node, 'lineno', '?')}"


class _PromptCapturingLLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_completion(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])


def test_query_planner_uses_injected_policy_bundle_for_prompt(tmp_path: Path) -> None:
    _write_policy_bundle(tmp_path)
    load_policy_bundle.cache_clear()
    bundle = load_policy_bundle(tmp_path)
    llm_client = _PromptCapturingLLM()
    planner = QueryPlanner(
        llm_client,
        settings=QueryPlannerRuntimeSettings(fast_rule_planning=False),
        policy_bundle=bundle,
    )

    planner.plan("custom query")

    prompt = llm_client.calls[0]["prompt"]
    assert "CUSTOM_PROMPT_MARKER" in prompt
    assert "CUSTOM_REL" in prompt
    assert bundle.metadata.bundle_name == "custom-bundle"


def test_graph_retrieval_runtime_uses_injected_policy_snapshot(tmp_path: Path) -> None:
    _write_policy_bundle(tmp_path)
    load_policy_bundle.cache_clear()
    bundle = load_policy_bundle(tmp_path)
    query_factory = GraphQueryFactory(policy_bundle=bundle)
    runtime = GraphRetrievalRuntime(query_factory, policy_bundle=bundle)

    trace = runtime.start_trace(
        "custom query",
        requested_top_k=2,
        retrieval_request=RetrievalRequest(query="custom query", top_k=2),
    )

    assert trace.policy.bundle_name == "custom-bundle"
    assert trace.policy.policy_version == "custom-bundle-policy"


def test_serving_runtime_factory_passes_selected_policy_bundle_to_runtime_providers(
    tmp_path: Path,
) -> None:
    _write_policy_bundle(tmp_path, name="factory-bundle")
    load_policy_bundle.cache_clear()
    config = build_test_config().with_overrides(
        {"query_understanding": {"policy": {"bundle_path": str(tmp_path)}}}
    )
    profile = SimpleNamespace(name="profile")
    understanding_service = SimpleNamespace(name="understanding")
    traditional_retrieval = SimpleNamespace(name="traditional")
    graph_rag_retrieval = SimpleNamespace(name="graph")
    router = SimpleNamespace(name="router")
    answer_workflow = SimpleNamespace(name="workflow")

    infrastructure = SimpleNamespace(
        provide_neo4j_manager=lambda config, existing=None: SimpleNamespace(name="neo4j"),
        provide_data_module=lambda config, neo4j_manager, existing=None: SimpleNamespace(
            name="data"
        ),
        provide_index_module=lambda config, existing=None: SimpleNamespace(name="index"),
        provide_query_tracer=lambda config, existing=None: SimpleNamespace(name="tracer"),
    )
    services = SimpleNamespace(provide_answer_workflow=lambda **kwargs: answer_workflow)

    class _Provider:
        def __init__(self) -> None:
            self.infrastructure = infrastructure
            self.retrieval_runtime = self
            self.services = services
            self.seen_policy_names: list[str] = []

        def _record(self, policy_bundle) -> None:
            self.seen_policy_names.append(policy_bundle.metadata.bundle_name)

        def provide_generation_module(self, config, *, policy_bundle):
            del config
            self._record(policy_bundle)
            return SimpleNamespace(client=SimpleNamespace(), llm_client=SimpleNamespace())

        def provide_retrieval_runtime_profile(self, config, *, policy_bundle):
            del config
            self._record(policy_bundle)
            return profile

        def provide_query_understanding_service(self, *, policy_bundle, **kwargs):
            del kwargs
            self._record(policy_bundle)
            return understanding_service

        def provide_traditional_retrieval(self, **kwargs):
            del kwargs
            return traditional_retrieval

        def provide_graph_rag_retrieval(self, *, policy_bundle, **kwargs):
            del kwargs
            self._record(policy_bundle)
            return graph_rag_retrieval

        def provide_routing_workflow(self, *, policy_bundle, **kwargs):
            del kwargs
            self._record(policy_bundle)
            return router

    provider = _Provider()
    factory = ServingRuntimeFactory(provider=provider)

    runtime = factory.build(config=config)

    assert runtime.retrieval_runtime_profile is profile
    assert runtime.query_understanding_service is understanding_service
    assert provider.seen_policy_names == [
        "factory-bundle",
        "factory-bundle",
        "factory-bundle",
        "factory-bundle",
        "factory-bundle",
    ]


def test_query_understanding_registry_does_not_load_policy_at_import_time() -> None:
    eager_policy_assignments = [
        _node_location(path, node)
        for path, node in _iter_package_nodes(
            QUERY_UNDERSTANDING_PACKAGE,
            (ast.Assign, ast.AnnAssign),
        )
        if any(_attribute_path(target) == ("POLICY",) for target in _assignment_targets(node))
        if isinstance(node.value, ast.Call)
        and _attribute_path(node.value.func) == ("get_query_policy",)
    ]
    package_eager_registry_imports = [
        _node_location(path, node)
        for path, node in _iter_package_nodes(QUERY_UNDERSTANDING_PACKAGE / "__init__.py", ast.AST)
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module == "registry"
    ]

    assert eager_policy_assignments == []
    assert package_eager_registry_imports == []
