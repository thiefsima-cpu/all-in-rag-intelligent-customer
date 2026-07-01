from __future__ import annotations

import unittest

from rag_modules.build_pipeline.stats_presenter import KnowledgeBaseStatsPresenter


class _FakeRuntimeStatsAccess:
    def __init__(self) -> None:
        self.graph_stats_calls = 0
        self.vector_stats_calls = 0
        self.route_stats_calls = 0

    def get_graph_data_stats(self, data_module):
        self.graph_stats_calls += 1
        return dict(data_module.stats)

    def get_vector_collection_stats(self, index_module):
        self.vector_stats_calls += 1
        return dict(index_module.stats)

    def get_route_stats(self, query_router):
        self.route_stats_calls += 1
        return dict(query_router.stats if query_router is not None else {})


class KnowledgeBaseStatsPresenterTests(unittest.TestCase):
    def test_show_emits_stats_lines_from_runtime_stats_port(self) -> None:
        stats_access = _FakeRuntimeStatsAccess()
        presenter = KnowledgeBaseStatsPresenter(
            runtime_stats_access=stats_access,
            data_module=type(
                "DataModule", (), {"stats": {"total_recipes": 2, "total_chunks": 4}}
            )(),
            index_module=type("IndexModule", (), {"stats": {"row_count": 4}})(),
            query_router=type("QueryRouter", (), {"stats": {"total_queries": 3}})(),
        )
        messages: list[str] = []

        presenter.show(messages.append)

        self.assertEqual(stats_access.graph_stats_calls, 1)
        self.assertEqual(stats_access.vector_stats_calls, 1)
        self.assertEqual(stats_access.route_stats_calls, 1)
        self.assertTrue(any("Recipes: 2" in message for message in messages))
        self.assertTrue(any("Vector rows: 4" in message for message in messages))
        self.assertTrue(any("Routed queries: 3" in message for message in messages))

    def test_vector_row_count_reads_from_runtime_stats_port(self) -> None:
        stats_access = _FakeRuntimeStatsAccess()
        presenter = KnowledgeBaseStatsPresenter(
            runtime_stats_access=stats_access,
            data_module=object(),
            index_module=type("IndexModule", (), {"stats": {"row_count": 7}})(),
        )

        row_count = presenter.vector_row_count()

        self.assertEqual(row_count, 7)
        self.assertEqual(stats_access.vector_stats_calls, 1)


if __name__ == "__main__":
    unittest.main()
