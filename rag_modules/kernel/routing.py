"""Pure routing strategies and statistics."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum

from .json_types import JsonObject


class SearchStrategy(str, Enum):
    HYBRID_TRADITIONAL = "hybrid_traditional"
    GRAPH_RAG = "graph_rag"
    COMBINED = "combined"


@dataclass
class RouteStatistics:
    """Track high-level routing distribution across strategies."""

    traditional_count: int = 0
    graph_rag_count: int = 0
    combined_count: int = 0
    total_queries: int = 0
    _lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
        compare=False,
    )

    def record(self, strategy: SearchStrategy) -> None:
        with self._lock:
            self.total_queries += 1
            if strategy == SearchStrategy.HYBRID_TRADITIONAL:
                self.traditional_count += 1
            elif strategy == SearchStrategy.GRAPH_RAG:
                self.graph_rag_count += 1
            elif strategy == SearchStrategy.COMBINED:
                self.combined_count += 1

    def to_dict(self) -> JsonObject:
        traditional, graph_rag, combined, total = self._snapshot()
        return {
            "traditional_count": traditional,
            "graph_rag_count": graph_rag,
            "combined_count": combined,
            "total_queries": total,
        }

    def _snapshot(self) -> tuple[int, int, int, int]:
        with self._lock:
            return (
                self.traditional_count,
                self.graph_rag_count,
                self.combined_count,
                self.total_queries,
            )

    def summary(self) -> JsonObject:
        traditional, graph_rag, combined, total = self._snapshot()
        payload: JsonObject = {
            "traditional_count": traditional,
            "graph_rag_count": graph_rag,
            "combined_count": combined,
            "total_queries": total,
        }
        if total == 0:
            return payload
        return {
            **payload,
            "traditional_ratio": traditional / total,
            "graph_rag_ratio": graph_rag / total,
            "combined_ratio": combined / total,
        }


__all__ = ["RouteStatistics", "SearchStrategy"]
