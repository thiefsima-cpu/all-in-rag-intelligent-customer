from __future__ import annotations

from dataclasses import dataclass, field

from rag_modules.graph.entity_linker import EntityLinkContext, EntityLinker
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

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, **kwargs):
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


def test_entity_linker_degrades_driver_failure_to_unresolved_result() -> None:
    linker = EntityLinker(
        driver=_LinkDriver(_LinkSession(error=RuntimeError("neo4j down"))),
        database="neo4j",
    )

    [linked] = linker.link_many(["tofu"])

    assert linked.text == "tofu"
    assert linked.node_id == ""
    assert linked.confidence == 0.0
