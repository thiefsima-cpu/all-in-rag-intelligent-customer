from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

import pytest

from rag_modules.query_policy import get_query_policy

QUERY_UNDERSTANDING_PACKAGE = Path("rag_modules/query_understanding")
QUERY_POLICY_MODELS = Path("rag_modules/query_policy/models.py")
QUERY_UNDERSTANDING_REGISTRY = Path("rag_modules/query_understanding/registry.py")
GRAPH_INDEX_PACKAGE = Path("rag_modules/graph_index")
GRAPH_PACKAGE = Path("rag_modules/graph")
LEGACY_PREFERRED_RELATION_TYPES = frozenset({"REQUIRES", "BELONGS_TO_CATEGORY", "CONTAINS_STEP"})


def _answer_workflow_copy_payload() -> dict[str, str]:
    return {
        "no_evidence_answer": "No evidence.",
        "answer_failed": "Answer failed.",
        "user_question_template": "Question: {question}",
        "query_routing_started": "Routing started.",
        "answer_generation_started": "Generation started.",
        "streaming_interrupted_fallback": "Stream interrupted.",
        "answer_complete_template": "Done in {latency_seconds:.2f}s",
        "strategy_summary_template": (
            "{strategy_icon} Strategy: {strategy}\n"
            "Complexity: {complexity:.2f}, "
            "Relationship intensity: {relationship_intensity:.2f}"
        ),
        "strategy_icon_hybrid_traditional": "[HYBRID]",
        "strategy_icon_graph_rag": "[GRAPH]",
        "strategy_icon_combined": "[COMBINED]",
        "strategy_icon_default": "[ROUTE]",
        "document_summary_template": (
            "Found {document_count} relevant documents: {document_summaries}"
        ),
        "document_summary_total_template": "\n    Total results: {document_count}",
        "unknown_recipe_name": "unknown",
        "unknown_search_type": "unknown",
    }


def _minimal_policy_payload() -> dict:
    return {
        "lexicon": {
            "term_sets": {
                "relation_markers": ["relationship"],
                "flavor_terms": ["麻辣"],
            },
            "regex_rules": {
                "recommendation_patterns": ["recommend"],
            },
        },
        "relations": {
            "graph_routing_strategies": ["graph_rag"],
            "graph_query_types": ["entity_relation", "subgraph"],
            "graph_relation_types": ["CONTRIBUTES_TO", "REQUIRES"],
            "preferred_relation_excluded_types": ["REQUIRES"],
            "semantic_relation_hints": {"impact": "CONTRIBUTES_TO"},
            "relation_index_keywords": {"CONTRIBUTES_TO": ["impact"]},
            "relation_index_suffix_templates": {"REQUIRES": "{source_entity}_ingredient"},
            "relation_query_markers": {"CONTRIBUTES_TO": ["why"]},
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
            "graph_first_query_types": ["subgraph"],
            "multi_hop_graph_first_relation_hits": 2,
            "meaningful_constraint_fields": ["include_terms", "exclude_terms"],
            "validation_labels": {
                "strategy": "calibrated_strategy",
                "graph_query_type": "calibrated_graph_query_type",
                "source_entities": "calibrated_source_entities",
            },
        },
        "graph": {
            "max_depth": {"default": 2},
            "max_nodes": {"default": 50},
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
                {
                    "id": "fallback",
                    "when": {"fallback": True},
                    "template": (
                        "Retrieve recipes, ingredients, steps, and semantic graph relations "
                        "relevant to the question."
                    ),
                }
            ],
        },
        "generation": {
            "answer_types": {
                "direct_answer": {"markers": []},
                "recommendation": {"markers": ["recommend"]},
                "explanation": {"markers": ["why"]},
                "comparison": {"markers": ["compare"]},
            },
            "relation_explanation_markers": ["relationship"],
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
            "answer_workflow_copy": _answer_workflow_copy_payload(),
        },
        "runtime_defaults": {
            "planner": {"model_name": "test"},
            "semantics": {"default_max_depth": 2, "default_max_nodes": 50},
        },
    }


def _write_bundle(
    root: Path,
    *,
    manifest: dict | None = None,
    query_planner: str | None = None,
) -> None:
    prompts = root / "prompts"
    prompts.mkdir(parents=True)
    (root / "policy.json").write_text(
        json.dumps(_minimal_policy_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    prompt_payloads = {
        "query_planner": query_planner
        or "{query} {graph_query_types_text} {relation_types_text} {preferred_relation_types_text}",
        "answer_plan": "{question} {evidence_summary}",
        "answer_compose": "{question} {plan_json} {evidence_text}",
        "answer_direct": "{question} {evidence_text}",
    }
    for name, text in prompt_payloads.items():
        (prompts / f"{name}.txt").write_text(text, encoding="utf-8")

    bundle_manifest = {
        "schema_version": "policy-bundle-v1",
        "policy_version": "c9-default-policy-v1",
        "prompt_version": "c9-default-prompts-v1",
        "name": "c9-default-v1",
        "policy_path": "policy.json",
        "prompts": {name: f"prompts/{name}.txt" for name in prompt_payloads},
    }
    if manifest is not None:
        bundle_manifest = manifest
    (root / "manifest.json").write_text(
        json.dumps(bundle_manifest, ensure_ascii=False),
        encoding="utf-8",
    )


def _iter_package_nodes(package_path: Path, node_types):
    for path in sorted(package_path.rglob("*.py")):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, node_types):
                yield path, node


def _attribute_path(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return tuple(reversed(parts))
    return None


def _literal_string_values(node: ast.AST) -> frozenset[str] | None:
    if not isinstance(node, ast.Set | ast.List | ast.Tuple):
        return None
    values: set[str] = set()
    for item in node.elts:
        if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
            return None
        values.add(item.value)
    return frozenset(values)


def _assignment_value(node: ast.AST) -> ast.AST | None:
    if isinstance(node, ast.Assign | ast.AnnAssign):
        return node.value
    return None


def _assignment_targets(node: ast.AST) -> tuple[ast.AST, ...]:
    if isinstance(node, ast.Assign):
        return tuple(node.targets)
    if isinstance(node, ast.AnnAssign):
        return (node.target,)
    return ()


def _node_location(path: Path, node: ast.AST) -> str:
    return f"{path}:{getattr(node, 'lineno', '?')}"


def _class_method_names(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    matches = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {class_name} in {path}, found {len(matches)}")
    return {
        node.name
        for node in matches[0].body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _annotation_name(node: ast.AST | None) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Constant) and node.value is None:
        return "None"
    return ""


def _is_optional_query_policy_bundle(node: ast.AST | None) -> bool:
    return (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.BitOr)
        and _annotation_name(node.left) == "QueryPolicyBundle"
        and _annotation_name(node.right) == "None"
    )


def _has_policy_bundle_default_none_arg(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        if (
            arg.arg == "policy_bundle"
            and _is_optional_query_policy_bundle(arg.annotation)
            and isinstance(default, ast.Constant)
            and default.value is None
        ):
            return True
    return False


class QueryPolicyTests(unittest.TestCase):
    def test_bundle_types_do_not_expose_lexicon_convenience_methods(self) -> None:
        retired_methods = {"term_group", "regex_group"}

        self.assertTrue(
            retired_methods.isdisjoint(
                _class_method_names(QUERY_POLICY_MODELS, "QueryPolicyBundle")
            )
        )
        self.assertTrue(
            retired_methods.isdisjoint(
                _class_method_names(QUERY_UNDERSTANDING_REGISTRY, "_LazyPolicyBundle")
            )
        )

    def test_policy_bundle_exposes_versions_and_hashes(self) -> None:
        bundle = get_query_policy()

        self.assertEqual("policy-bundle-v1", bundle.metadata.schema_version)
        self.assertEqual("c9-default-policy-v1", bundle.metadata.policy_version)
        self.assertEqual("c9-default-prompts-v1", bundle.metadata.prompt_version)
        self.assertTrue(bundle.metadata.policy_hash.startswith("sha256:"))
        self.assertTrue(bundle.metadata.prompt_hash.startswith("sha256:"))
        self.assertEqual("c9-default-v1", bundle.metadata.bundle_name)
        self.assertIn("relation_markers", bundle.lexicon.term_sets)
        self.assertIn("CONTRIBUTES_TO", bundle.relations.graph_relation_types)

    def test_default_runtime_model_is_qwen_3_7_plus(self) -> None:
        bundle = get_query_policy()

        self.assertEqual("qwen3.7-plus", bundle.runtime_defaults.planner.model_name)

    def test_default_runtime_reranker_is_qwen_3_vl(self) -> None:
        bundle = get_query_policy()

        self.assertEqual("qwen3-vl-rerank", bundle.runtime_defaults.postprocess.rerank_model)

    def test_policy_bundle_preserves_structured_policy_sections(self) -> None:
        bundle = get_query_policy()

        self.assertEqual(
            "calibrated_strategy",
            bundle.routing.validation_labels["strategy"],
        )
        self.assertTrue(bundle.graph.sub_questions)
        sub_question = next(rule for rule in bundle.graph.sub_questions if rule.id == "fallback")
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
            "graph_rag_strategy",
        )
        self.assertTrue(bundle.generation.rule_plan.default_outline)
        self.assertIn("REQUIRES", bundle.relations.preferred_relation_excluded_types)
        self.assertIn(
            "CONTRIBUTES_TO",
            bundle.graph.reasoning.causal_relation_types,
        )
        self.assertIn(
            "CONTRIBUTES_TO",
            bundle.graph.reasoning.semantic_relation_key_specs,
        )
        self.assertEqual(
            "基于当前检索证据，我先给出一个保底回答：",
            bundle.generation.fallback_answer["heading"],
        )

    def test_policy_bundle_exposes_answer_workflow_copy(self) -> None:
        copy = get_query_policy().generation.answer_workflow_copy

        self.assertEqual(
            copy.no_evidence_answer,
            "Sorry, I could not find enough relevant retrieval evidence to answer that question.",
        )
        self.assertEqual(copy.answer_failed, "The answer could not be generated.")
        self.assertEqual(copy.user_question_template, "\nUser question: {question}")
        self.assertEqual(copy.query_routing_started, "Running query routing...")
        self.assertEqual(copy.answer_generation_started, "Generating answer...")
        self.assertEqual(copy.strategy_icon_graph_rag, "[GRAPH]")
        self.assertEqual(copy.unknown_recipe_name, "unknown")

    def test_policy_uses_clean_utf8_terms(self) -> None:
        policy = get_query_policy().lexicon

        self.assertIn("麻辣", policy.term_group("flavor_terms"))
        self.assertIn("关系", policy.term_group("relation_markers"))
        self.assertNotIn("楹昏荆", policy.term_group("flavor_terms"))
        self.assertNotIn("鍏崇郴", policy.term_group("relation_markers"))

    def test_planner_prompt_template_has_required_placeholders(self) -> None:
        template = get_query_policy().prompts.query_planner

        self.assertIn("{graph_query_types_text}", template)
        self.assertIn("{relation_types_text}", template)
        self.assertIn("{preferred_relation_types_text}", template)
        self.assertIn("{query}", template)
        self.assertIn("graph_rag", template)
        self.assertNotIn("鍥捐氨", template)

    def test_policy_bundle_prompts_are_format_templates(self) -> None:
        prompts = get_query_policy().prompts

        prompts.query_planner.format(
            query="q",
            graph_query_types_text="g",
            relation_types_text="r",
            preferred_relation_types_text="p",
        )
        prompts.answer_plan.format(question="q", evidence_summary="e")
        prompts.answer_compose.format(question="q", plan_json="p", evidence_text="e")
        prompts.answer_direct.format(question="q", evidence_text="e")

    def test_answer_prompts_honor_explicit_language_and_clarification_requests(self) -> None:
        prompts = get_query_policy().prompts

        for template in (prompts.answer_direct, prompts.answer_compose):
            self.assertIn("用户明确指定回答语言时，使用该语言", template)
            self.assertIn("只提出必要的澄清问题", template)
            self.assertIn("不猜测菜名或给出菜谱", template)
            self.assertIn("整个回答只能包含一个问句", template)
            self.assertIn("不得添加解释、证据摘要或候选项", template)
            self.assertIn("声称证据缺失前，先核对全部可见证据", template)

    def test_registry_reads_terms_from_typed_policy_bundle(self) -> None:
        from rag_modules.query_understanding.registry import POLICY, RELATION_MARKERS

        self.assertEqual("c9-default-policy-v1", POLICY.metadata.policy_version)
        self.assertEqual(POLICY.lexicon.term_group("relation_markers"), RELATION_MARKERS)

    def test_query_understanding_consumers_use_typed_policy_sections(self) -> None:
        query_understanding_calls = tuple(
            _iter_package_nodes(QUERY_UNDERSTANDING_PACKAGE, ast.Call)
        )
        query_understanding_call_paths = {
            _attribute_path(node.func) for _, node in query_understanding_calls
        }
        legacy_policy_helper_calls = [
            _node_location(path, node)
            for path, node in query_understanding_calls
            if _attribute_path(node.func)
            in {
                ("POLICY", "term_group"),
                ("POLICY", "regex_group"),
            }
        ]
        legacy_relation_type_hint_names = [
            _node_location(path, node)
            for path, node in _iter_package_nodes(GRAPH_INDEX_PACKAGE, ast.Name)
            if node.id == "_RELATION_TYPE_HINTS"
        ]
        legacy_preferred_relation_literals = [
            _node_location(path, node)
            for path, node in _iter_package_nodes(QUERY_UNDERSTANDING_PACKAGE, ast.AST)
            if _literal_string_values(node) == LEGACY_PREFERRED_RELATION_TYPES
        ]
        hardcoded_causal_relation_assignments = [
            _node_location(path, node)
            for path, node in _iter_package_nodes(GRAPH_PACKAGE, (ast.Assign, ast.AnnAssign))
            if isinstance(_assignment_value(node), ast.Set)
            for target in _assignment_targets(node)
            if _attribute_path(target)
            in {
                ("causal_relation_types",),
                ("self", "causal_relation_types"),
            }
        ]
        planning_prompt_injection_points = [
            _node_location(path, node)
            for path, node in _iter_package_nodes(
                QUERY_UNDERSTANDING_PACKAGE,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            if node.name == "build_planning_prompt" and _has_policy_bundle_default_none_arg(node)
        ]

        self.assertEqual([], legacy_policy_helper_calls)
        self.assertEqual([], legacy_relation_type_hint_names)
        self.assertEqual([], legacy_preferred_relation_literals)
        self.assertEqual([], hardcoded_causal_relation_assignments)
        self.assertIn(("policy", "lexicon", "term_group"), query_understanding_call_paths)
        self.assertIn(
            ("active_registry", "policy", "lexicon", "regex_group"),
            query_understanding_call_paths,
        )
        self.assertTrue(planning_prompt_injection_points)
        self.assertIn(
            ("policy", "prompts", "query_planner", "format"),
            query_understanding_call_paths,
        )


def test_policy_loader_rejects_unversioned_schema(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(
        tmp_path,
        manifest={
            "policy_version": "legacy-policy",
            "prompt_version": "legacy-prompts",
            "name": "legacy",
            "policy_path": "policy.json",
            "prompts": {
                "query_planner": "prompts/query_planner.txt",
                "answer_plan": "prompts/answer_plan.txt",
                "answer_compose": "prompts/answer_compose.txt",
                "answer_direct": "prompts/answer_direct.txt",
            },
        },
    )

    with pytest.raises(PolicyLoadError, match="schema_version"):
        load_policy_bundle(tmp_path)


def test_policy_runtime_defaults_are_typed_sections(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import load_policy_bundle

    _write_bundle(tmp_path)
    load_policy_bundle.cache_clear()
    bundle = load_policy_bundle(tmp_path)

    assert bundle.runtime_defaults.planner.model_name == "test"
    assert bundle.runtime_defaults.semantics.default_max_depth == 2


def test_policy_loader_migrates_additive_v1_fields_for_custom_bundle(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import load_policy_bundle

    _write_bundle(tmp_path)
    load_policy_bundle.cache_clear()
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    generation = policy["generation"]
    generation["decision"]["reasons"].pop("simple")
    generation["fallback_answer"].pop("model_unavailable")
    answer_workflow_copy = generation["answer_workflow_copy"]
    for field_name in (
        "query_routing_started",
        "answer_generation_started",
        "streaming_interrupted_fallback",
        "unknown_recipe_name",
        "unknown_search_type",
    ):
        answer_workflow_copy.pop(field_name)
    graph_reasoning = policy["graph"]["reasoning"]
    graph_reasoning.pop("comparison_markers")
    graph_reasoning.pop("semantic_relation_key_specs")
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    bundle = load_policy_bundle(tmp_path)

    assert bundle.generation.answer_workflow_copy.no_evidence_answer == "No evidence."
    assert (
        bundle.generation.answer_workflow_copy.query_routing_started == "Running query routing..."
    )
    assert bundle.generation.answer_workflow_copy.unknown_recipe_name == "unknown"
    assert bundle.generation.decision.reasons.simple == "simple"
    assert bundle.generation.fallback_answer["model_unavailable"] == "Model unavailable."
    assert bundle.graph.reasoning.comparison_markers == ()
    assert bundle.graph.reasoning.semantic_relation_key_specs == {}


def test_policy_loader_delegates_to_focused_section_parsers() -> None:
    parser_dir = Path("rag_modules/query_policy/parsers")
    parser_modules = {path.name for path in parser_dir.glob("*.py")}

    assert {
        "common.py",
        "generation.py",
        "graph.py",
        "lexicon.py",
        "relations.py",
        "runtime_defaults.py",
        "scoring.py",
        "routing.py",
    }.issubset(parser_modules)

    loader_source = Path("rag_modules/query_policy/loader.py").read_text(encoding="utf-8")
    assert len(loader_source.splitlines()) < 250
    assert "RuntimeDefaultsPolicy(" not in loader_source
    assert "GraphSubQuestionPolicy(" not in loader_source


def test_policy_loader_rejects_missing_prompt_variable(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(
        tmp_path,
        query_planner="{query} {graph_query_types_text} {preferred_relation_types_text}",
    )

    with pytest.raises(PolicyLoadError, match="relation_types_text"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_pairwise_regex_without_two_capture_groups(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["lexicon"]["regex_rules"]["pairwise_entity_patterns"] = [
        "(?:订单|政策)\\s*([A-Za-z0-9_.-]+)"
    ]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="exactly two capture groups"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_entity_reference_regex_without_one_capture_group(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["lexicon"]["regex_rules"]["entity_reference_patterns"] = ["(order)\\s*([A-Za-z0-9-]+)"]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="exactly one capture group"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_unknown_domain_strategy_rule(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["routing"]["strategy_rules"] = [
        {"strategy": "unknown", "relation_types_any": ["CONTRIBUTES_TO"]}
    ]
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="Routing strategy rule is invalid"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_legacy_generation_policy(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["generation"]["rule_plan"].pop("default_outline")
    policy["generation"]["rule_plan"]["outline"] = ["legacy outline"]
    policy["generation"]["decision"].pop("reasons")
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="generation.rule_plan.default_outline"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_malformed_answer_workflow_copy_section(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["generation"]["answer_workflow_copy"] = []
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PolicyLoadError,
        match="generation.answer_workflow_copy",
    ):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_unknown_answer_workflow_template_variable(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["generation"]["answer_workflow_copy"]["answer_complete_template"] = "Done in {seconds}s"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PolicyLoadError,
        match="generation.answer_workflow_copy.answer_complete_template.seconds",
    ):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_unknown_graph_sub_question_condition(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["graph"]["sub_questions"][0]["when"]["unsupported_condition"] = True
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="graph.sub_questions\\[0\\].when"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_incomplete_graph_reasoning_policy(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["graph"]["reasoning"].pop("causal_relation_types")
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="graph.reasoning.causal_relation_types"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_non_list_graph_reasoning_groups(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["graph"]["reasoning"]["causal_relation_types"] = "CONTRIBUTES_TO"
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="graph.reasoning.causal_relation_types"):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_incomplete_semantic_relation_key_spec(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["graph"]["reasoning"]["semantic_relation_key_specs"]["CONTRIBUTES_TO"] = {
        "target_field": "effect"
    }
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PolicyLoadError,
        match="graph.reasoning.semantic_relation_key_specs.CONTRIBUTES_TO.key_fields",
    ):
        load_policy_bundle(tmp_path)


if __name__ == "__main__":
    unittest.main()
