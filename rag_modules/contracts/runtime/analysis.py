"""Query analysis contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from ...kernel.json_types import JsonObject, coerce_float, coerce_int, coerce_str
from ...kernel.routing import SearchStrategy
from ..query_semantics import QuerySemanticProfile


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
        if isinstance(self.semantic_profile, Mapping):
            self.semantic_profile = QuerySemanticProfile.from_dict(self.semantic_profile)
        elif not isinstance(self.semantic_profile, QuerySemanticProfile):
            self.semantic_profile = QuerySemanticProfile()

    @property
    def strategy_name(self) -> str:
        return self.recommended_strategy.value

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryAnalysis":
        payload = dict(data or {})
        return cls(
            query_complexity=coerce_float(payload.get("query_complexity")),
            relationship_intensity=coerce_float(payload.get("relationship_intensity")),
            reasoning_required=bool(payload.get("reasoning_required")),
            entity_count=coerce_int(payload.get("entity_count")),
            recommended_strategy=_strategy_from(
                payload.get("recommended_strategy", SearchStrategy.HYBRID_TRADITIONAL.value)
            ),
            confidence=coerce_float(payload.get("confidence")),
            reasoning=coerce_str(payload.get("reasoning")),
            semantic_profile=QuerySemanticProfile.from_dict(_profile_payload(payload)),
        )

    def to_dict(self) -> JsonObject:
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


AnalysisMapping = Mapping[str, object]
AnalysisInput = QueryAnalysis | AnalysisMapping | None


def analysis_payload(analysis: object) -> JsonObject:
    if isinstance(analysis, QueryAnalysis):
        payload = analysis.to_dict()
    elif isinstance(analysis, Mapping):
        payload = dict(analysis)
    elif analysis is None:
        payload = {}
    else:
        payload = {}

    strategy = payload.get("recommended_strategy")
    if isinstance(strategy, SearchStrategy):
        payload["recommended_strategy"] = strategy.value
    elif strategy is None:
        payload["recommended_strategy"] = ""
    else:
        payload["recommended_strategy"] = str(strategy)
    return QueryAnalysis.from_dict(payload).to_dict()


def ensure_query_analysis(analysis: object) -> QueryAnalysis:
    if isinstance(analysis, QueryAnalysis):
        return analysis
    if analysis is None:
        return QueryAnalysis()
    if isinstance(analysis, Mapping):
        return QueryAnalysis.from_dict(analysis)
    return QueryAnalysis.from_dict(analysis_payload(analysis))


def ensure_optional_query_analysis(analysis: AnalysisInput) -> QueryAnalysis | None:
    if analysis is None:
        return None
    return ensure_query_analysis(analysis)


def analysis_value(analysis: object, key: str, default: object = None) -> object:
    return analysis_payload(analysis).get(key, default)


def analysis_strategy_name(analysis: object) -> str:
    return str(analysis_value(analysis, "recommended_strategy", "") or "")


def _profile_payload(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    value = payload.get("semantic_profile")
    return value if isinstance(value, Mapping) else None


def _strategy_from(value: object) -> SearchStrategy:
    if isinstance(value, SearchStrategy):
        return value
    try:
        return SearchStrategy(coerce_str(value) or SearchStrategy.HYBRID_TRADITIONAL.value)
    except ValueError:
        return SearchStrategy.HYBRID_TRADITIONAL
