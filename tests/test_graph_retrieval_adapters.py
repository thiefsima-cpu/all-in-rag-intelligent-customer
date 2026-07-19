from __future__ import annotations

from dataclasses import dataclass, field

from rag_modules.graph.entity_linker import EntityLinkContext, EntityLinker
from rag_modules.interfaces.api.answer_public_models import PublicEvidenceDocumentResponseModel
from rag_modules.retrieval.adapters.graph_kv_retriever import GraphKVRetriever


@dataclass
class _Entity:
    entity_name: str
    entity_type: str = "Recipe"
    index_keys: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    value_content: str = "content"


@dataclass
class _Relation:
    relation_id: str
    relation_type: str = "RELATED"
    source_entity: str = "r1"
    target_entity: str = "i1"
    index_keys: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    value_content: str = "relation"


class _Index:
    def __init__(self, entities=(), relations=()) -> None:
        self.entities = list(entities)
        self.relations = list(relations)

    def get_entities_by_key(self, key):
        return self.entities

    def get_relations_by_key(self, key):
        return self.relations


class _LinkSession:
    def __init__(self, records=(), error: Exception | None = None) -> None:
        self.records = list(records)
        self.error = error
        self.last_query = ""
        self.last_kwargs: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, **kwargs):
        self.last_query = str(query)
        self.last_kwargs = dict(kwargs)
        if self.error:
            raise self.error
        return self.records


class _LinkDriver:
    def __init__(self, session: _LinkSession) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


def test_graph_kv_guards_scores_deduplicates_and_interleaves() -> None:
    assert GraphKVRetriever(None).search(["tofu"]) == []
    assert GraphKVRetriever(_Index()).entity_search([]) == []

    index = _Index(
        entities=[
            _Entity("tofu", index_keys=("tofu",), metadata={"node_id": "r1", "degree": 12}),
            _Entity("tofu", index_keys=("tofu",)),
            _Entity("unmatched", index_keys=("other",), metadata={"degree": "bad"}),
        ],
        relations=[
            _Relation(
                "rel-1",
                index_keys=("tofu",),
                metadata={"source_name": "Mapo tofu"},
            ),
            _Relation("rel-1", index_keys=("tofu",)),
        ],
    )

    results = GraphKVRetriever(index).search(["tofu"], top_k=2)

    assert [document.retrieval_level for document in results] == ["entity", "topic"]
    assert results[0].score <= 1.0
    assert results[1].recipe_name == "Mapo tofu"


def test_graph_kv_skips_nonmatching_entries_and_limits_results() -> None:
    index = _Index(
        entities=[_Entity("different", index_keys=("other",))],
        relations=[_Relation("rel", index_keys=("other",))],
    )

    assert GraphKVRetriever(index).entity_search(["tofu"], top_k=1) == []
    assert GraphKVRetriever(index).topic_search(["tofu"], top_k=1) == []


def test_customer_graph_kv_evidence_keeps_domain_and_public_projection_redacts() -> None:
    index = _Index(
        entities=[
            _Entity(
                "订单 CS-1001",
                entity_type="Order",
                index_keys=("CS-1001",),
                metadata={
                    "node_id": "CS-1001",
                    "domain": "customer_service",
                    "properties": {"domain": "customer_service"},
                },
                value_content="订单 CS-1001 已发货。",
            )
        ],
        relations=[
            _Relation(
                "rel-1",
                relation_type="GOVERNED_BY",
                source_entity="CS-1001",
                target_entity="POL-REFUND-2026-07",
                index_keys=("GOVERNED_BY",),
                metadata={
                    "source_name": "订单 CS-1001",
                    "target_name": "七天无理由退货政策",
                    "domain": "customer_service",
                },
                value_content="订单受退款政策约束。",
            )
        ],
    )

    entity_doc = GraphKVRetriever(index).entity_search(["CS-1001"], top_k=1)[0]
    relation_doc = GraphKVRetriever(index).topic_search(["GOVERNED_BY"], top_k=1)[0]

    assert entity_doc.metadata["domain"] == "customer_service"
    assert relation_doc.metadata["domain"] == "customer_service"
    for document in (entity_doc, relation_doc):
        public = PublicEvidenceDocumentResponseModel.from_dto(document)
        assert public.content == ""
        assert public.entity_id == ""
        assert public.entity_name == ""
        assert public.matched_terms == []


def test_entity_linker_guards_empty_and_returns_unresolved_without_driver() -> None:
    linker = EntityLinker(driver=None, database="neo4j")

    assert linker.link_many([]) == []
    unresolved = linker.link_many([" tofu ", "tofu", ""])

    assert len(unresolved) == 1
    assert unresolved[0].resolved_value == "tofu"
    assert unresolved[0].confidence == 0.0


def test_entity_linker_prefers_exact_contextual_candidates_and_deduplicates() -> None:
    records = [
        {
            "node_id": "tofu",
            "name": "Tofu",
            "category": "ingredient",
            "labels": ["Ingredient"],
            "match_score": 1.0,
            "degree": 200,
        },
        {
            "node_id": "tofu",
            "name": "Tofu duplicate",
            "category": "ingredient",
            "labels": ["Ingredient"],
            "match_score": 0.9,
            "degree": 1,
        },
        {
            "node_id": "recipe-1",
            "name": "Tofu",
            "category": "main",
            "labels": ["Recipe"],
            "match_score": 0.95,
            "degree": 10,
        },
    ]
    linker = EntityLinker(driver=_LinkDriver(_LinkSession(records)), database="neo4j")
    context = EntityLinkContext(query_type="entity_relation", entity_role="source")

    linked = linker.link_many(["tofu"], context=context)

    assert linked[0].node_id == "tofu"
    assert linked[0].match_reason == "node_id"
    assert len({candidate.node_id for candidate in linked}) == len(linked)


def test_entity_linker_uses_domain_ontology_lookup_fields_and_labels() -> None:
    session = _LinkSession(
        [
            {
                "node_id": "POL-REFUND-2026-07",
                "name": "Refund policy 2026.07",
                "category": "",
                "labels": ["RefundPolicy"],
                "match_score": 0.95,
                "degree": 1,
            }
        ]
    )
    linker = EntityLinker(
        driver=_LinkDriver(session),
        database="neo4j",
        domain_name="customer_service",
        lookup_fields=("policy_id", "version", "title"),
        allowed_labels=("RefundPolicy", "ServicePolicy"),
    )

    [linked] = linker.link_many(["2026.07"])

    assert linked.node_id == "POL-REFUND-2026-07"
    assert session.last_kwargs["lookup_fields"] == ["policy_id", "version", "title"]
    assert session.last_kwargs["allowed_labels"] == ["RefundPolicy", "ServicePolicy"]
    assert session.last_kwargs["domain_name"] == "customer_service"
    assert "n[field]" in session.last_query
    assert "label IN labels(n)" in session.last_query
    assert "n.domain = $domain_name" in session.last_query


def test_entity_linker_degrades_driver_failure_to_unresolved_result() -> None:
    linker = EntityLinker(
        driver=_LinkDriver(_LinkSession(error=RuntimeError("neo4j down"))),
        database="neo4j",
    )

    [linked] = linker.link_many(["tofu"])

    assert linked.text == "tofu"
    assert linked.node_id == ""
    assert linked.confidence == 0.0
