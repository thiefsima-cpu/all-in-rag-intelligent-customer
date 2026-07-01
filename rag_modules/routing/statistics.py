"""Routing statistics tracking."""

from __future__ import annotations

from dataclasses import dataclass

from ..runtime import SearchStrategy
from ..runtime.json_types import JsonObject


@dataclass
class RouteStatisticsTracker:
    """Track high-level routing distribution across strategies."""

    traditional_count: int = 0
    graph_rag_count: int = 0
    combined_count: int = 0
    total_queries: int = 0

    def record(self, strategy: SearchStrategy) -> None:
        self.total_queries += 1
        if strategy == SearchStrategy.HYBRID_TRADITIONAL:
            self.traditional_count += 1
        elif strategy == SearchStrategy.GRAPH_RAG:
            self.graph_rag_count += 1
        elif strategy == SearchStrategy.COMBINED:
            self.combined_count += 1

    def to_dict(self) -> JsonObject:
        return {
            "traditional_count": self.traditional_count,
            "graph_rag_count": self.graph_rag_count,
            "combined_count": self.combined_count,
            "total_queries": self.total_queries,
        }

    def summary(self) -> JsonObject:
        payload = self.to_dict()
        total = self.total_queries
        if total == 0:
            return payload
        return {
            **payload,
            "traditional_ratio": self.traditional_count / total,
            "graph_rag_ratio": self.graph_rag_count / total,
            "combined_ratio": self.combined_count / total,
        }
