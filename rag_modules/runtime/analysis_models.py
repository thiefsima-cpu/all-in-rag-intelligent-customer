"""Query analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict

from ..query_understanding import QuerySemanticProfile


class SearchStrategy(Enum):
    HYBRID_TRADITIONAL = "hybrid_traditional"
    GRAPH_RAG = "graph_rag"
    COMBINED = "combined"


@dataclass
class QueryAnalysis:
    query_complexity: float = 0.0
    relationship_intensity: float = 0.0
    reasoning_required: bool = False
    entity_count: int = 0
    recommended_strategy: SearchStrategy = SearchStrategy.HYBRID_TRADITIONAL
    confidence: float = 0.0
    reasoning: str = ""
    semantic_profile: QuerySemanticProfile = field(default_factory=QuerySemanticProfile)

    def __post_init__(self) -> None:
        if isinstance(self.recommended_strategy, SearchStrategy):
            strategy = self.recommended_strategy
        else:
            try:
                strategy = SearchStrategy(
                    str(self.recommended_strategy or SearchStrategy.HYBRID_TRADITIONAL.value)
                )
            except ValueError:
                strategy = SearchStrategy.HYBRID_TRADITIONAL
        self.recommended_strategy = strategy
        self.query_complexity = float(self.query_complexity or 0.0)
        self.relationship_intensity = float(self.relationship_intensity or 0.0)
        self.reasoning_required = bool(self.reasoning_required)
        self.entity_count = max(0, int(self.entity_count or 0))
        self.confidence = float(self.confidence or 0.0)
        self.reasoning = str(self.reasoning or "")
        if isinstance(self.semantic_profile, dict):
            self.semantic_profile = QuerySemanticProfile.from_dict(self.semantic_profile)
        elif not isinstance(self.semantic_profile, QuerySemanticProfile):
            self.semantic_profile = QuerySemanticProfile()

    @property
    def strategy_name(self) -> str:
        return self.recommended_strategy.value

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "QueryAnalysis":
        payload = dict(data or {})
        return cls(
            query_complexity=payload.get("query_complexity", 0.0),
            relationship_intensity=payload.get("relationship_intensity", 0.0),
            reasoning_required=payload.get("reasoning_required", False),
            entity_count=payload.get("entity_count", 0),
            recommended_strategy=payload.get(
                "recommended_strategy",
                SearchStrategy.HYBRID_TRADITIONAL.value,
            ),
            confidence=payload.get("confidence", 0.0),
            reasoning=payload.get("reasoning", ""),
            semantic_profile=payload.get("semantic_profile") or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_complexity": self.query_complexity,
            "relationship_intensity": self.relationship_intensity,
            "reasoning_required": self.reasoning_required,
            "entity_count": self.entity_count,
            "recommended_strategy": self.strategy_name,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "semantic_profile": self.semantic_profile.to_dict(),
        }


def analysis_payload(analysis: Any) -> Dict[str, Any]:
    if isinstance(analysis, QueryAnalysis):
        payload = analysis.to_dict()
    elif isinstance(analysis, dict):
        payload = dict(analysis)
    elif analysis is None:
        payload = {}
    else:
        payload = {
            "query_complexity": getattr(analysis, "query_complexity", 0.0),
            "relationship_intensity": getattr(analysis, "relationship_intensity", 0.0),
            "reasoning_required": getattr(analysis, "reasoning_required", False),
            "entity_count": getattr(analysis, "entity_count", 0),
            "recommended_strategy": getattr(
                getattr(analysis, "recommended_strategy", None),
                "value",
                "",
            ),
            "confidence": getattr(analysis, "confidence", 0.0),
            "reasoning": getattr(analysis, "reasoning", ""),
            "semantic_profile": getattr(analysis, "semantic_profile", {}),
        }

    strategy = payload.get("recommended_strategy")
    if hasattr(strategy, "value"):
        payload["recommended_strategy"] = strategy.value
    elif strategy is None:
        payload["recommended_strategy"] = ""
    else:
        payload["recommended_strategy"] = str(strategy)
    return QueryAnalysis.from_dict(payload).to_dict()


def ensure_query_analysis(analysis: Any) -> QueryAnalysis:
    if isinstance(analysis, QueryAnalysis):
        return analysis
    if analysis is None:
        return QueryAnalysis()
    if isinstance(analysis, dict):
        return QueryAnalysis.from_dict(analysis)
    return QueryAnalysis.from_dict(analysis_payload(analysis))


def analysis_value(analysis: Any, key: str, default: Any = None) -> Any:
    return analysis_payload(analysis).get(key, default)


def analysis_strategy_name(analysis: Any) -> str:
    return str(analysis_value(analysis, "recommended_strategy", "") or "")
