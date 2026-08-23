from __future__ import annotations

from rag_modules.graph.cache_stats import GraphCacheEntityStats, GraphCacheStats
from rag_modules.graph.cache_warmup import (
    GraphCacheWarmupService,
    _int_value,
    _string_tuple,
)


class _Store:
    def __init__(self, cached: GraphCacheStats | None, signature: str = "sig") -> None:
        self.cached = cached
        self.signature = signature
        self.saved: list[GraphCacheStats] = []

    def expected_graph_signature(self) -> str:
        return self.signature

    def load(self) -> GraphCacheStats | None:
        return self.cached

    def save(self, stats: GraphCacheStats) -> GraphCacheStats:
        self.saved.append(stats)
        return stats


class _Session:
    def __init__(self) -> None:
        self.entity_pages = [
            [
                {
                    "node_id": "r1",
                    "node_labels": "Recipe",
                    "name": "Recipe",
                    "category": "main",
                    "degree": "3",
                },
                {
                    "node_id": "i1",
                    "node_labels": ["Ingredient", "Food", ""],
                    "name": "Pepper",
                    "category": None,
                    "degree": "invalid",
                },
            ],
            [],
        ]
        self.calls: list[tuple[str, object]] = []

    def __enter__(self) -> _Session:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def run(self, query: str, params: object = None):
        self.calls.append((query, params))
        if "MATCH (n)" in query:
            return self.entity_pages.pop(0)
        return [
            {"rel_type": "USES", "frequency": 2},
            {"rel_type": None, "frequency": "bad"},
        ]


class _Driver:
    def __init__(self) -> None:
        self.session_obj = _Session()

    def session(self, **kwargs: object) -> _Session:
        return self.session_obj


def test_warm_reuses_matching_cached_stats_and_filters_empty_entity_ids() -> None:
    cached = GraphCacheStats(
        graph_signature="sig",
        entities=[
            GraphCacheEntityStats(node_id="r1", labels=("Recipe",), name="Recipe", degree=2),
            GraphCacheEntityStats(node_id="", name="ignored"),
        ],
        relation_frequencies={"USES": 4},
    )
    store = _Store(cached)

    result = GraphCacheWarmupService(store).warm(_Driver(), database_name="neo4j")

    assert result.stats is cached
    assert result.entity_cache == {
        "r1": {"labels": ["Recipe"], "name": "Recipe", "category": "", "degree": 2}
    }
    assert result.relation_cache == {"USES": 4}
    assert store.saved == []


def test_warm_rebuilds_stale_cache_with_paged_entities_and_relations() -> None:
    stale = GraphCacheStats(graph_signature="old", entities=[GraphCacheEntityStats(node_id="old")])
    store = _Store(stale, signature="new")
    driver = _Driver()

    result = GraphCacheWarmupService(
        store,
        domain_name="recipe",
        allowed_node_labels=("Recipe", "Ingredient", "CookingStep", "Category"),
        allow_domainless_graph_records=True,
    ).warm(driver, database_name="neo4j")

    assert result.stats.graph_signature == "new"
    assert [item.node_id for item in result.stats.entities] == ["r1", "i1"]
    assert result.stats.entities[0].degree == 3
    assert result.stats.relation_frequencies == {"USES": 2, "": 0}
    assert result.stats.page_size == 500
    assert store.saved == [result.stats]
    expected_scope = {
        "domain_name": "recipe",
        "allowed_node_labels": ["Recipe", "Ingredient", "CookingStep", "Category"],
    }
    assert driver.session_obj.calls[0][1] == {
        "after_node_id": "",
        "limit": 500,
        **expected_scope,
    }
    assert driver.session_obj.calls[1][1] == {
        "after_node_id": "i1",
        "limit": 500,
        **expected_scope,
    }
    assert "n.domain = $domain_name" in driver.session_obj.calls[0][0]
    assert "n.domain IS NULL" in driver.session_obj.calls[0][0]


def test_warmup_coercion_helpers_cover_strings_sequences_and_invalid_values() -> None:
    assert _string_tuple("Recipe") == ("Recipe",)
    assert _string_tuple(" ") == ()
    assert _string_tuple(["Recipe", "", 2]) == ("Recipe", "2")
    assert _string_tuple({"not": "a sequence"}) == ()
    assert _int_value(3.5) == 3
    assert _int_value("bad") == 0
    assert _int_value({"bad": True}) == 0


def test_customer_service_warmup_rebuilds_and_filters_cache_by_domain() -> None:
    cached = GraphCacheStats(
        graph_signature="sig",
        domain_name="recipe",
        entities=[GraphCacheEntityStats(node_id="recipe-1")],
    )
    store = _Store(cached)
    driver = _Driver()

    result = GraphCacheWarmupService(store, domain_name="customer_service").warm(
        driver,
        database_name="neo4j",
    )

    assert result.stats.domain_name == "customer_service"
    entity_query, entity_params = driver.session_obj.calls[0]
    assert "n.domain = $domain_name" in entity_query
    assert "neighbor.domain = $domain_name" in entity_query
    assert entity_params == {
        "after_node_id": "",
        "limit": 500,
        "domain_name": "customer_service",
    }
    relation_query, relation_params = driver.session_obj.calls[-1]
    assert "source.domain = $domain_name" in relation_query
    assert "target.domain = $domain_name" in relation_query
    assert relation_params == {"domain_name": "customer_service"}
