from __future__ import annotations

from rag_modules.retrieval.adapters.neo4j_fallback_retriever import Neo4jFallbackRetriever


class _Session:
    def __init__(self, entity=None, topic=None, neighbors=None, error=None) -> None:
        self.entity = list(entity or [])
        self.topic = list(topic or [])
        self.neighbors = list(neighbors or [])
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, parameters):
        if self.error:
            raise self.error
        if "fulltext" in query:
            return self.entity
        if "matched_keyword" in query:
            return self.topic
        return self.neighbors


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


def test_entity_search_builds_partial_records_and_coerces_scores() -> None:
    retriever = Neo4jFallbackRetriever(
        driver=_Driver(
            _Session(
                entity=[
                    {
                        "node_id": "r1",
                        "name": "Mapo tofu",
                        "description": "spicy",
                        "labels": ["Recipe", ""],
                        "score": "0.5",
                    },
                    {
                        "node_id": "r2",
                        "name": "",
                        "description": "fallback",
                        "labels": "invalid",
                        "score": object(),
                    },
                ]
            )
        ),
        database="neo4j",
    )

    first, second = retriever.entity_search(["tofu"], 2)

    assert first.score == 0.35
    assert first.metadata["labels"] == ["Recipe"]
    assert second.score == 0.0
    assert second.metadata["labels"] == []


def test_topic_search_includes_optional_fields_and_filters_ingredients() -> None:
    record = {
        "node_id": "r1",
        "name": "Mapo tofu",
        "category": "main",
        "cuisine_type": "Sichuan",
        "difficulty": 2,
        "ingredients": ["tofu", "", "pepper", "oil"],
        "matched_keyword": "Sichuan",
    }
    retriever = Neo4jFallbackRetriever(driver=_Driver(_Session(topic=[record])), database="neo4j")

    [document] = retriever.topic_search(["Sichuan"], 1)

    assert document.score == 0.75
    assert document.matched_terms == ["Sichuan"]
    assert "tofu" in document.content


def test_topic_search_omits_empty_optional_fields_and_invalid_ingredients() -> None:
    record = {
        "node_id": "r1",
        "name": "Recipe",
        "category": "",
        "cuisine_type": "",
        "difficulty": 0,
        "ingredients": "invalid",
        "matched_keyword": "",
    }
    retriever = Neo4jFallbackRetriever(driver=_Driver(_Session(topic=[record])), database="neo4j")

    [document] = retriever.topic_search(["x"], 1)

    assert document.recipe_name == "Recipe"
    assert document.matched_terms == []


def test_guards_neighbors_and_failures_return_empty() -> None:
    no_driver = Neo4jFallbackRetriever(driver=None, database="neo4j")
    assert no_driver.entity_search([], 1) == []
    assert no_driver.entity_search(["x"], 0) == []
    assert no_driver.topic_search(["x"], 0) == []
    assert no_driver.node_neighbors("") == []

    success = Neo4jFallbackRetriever(
        driver=_Driver(_Session(neighbors=[{"name": "Pepper"}, {"name": ""}])),
        database="neo4j",
    )
    assert success.node_neighbors("r1") == ["Pepper"]

    failing = Neo4jFallbackRetriever(
        driver=_Driver(_Session(error=RuntimeError("down"))), database="neo4j"
    )
    assert failing.entity_search(["x"], 1) == []
    assert failing.topic_search(["x"], 1) == []
    assert failing.node_neighbors("r1") == []
