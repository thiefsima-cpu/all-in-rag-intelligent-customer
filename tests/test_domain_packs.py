from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import rag_modules.domains as domain_registry
from rag_modules.build_pipeline.graph_preparation.domain_loader import (
    DOMAIN_ENTITIES_QUERY,
    DomainGraphDataLoader,
)
from rag_modules.build_pipeline.graph_preparation.state import GraphPreparationState
from rag_modules.build_pipeline.graph_preparation.statistics import (
    GraphPreparationStatisticsService,
)
from rag_modules.build_pipeline.schema_sync import SemanticGraphSchemaSyncService
from rag_modules.configuration import ConfigurationError, load_config
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.contracts import EvidenceDocument, QuerySemanticRuntimeSettings
from rag_modules.contracts.graph_preparation import GraphNode
from rag_modules.contracts.retrieval_documents import evidence_document_from_text_document
from rag_modules.domains import domain_pack_names, get_domain_pack, load_domain_evaluation
from rag_modules.evidence_processing.answer_builder import AnswerEvidenceBuilder
from rag_modules.graph.evidence_builder import GraphEvidenceBuilder
from rag_modules.graph.retrieval_types import (
    GraphNodeSnapshot,
    GraphPath,
    GraphRelationshipSnapshot,
    KnowledgeSubgraph,
)
from rag_modules.interfaces.api.answer_public_models import PublicEvidenceDocumentResponseModel
from rag_modules.kernel.documents import TextDocument
from rag_modules.query_policy.loader import load_policy_bundle
from rag_modules.query_policy.selector import resolve_query_policy_selector
from rag_modules.query_understanding.planning.calibration import QueryPlanCalibrator
from rag_modules.query_understanding.planning.rule_based import RuleBasedPlanner
from rag_modules.query_understanding.registry import QueryUnderstandingRegistry


def test_customer_service_pack_owns_ontology_mapping_projection_and_evaluation() -> None:
    pack = get_domain_pack("customer_service")

    assert domain_pack_names() == ("customer_service", "recipe")
    assert pack.query_policy_bundle == "customer-service-v1"
    assert "Order" in pack.ontology.node_labels
    assert "RefundPolicy" in pack.ontology.node_labels
    assert "Recipe" not in pack.ontology.node_labels
    assert {"order_id", "policy_id", "product_sku", "version"} <= set(
        pack.ontology.entity_lookup_fields
    )
    assert pack.citation_projection.citation_label == "客服证据"
    evaluation = load_domain_evaluation(pack)
    grounded = [
        case for case in evaluation["cases"] if case["expected_response_mode"] == "grounded_answer"
    ]
    assert len(grounded) >= 5
    assert all(case["relevant_entities"] for case in grounded)


def test_customer_service_build_stats_use_domain_neutral_names() -> None:
    state = GraphPreparationState(
        recipes=[
            GraphNode(
                node_id="CS-1001",
                labels=["Order"],
                name="订单 CS-1001",
            )
        ],
        documents=[
            TextDocument(
                content="订单 CS-1001 已发货。",
                metadata={"document_type": "order_status", "content_length": 17},
            )
        ],
    )

    stats = GraphPreparationStatisticsService(domain_name="customer_service").build(state).to_dict()

    assert stats["domain_name"] == "customer_service"
    assert stats["total_entities"] == 1
    assert stats["entity_types"] == {"Order": 1}
    assert stats["document_types"] == {"order_status": 1}
    assert "total_recipes" not in stats
    assert "categories" not in stats
    assert "cuisines" not in stats


def test_customer_service_policy_routes_live_gate_queries_and_extracts_identifiers() -> None:
    config = load_config(
        profile="dev",
        source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "customer_service"}),
    )
    settings = QuerySemanticRuntimeSettings.from_config(config)
    bundle = load_policy_bundle(Path("rag_modules/query_policy/resources/customer-service-v1"))
    planner = RuleBasedPlanner(
        settings,
        QueryPlanCalibrator(settings, policy_bundle=bundle),
        policy_bundle=bundle,
    )
    cases = json.loads(Path("eval/integration_gate.json").read_text(encoding="utf-8"))["live_cases"]
    plans = {case["case_id"]: planner.plan(case["question"]) for case in cases}

    order_plan = plans["vector_customer_lookup"]
    assert order_plan.strategy_value == "hybrid_traditional"
    assert "CS-1001" in order_plan.source_entities

    version_plan = plans["graph_relationship_reasoning"]
    assert version_plan.strategy_value == "graph_rag"
    assert "2026.07" in version_plan.source_entities
    assert "SUPERSEDES" in version_plan.relation_types

    product_plan = plans["combined_constrained_recommendation"]
    assert product_plan.strategy_value == "combined"
    assert "SKU-PHONE-A" in product_plan.source_entities
    assert {"HAS_REFUND_RULE", "HAS_WARRANTY_TERM"} <= set(product_plan.relation_types)


def test_domain_pack_selects_policy_when_environment_overrides_profile_domain() -> None:
    recipe_config = load_config(
        profile="dev",
        source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "recipe"}),
    )
    customer_config = load_config(
        source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "customer_service"}),
    )

    assert recipe_config.domain.name == "recipe"
    assert recipe_config.query_understanding.policy.bundle == "c9-default-v1"
    assert recipe_config.storage.milvus_collection_name == "cooking_knowledge"
    assert customer_config.domain.name == "customer_service"
    assert customer_config.query_understanding.policy.bundle == "customer-service-v1"
    assert customer_config.storage.milvus_collection_name == "customer_service_knowledge"


def test_explicit_vector_collection_override_stays_in_the_selected_domain_bundle() -> None:
    config = load_config(
        source=EnvConfigSource(
            environ={
                "GRAPH_RAG_DOMAIN": "customer_service",
                "MILVUS_COLLECTION_NAME": "tenant_customer_service",
            }
        )
    )

    assert config.domain.name == "customer_service"
    assert config.query_understanding.policy.bundle == "customer-service-v1"
    assert config.storage.milvus_collection_name == "tenant_customer_service"


def test_customer_service_eval_profiles_use_customer_vector_collection() -> None:
    from rag_modules.configuration.env import EnvConfigSource

    for profile in ("eval_fast", "eval_quality"):
        config = load_config(profile=profile, source=EnvConfigSource(environ={}))

        assert config.domain.name == "customer_service"
        assert config.storage.milvus_collection_name == "customer_service_knowledge"
        assert config.query_understanding.policy.bundle == "customer-service-v1"


def test_query_policy_selector_uses_domain_pack_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "rag_modules.query_policy.selector.get_domain_pack",
        lambda domain_name: SimpleNamespace(query_policy_bundle=f"{domain_name}-policy"),
    )

    selector = resolve_query_policy_selector(
        {"domain": {"name": "recipe"}},
        {"domain": {"name": "third_domain"}},
    )

    assert selector.bundle == "third_domain-policy"


def test_domain_registry_accepts_a_pack_without_selector_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domain_registry, "_DOMAIN_PACKS", dict(domain_registry._DOMAIN_PACKS))
    third_pack = replace(get_domain_pack("recipe"), name="third_domain")

    domain_registry.register_domain_pack(third_pack)

    assert get_domain_pack("third-domain") is third_pack
    assert "third_domain" in domain_pack_names()


def test_domain_settings_reject_unknown_pack_without_literal_domain_coupling() -> None:
    with pytest.raises(ValueError, match="Unknown domain pack"):
        load_config(source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "unknown_domain"}))


@pytest.mark.parametrize("domain_name", [None, 0, False, [], {}])
def test_falsy_domain_override_uses_sourced_configuration_error(domain_name: object) -> None:
    with pytest.raises(ConfigurationError) as context:
        load_config(
            {"domain": {"name": domain_name}},
            source=EnvConfigSource(environ={}),
        )

    message = str(context.value)
    assert "overrides load_config" in message
    assert "domain.name" in message
    assert "string" in message


def test_domain_graph_loader_resolves_identity_from_ontology_fields() -> None:
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def run(self, query, parameters):
            assert query == DOMAIN_ENTITIES_QUERY
            assert "RefundPolicy" in parameters["labels"]
            assert parameters["domain_name"] == "customer_service"
            return [
                {
                    "labels": ["RefundPolicy", "ServicePolicy"],
                    "properties": {
                        "nodeId": "POL-REFUND-2026-07",
                        "policy_id": "POL-REFUND-2026-07",
                        "title": "Refund policy 2026.07",
                        "version": "2026.07",
                    },
                }
            ]

    class Driver:
        def session(self, **kwargs):
            assert kwargs["database"] == "neo4j"
            return Session()

    pack = get_domain_pack("customer_service")
    loaded = DomainGraphDataLoader(
        pack.ontology,
        domain_name=pack.name,
    ).load(Driver(), database="neo4j")

    assert loaded.recipes[0].node_id == "POL-REFUND-2026-07"
    assert loaded.recipes[0].name == "Refund policy 2026.07"
    assert "n.orderId" not in DOMAIN_ENTITIES_QUERY
    assert "n.policyId" not in DOMAIN_ENTITIES_QUERY
    assert "n.sku" not in DOMAIN_ENTITIES_QUERY
    assert "n.domain = $domain_name" in DOMAIN_ENTITIES_QUERY


def test_customer_service_mapper_builds_generic_evidence_and_semantic_relations() -> None:
    pack = get_domain_pack("customer_service")
    document = pack.document_mapper.map_document(
        {
            "policy_id": "POL-REFUND-2026-07",
            "title": "七天无理由退货政策",
            "document_type": "refund_policy",
            "product_sku": "SKU-PHONE-A",
            "effective_from": "2026-07-01",
            "version": "2026.07",
            "supersedes": "POL-REFUND-2026-06",
            "content": "商品 SKU-PHONE-A 签收后 7 天内且未拆封可以退货。",
        }
    )

    evidence = evidence_document_from_text_document(document)
    assert evidence.entity_id == "POL-REFUND-2026-07"
    assert evidence.entity_name == "七天无理由退货政策"
    assert evidence.entity_type == "RefundPolicy"
    assert evidence.metadata["domain"] == "customer_service"
    relations = evidence.metadata["semantic_relations"]
    assert any(item["relation_type"] == "APPLIES_TO" for item in relations)
    assert any(item["relation_type"] == "SUPERSEDES" for item in relations)


def test_customer_service_extraction_is_closed_over_its_ontology() -> None:
    pack = get_domain_pack("customer_service")
    extraction = pack.document_mapper.extract(
        {
            "policy_id": "POL-REFUND-2026-07",
            "title": "七天无理由退货政策",
            "document_type": "refund_policy",
            "product_sku": "SKU-PHONE-A",
            "supersedes": "POL-REFUND-2026-06",
            "content": "商品 SKU-PHONE-A 签收后 7 天内且未拆封可以退货。",
        }
    )
    entity_types = {entity.entity_type for entity in extraction.entities}
    relation_types = {relation.relation_type for relation in extraction.relations}

    assert entity_types <= set(pack.ontology.node_labels)
    assert relation_types <= {relation.name for relation in pack.ontology.relation_types}
    assert "PolicyTerm" in entity_types
    entity_types_by_id = {entity.entity_id: entity.entity_type for entity in extraction.entities}
    relation_specs = {relation.name: relation for relation in pack.ontology.relation_types}
    for relation in extraction.relations:
        spec = relation_specs[relation.relation_type]
        assert entity_types_by_id[relation.source_id] in spec.source_labels
        assert entity_types_by_id[relation.target_id] in spec.target_labels


def test_each_domain_pack_ships_a_grounded_evaluation_resource() -> None:
    for domain_name in domain_pack_names():
        evaluation = load_domain_evaluation(get_domain_pack(domain_name))
        assert evaluation["domain"] == domain_name
        assert any(
            case.get("expected_response_mode") == "grounded_answer" for case in evaluation["cases"]
        )


def test_evidence_contract_rejects_deprecated_recipe_aliases() -> None:
    with pytest.raises(TypeError):
        EvidenceDocument(content="legacy", recipe_id="r1", recipe_name="Mapo tofu")

    evidence = EvidenceDocument(
        content="canonical",
        entity_id="r1",
        entity_name="Mapo tofu",
        domain_graph_evidence={"kind": "recipe"},
    )
    assert "recipe_id" not in evidence.to_dict()
    assert "recipe_name" not in evidence.to_dict()
    assert "recipe_graph_evidence" not in evidence.to_dict()


def test_evidence_processing_retires_generic_recipe_compatibility_exports() -> None:
    import rag_modules.evidence_processing as evidence_processing
    from rag_modules.evidence_processing.models import AggregatedEvidence

    assert not hasattr(evidence_processing, "RecipeEvidence")
    assert not hasattr(evidence_processing, "aggregate_recipe_evidence")
    assert not hasattr(evidence_processing, "aggregate_recipe_evidence_from_documents")
    aggregate = AggregatedEvidence(entity_id="r1", entity_name="Mapo tofu")
    assert not hasattr(aggregate, "recipe_id")
    assert not hasattr(aggregate, "recipe_name")
    assert not hasattr(aggregate, "full_recipe_doc")


def test_customer_service_domain_selects_its_policy_and_citation_label() -> None:
    config = load_config(source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "customer_service"}))
    bundle_path = (
        Path("rag_modules/query_policy/resources") / config.query_understanding.policy.bundle
    )
    bundle = load_policy_bundle(bundle_path)
    builder = AnswerEvidenceBuilder(citation_label=bundle.generation.citation_label)
    package = builder.build(
        "订单 CS-1001 现在是什么状态？",
        [
            EvidenceDocument(
                content="订单 CS-1001 已发货。",
                entity_id="CS-1001",
                entity_name="订单 CS-1001",
                entity_type="Order",
                source="knowledge_base",
                score=0.98,
                metadata={"domain": "customer_service", "status": "已发货"},
            )
        ],
    )

    assert config.domain.name == "customer_service"
    assert bundle.metadata.bundle_name == "customer-service-v1"
    assert "HAS_REFUND_RULE" in bundle.relations.graph_relation_types
    assert "菜谱" not in bundle.prompts.query_planner
    assert "食材" not in bundle.prompts.query_planner
    assert package.items[0].citation == "客服证据 1"
    assert package.items[0].entity_name == "订单 CS-1001"


def test_customer_service_registry_contains_only_policy_owned_relations() -> None:
    bundle = load_policy_bundle(Path("rag_modules/query_policy/resources/customer-service-v1"))
    registry = QueryUnderstandingRegistry.from_policy_bundle(bundle)

    assert set(registry.graph_relation_types) == set(bundle.relations.graph_relation_types)
    assert "REQUIRES" not in registry.graph_relation_types
    assert "CONTAINS_STEP" not in registry.graph_relation_types


def test_public_citation_projection_is_domain_owned_and_keeps_recipe_compatibility() -> None:
    customer = PublicEvidenceDocumentResponseModel.from_dto(
        EvidenceDocument(
            content="订单 CS-1001 已发货。",
            entity_id="CS-1001",
            entity_name="订单 CS-1001",
            entity_type="Order",
            matched_terms=["CS-1001", "已发货"],
            metadata={
                "domain": "customer_service",
                "document_type": "order",
                "status": "已发货",
                "internal_note": "never public",
            },
        )
    )
    recipe = PublicEvidenceDocumentResponseModel.from_dto(
        EvidenceDocument(
            content="麻婆豆腐使用豆腐和豆瓣酱。",
            entity_id="recipe-1",
            entity_name="麻婆豆腐",
            entity_type="Recipe",
            matched_terms=["豆腐"],
            metadata={"domain": "recipe", "category": "川菜"},
        )
    )

    assert customer.content == ""
    assert customer.entity_id == ""
    assert customer.entity_name == ""
    assert customer.recipe_name == ""
    assert customer.matched_terms == []
    assert customer.attributes == {"document_type": "order", "status": "已发货"}
    assert recipe.content == "麻婆豆腐使用豆腐和豆瓣酱。"
    assert recipe.entity_id == "recipe-1"
    assert recipe.entity_name == "麻婆豆腐"
    assert recipe.recipe_name == "麻婆豆腐"
    assert recipe.matched_terms == ["豆腐"]


def test_public_citation_projection_fails_closed_without_domain_or_recipe_markers() -> None:
    public = PublicEvidenceDocumentResponseModel.from_dto(
        EvidenceDocument(
            content="internal customer record",
            entity_id="customer-1",
            entity_name="Customer One",
            entity_type="Customer",
            matched_terms=["customer-1"],
            metadata={},
        )
    )

    assert public.content == ""
    assert public.entity_id == ""
    assert public.entity_name == ""
    assert public.recipe_name == ""
    assert public.matched_terms == []


def test_recipe_text_document_projects_through_canonical_evidence_type() -> None:
    document = TextDocument(
        content="Mapo tofu uses tofu and chili bean paste.",
        metadata={"recipe_id": "recipe-1", "recipe_name": "Mapo tofu", "matched_terms": ["tofu"]},
    )

    public = PublicEvidenceDocumentResponseModel.from_dto(
        evidence_document_from_text_document(document)
    )

    assert public.content == document.content
    assert public.entity_id == "recipe-1"
    assert public.entity_name == "Mapo tofu"
    assert public.recipe_name == "Mapo tofu"
    assert public.matched_terms == ["tofu"]


def test_customer_service_build_does_not_run_recipe_semantic_writer() -> None:
    config = load_config(source=EnvConfigSource(environ={"GRAPH_RAG_DOMAIN": "customer_service"}))
    service = SemanticGraphSchemaSyncService(config, neo4j_manager=object())

    result = service.sync_from_documents([object()])

    assert result.enabled is False


def test_customer_service_graph_evidence_keeps_customer_entity_identity() -> None:
    builder = GraphEvidenceBuilder(
        domain_name="customer_service",
        primary_labels=("Order", "RefundPolicy"),
        semantic_node_labels=(),
    )
    path = GraphPath(
        nodes=[
            GraphNodeSnapshot(node_id="CS-1001", name="Order CS-1001", labels=("Order",)),
            GraphNodeSnapshot(
                node_id="POL-REFUND-2026-07",
                name="Refund policy 2026.07",
                labels=("RefundPolicy",),
            ),
        ],
        relationships=[
            GraphRelationshipSnapshot(
                relation_type="GOVERNED_BY",
                start_node_id="CS-1001",
                end_node_id="POL-REFUND-2026-07",
            )
        ],
        path_length=1,
        relevance_score=0.9,
        path_type="entity_relation",
    )

    [evidence] = builder.paths_to_evidence([path], "refund policy")

    assert evidence.entity_id == "CS-1001"
    assert evidence.entity_name == "Order CS-1001"
    assert evidence.metadata["domain"] == "customer_service"
    assert "recipe_name" not in evidence.metadata
    assert "recipe_graph_evidence" not in evidence.metadata
    assert evidence.domain_graph_evidence["relationships"][0]["type"] == "GOVERNED_BY"


def test_customer_service_subgraph_evidence_has_no_recipe_metadata() -> None:
    builder = GraphEvidenceBuilder(
        domain_name="customer_service",
        primary_labels=("Order", "RefundPolicy"),
        semantic_node_labels=(),
    )
    subgraph = KnowledgeSubgraph(
        central_nodes=[
            GraphNodeSnapshot(node_id="CS-1001", name="订单 CS-1001", labels=("Order",))
        ],
        connected_nodes=[
            GraphNodeSnapshot(
                node_id="POL-REFUND-2026-07",
                name="七天无理由退货政策",
                labels=("RefundPolicy",),
            )
        ],
        relationships=[
            GraphRelationshipSnapshot(
                relation_type="GOVERNED_BY",
                start_node_id="CS-1001",
                end_node_id="POL-REFUND-2026-07",
            )
        ],
        graph_metrics={"density": 1.0},
    )

    [evidence] = builder.subgraph_to_evidence(
        subgraph,
        ["订单受退款政策约束"],
        "订单退款政策",
    )

    assert evidence.entity_id == "CS-1001"
    assert evidence.entity_name == "订单 CS-1001"
    assert evidence.metadata["entity_ids"] == ["CS-1001", "POL-REFUND-2026-07"]
    assert evidence.metadata["entity_names"] == ["订单 CS-1001", "七天无理由退货政策"]
    assert not any(key.startswith("recipe") for key in evidence.metadata)
