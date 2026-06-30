from __future__ import annotations

import json
import unittest
from pathlib import Path

import pytest

from rag_modules.query_policy import get_planner_prompt_template, get_query_policy


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


class QueryPolicyTests(unittest.TestCase):
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

    def test_policy_bundle_preserves_structured_policy_sections(self) -> None:
        bundle = get_query_policy()

        self.assertEqual(
            "calibrated_strategy",
            bundle.routing.validation_labels["strategy"],
        )
        self.assertTrue(bundle.graph.sub_questions)
        self.assertIn("id", bundle.graph.sub_questions[0])
        self.assertIn("template", bundle.graph.sub_questions[0])
        self.assertIn("direct_answer", bundle.generation.answer_types)
        self.assertIsInstance(bundle.generation.answer_types["direct_answer"], dict)
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

    def test_policy_uses_clean_utf8_terms(self) -> None:
        policy = get_query_policy().lexicon

        self.assertIn("麻辣", policy.term_group("flavor_terms"))
        self.assertIn("关系", policy.term_group("relation_markers"))
        self.assertNotIn("楹昏荆", policy.term_group("flavor_terms"))
        self.assertNotIn("鍏崇郴", policy.term_group("relation_markers"))

    def test_planner_prompt_template_has_required_placeholders(self) -> None:
        template = get_planner_prompt_template()

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

    def test_registry_reads_terms_from_typed_policy_bundle(self) -> None:
        from rag_modules.query_understanding.registry import POLICY, RELATION_MARKERS

        self.assertEqual("c9-default-policy-v1", POLICY.metadata.policy_version)
        self.assertEqual(POLICY.lexicon.term_group("relation_markers"), RELATION_MARKERS)

    def test_query_understanding_consumers_use_typed_policy_sections(self) -> None:
        registry_source = Path("rag_modules/query_understanding/registry.py").read_text(
            encoding="utf-8"
        )
        features_source = Path("rag_modules/query_understanding/features.py").read_text(
            encoding="utf-8"
        )
        prompting_source = Path("rag_modules/query_understanding/planning/prompting.py").read_text(
            encoding="utf-8"
        )
        relation_index_source = Path("rag_modules/graph_index/relation_index_builder.py").read_text(
            encoding="utf-8"
        )
        reasoning_source = Path("rag_modules/graph/reasoning_strategy.py").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("POLICY.term_group", registry_source)
        self.assertNotIn("POLICY.regex_group", features_source)
        self.assertNotIn("POLICY.term_group", features_source)
        self.assertNotIn("get_planner_prompt_template", prompting_source)
        self.assertNotIn("_RELATION_TYPE_HINTS", relation_index_source)
        self.assertNotIn('{"REQUIRES", "BELONGS_TO_CATEGORY", "CONTAINS_STEP"}', prompting_source)
        self.assertNotIn("causal_relation_types = {", reasoning_source)
        self.assertIn("POLICY.lexicon.term_group", registry_source)
        self.assertIn("POLICY.lexicon.regex_group", features_source)
        self.assertIn("policy = get_query_policy()", prompting_source)
        self.assertIn("policy.prompts.query_planner", prompting_source)


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


def test_policy_loader_rejects_missing_prompt_variable(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(
        tmp_path,
        query_planner="{query} {graph_query_types_text} {preferred_relation_types_text}",
    )

    with pytest.raises(PolicyLoadError, match="relation_types_text"):
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


def test_policy_loader_rejects_incomplete_graph_reasoning_policy(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["graph"]["reasoning"].pop("comparison_markers")
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PolicyLoadError, match="graph.reasoning.comparison_markers"):
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
