from __future__ import annotations

from rag_modules.runtime import stats_ports
from rag_modules.runtime.stats_adapters import DefaultRuntimeStatsAccess


class _StatsPayload:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> object:
        return dict(self.payload)


class _GraphStatsSource:
    def get_statistics(self) -> object:
        return _StatsPayload({"total_entities": 2})


class _VectorStatsSource:
    def get_collection_stats(self, collection_name: str | None = None) -> object:
        return {"collection_name": collection_name or "recipes", "row_count": 4}


class _RouteStatsSource:
    def get_route_statistics(self) -> object:
        return _StatsPayload({"total_queries": 3})


class _TraceStatsSource:
    def stats(self) -> object:
        return _StatsPayload({"written_events": 5})


def test_runtime_owns_minimal_statistics_source_ports() -> None:
    expected = {
        "GraphStatisticsSourcePort",
        "VectorCollectionStatisticsSourcePort",
        "RouteStatisticsSourcePort",
        "QueryTraceStatisticsSourcePort",
    }

    assert expected <= set(stats_ports.__all__)
    for name in expected:
        assert getattr(stats_ports, name).__module__ == "rag_modules.runtime.stats_ports"


def test_default_runtime_stats_access_coerces_minimal_source_shapes() -> None:
    access = DefaultRuntimeStatsAccess()

    assert access.get_graph_data_stats(_GraphStatsSource()) == {"total_entities": 2}
    assert access.get_vector_collection_stats(_VectorStatsSource()) == {
        "collection_name": "recipes",
        "row_count": 4,
    }
    assert access.get_route_stats(_RouteStatsSource()) == {"total_queries": 3}
    assert access.get_query_trace_stats(_TraceStatsSource()) == {"written_events": 5}
    assert access.get_graph_data_stats(None) == {}
    assert access.get_vector_collection_stats(None) == {}
    assert access.get_route_stats(None) == {}
    assert access.get_query_trace_stats(None) == {}
