"""Cross-stage workflow contracts for query understanding, routing, and answer generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from langchain_core.documents import Document

from ..contracts import EvidenceDocument, QueryPlan, QuerySemanticProfile
from ..domain.shared.query_constraints import QueryConstraints
from .analysis_models import QueryAnalysis, SearchStrategy, ensure_query_analysis
from .json_types import JsonObject, coerce_json_object
from .retrieval_models import RetrievalOutcome


def _search_strategy(value: str) -> SearchStrategy:
    try:
        return SearchStrategy(str(value or SearchStrategy.HYBRID_TRADITIONAL.value))
    except ValueError:
        return SearchStrategy.HYBRID_TRADITIONAL


@dataclass
class QueryUnderstandingSnapshot:
    """Stable query-understanding contract shared across router and generation."""

    query: str = ""
    query_plan: QueryPlan = field(default_factory=lambda: QueryPlan(query=""))
    analysis: QueryAnalysis = field(default_factory=QueryAnalysis)
    constraints: QueryConstraints = field(default_factory=QueryConstraints)
    semantic_profile: QuerySemanticProfile = field(default_factory=QuerySemanticProfile)
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.query_plan, dict):
            query = str(self.query or self.query_plan.get("query") or "")
            self.query_plan = QueryPlan.from_dict(query, coerce_json_object(self.query_plan))
        elif not isinstance(self.query_plan, QueryPlan):
            self.query_plan = QueryPlan(query=str(self.query or ""))
        self.query = str(self.query or self.query_plan.query or "")
        self.analysis = ensure_query_analysis(self.analysis)
        if isinstance(self.constraints, dict):
            self.constraints = QueryConstraints.from_dict(coerce_json_object(self.constraints))
        elif not isinstance(self.constraints, QueryConstraints):
            self.constraints = QueryConstraints()
        if isinstance(self.semantic_profile, dict):
            self.semantic_profile = QuerySemanticProfile.from_dict(
                coerce_json_object(self.semantic_profile)
            )
        elif not isinstance(self.semantic_profile, QuerySemanticProfile):
            self.semantic_profile = QuerySemanticProfile()
        if not self.semantic_profile.query and getattr(self.query_plan, "semantic_profile", None):
            self.semantic_profile = self.query_plan.semantic_profile
        if not self.constraints.has_constraints() and getattr(self.query_plan, "constraints", None):
            self.constraints = self.query_plan.constraints
        self.metadata = coerce_json_object(self.metadata)

    @classmethod
    def from_plan(
        cls,
        plan: QueryPlan,
        *,
        metadata: JsonObject | None = None,
    ) -> "QueryUnderstandingSnapshot":
        analysis = QueryAnalysis(
            query_complexity=plan.complexity,
            relationship_intensity=plan.relationship_intensity,
            reasoning_required=plan.reasoning_required,
            entity_count=plan.entity_count,
            recommended_strategy=_search_strategy(plan.strategy),
            confidence=plan.confidence,
            reasoning=plan.reasoning,
            semantic_profile=plan.semantic_profile,
        )
        return cls(
            query=plan.query,
            query_plan=plan,
            analysis=analysis,
            constraints=plan.constraints,
            semantic_profile=plan.semantic_profile,
            metadata=coerce_json_object(metadata),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryUnderstandingSnapshot":
        payload = dict(data or {})
        query = str(payload.get("query") or "")
        query_plan_payload = payload.get("query_plan")
        query_plan = (
            query_plan_payload
            if isinstance(query_plan_payload, QueryPlan)
            else QueryPlan.from_dict(query, coerce_json_object(query_plan_payload))
        )
        return cls(
            query=query,
            query_plan=query_plan,
            analysis=ensure_query_analysis(payload.get("analysis")),
            constraints=QueryConstraints.from_dict(coerce_json_object(payload.get("constraints"))),
            semantic_profile=QuerySemanticProfile.from_dict(
                coerce_json_object(payload.get("semantic_profile"))
            ),
            metadata=coerce_json_object(payload.get("metadata")),
        )

    def to_dict(self) -> JsonObject:
        return {
            "query": self.query,
            "query_plan": self.query_plan.to_dict(),
            "analysis": self.analysis.to_dict(),
            "constraints": self.constraints.to_dict(),
            "semantic_profile": self.semantic_profile.to_dict(),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class RouteResolution:
    """Stable router output carrying both understanding and retrieval state."""

    understanding: QueryUnderstandingSnapshot = field(default_factory=QueryUnderstandingSnapshot)
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.understanding, dict):
            self.understanding = QueryUnderstandingSnapshot.from_dict(self.understanding)
        elif not isinstance(self.understanding, QueryUnderstandingSnapshot):
            self.understanding = QueryUnderstandingSnapshot()
        if isinstance(self.retrieval, dict):
            self.retrieval = RetrievalOutcome.from_dict(self.retrieval)
        elif not isinstance(self.retrieval, RetrievalOutcome):
            self.retrieval = RetrievalOutcome()
        self.metadata = coerce_json_object(self.metadata)

    @property
    def query(self) -> str:
        return str(self.understanding.query or self.retrieval.query or "")

    @property
    def analysis(self) -> QueryAnalysis:
        return self.understanding.analysis

    @property
    def evidence_documents(self) -> list[EvidenceDocument]:
        return list(self.retrieval.evidence_documents or [])

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RouteResolution":
        payload = dict(data or {})
        return cls(
            understanding=QueryUnderstandingSnapshot.from_dict(
                _mapping_or_none(payload.get("understanding"))
            ),
            retrieval=RetrievalOutcome.from_dict(_mapping_or_none(payload.get("retrieval"))),
            metadata=coerce_json_object(payload.get("metadata")),
        )

    def to_dict(self) -> JsonObject:
        return {
            "understanding": self.understanding.to_dict(),
            "retrieval": self.retrieval.to_dict(),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class AnswerContext:
    """Canonical generation input contract for grounded answer generation."""

    question: str = ""
    retrieval: RetrievalOutcome = field(default_factory=RetrievalOutcome)
    analysis: QueryAnalysis | None = None
    understanding: QueryUnderstandingSnapshot | None = None
    evidence_package: JsonObject = field(default_factory=dict)
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.retrieval, RetrievalOutcome):
            pass
        else:
            self.retrieval = RetrievalOutcome.from_dict(self.retrieval or {})
        if isinstance(self.understanding, dict):
            self.understanding = QueryUnderstandingSnapshot.from_dict(self.understanding)
        elif self.understanding is not None and not isinstance(
            self.understanding,
            QueryUnderstandingSnapshot,
        ):
            self.understanding = QueryUnderstandingSnapshot.from_dict(dict(self.understanding))
        self.analysis = ensure_query_analysis(self.analysis) if self.analysis is not None else None
        if self.analysis is None and self.understanding is not None:
            self.analysis = self.understanding.analysis
        if not self.question:
            self.question = str(
                self.retrieval.query
                or (self.understanding.query if self.understanding else "")
                or ""
            )
        self.evidence_package = coerce_json_object(self.evidence_package)
        self.metadata = coerce_json_object(self.metadata)

    @classmethod
    def from_route_resolution(
        cls,
        resolution: RouteResolution,
        *,
        evidence_package: object = None,
        metadata: JsonObject | None = None,
    ) -> "AnswerContext":
        return cls(
            question=resolution.query,
            retrieval=resolution.retrieval,
            analysis=resolution.analysis,
            understanding=resolution.understanding,
            evidence_package=coerce_json_object(evidence_package),
            metadata=metadata or resolution.metadata,
        )

    @property
    def documents(self) -> list[Document]:
        return self.retrieval.documents

    @property
    def evidence_documents(self) -> list[EvidenceDocument]:
        return list(self.retrieval.evidence_documents)

    @property
    def has_evidence_package(self) -> bool:
        items = self.evidence_package.get("items")
        return bool(items)

    def with_evidence_package(self, payload: object) -> "AnswerContext":
        return replace(self, evidence_package=coerce_json_object(payload))

    def to_dict(self) -> JsonObject:
        return {
            "question": self.question,
            "retrieval": self.retrieval.to_dict(),
            "analysis": self.analysis.to_dict() if self.analysis else {},
            "understanding": self.understanding.to_dict() if self.understanding else {},
            "evidence_package": dict(self.evidence_package or {}),
            "metadata": dict(self.metadata or {}),
        }


__all__ = [
    "AnswerContext",
    "QueryUnderstandingSnapshot",
    "RouteResolution",
]


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
