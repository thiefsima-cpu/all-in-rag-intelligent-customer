"""Knowledge-base stats reporting over runtime stats contracts."""

from __future__ import annotations

from typing import Callable, Optional

from ..runtime.stats_ports import RuntimeStatsAccessPort

ProgressCallback = Optional[Callable[[str], None]]


class KnowledgeBaseStatsPresenter:
    """Render build-time knowledge-base stats without coupling to concrete modules."""

    def __init__(
        self,
        *,
        runtime_stats_access: RuntimeStatsAccessPort,
        data_module,
        index_module,
        query_router=None,
    ) -> None:
        self.runtime_stats_access = runtime_stats_access
        self.data_module = data_module
        self.index_module = index_module
        self.query_router = query_router

    def show(self, progress: ProgressCallback = None) -> None:
        stats = self.runtime_stats_access.get_graph_data_stats(self.data_module)
        milvus_stats = self.runtime_stats_access.get_vector_collection_stats(self.index_module)
        route_stats = self.runtime_stats_access.get_route_stats(self.query_router)
        lines = [
            "\nKnowledge base stats:",
            f"   Recipes: {stats.get('total_recipes', 0)}",
            f"   Ingredients: {stats.get('total_ingredients', 0)}",
            f"   Cooking steps: {stats.get('total_cooking_steps', 0)}",
            f"   Documents: {stats.get('total_documents', 0)}",
            f"   Chunks: {stats.get('total_chunks', 0)}",
            f"   Vector rows: {milvus_stats.get('row_count', 0)}",
            f"   Routed queries: {route_stats.get('total_queries', 0)}",
        ]
        categories_payload = stats.get("categories")
        if isinstance(categories_payload, dict):
            categories = list(categories_payload.keys())[:10]
            lines.append(f"   Categories: {', '.join(categories)}")
        for line in lines:
            self._emit(progress, line)

    def vector_row_count(self) -> int:
        stats = self.runtime_stats_access.get_vector_collection_stats(self.index_module)
        return self._int_stat(stats.get("row_count", 0))

    @staticmethod
    def _emit(progress: ProgressCallback, message: str) -> None:
        if progress:
            progress(message)

    @staticmethod
    def _int_stat(value: object) -> int:
        if isinstance(value, (bool, int, float, str)):
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
        return 0


__all__ = ["KnowledgeBaseStatsPresenter"]
