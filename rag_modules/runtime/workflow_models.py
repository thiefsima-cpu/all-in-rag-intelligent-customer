"""Cross-stage workflow contracts for query understanding, routing, and answer generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List

from langchain_core.documents import Document

from ..domain.shared.query_constraints import QueryConstraints
from ..query_understanding import QueryPlan, QuerySemanticProfile
from ..retrieval.contracts import EvidenceDocument
from .analysis_models import QueryAnalysis, SearchStrategy, ensure_query_analysis
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
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.query_plan, dict):
            query = str(self.query or self.query_plan.get("query") or "")
            self.query_plan = QueryPlan.from_dict(query, self.query_plan)
        elif not isinstance(self.query_plan, QueryPlan):
            self.query_plan = QueryPlan(query=str(self.query or ""))
        self.query = str(self.query or self.query_plan.query or "")
        self.analysis = ensure_query_analysis(self.analysis)
        if isinstance(self.constraints, dict):
            self.constraints = QueryConstraints.from_dict(self.constraints)
        elif not isinstance(self.constraints, QueryConstraints):
            self.constraints = QueryConstraints()
        if isinstance(self.semantic_profile, dict):
            self.semantic_profile = QuerySemanticProfile.from_dict(self.semantic_profile)
        elif not isinstance(self.semantic_profile, QuerySemanticProfile):
            self.semantic_profile = QuerySemanticProfile()
        if not self.semantic_profile.query and getattr(self.query_plan, "semantic_profile", None):
            self.semantic_profile = self.query_plan.semantic_profile
        if not self.constraints.has_constraints() and getattr(self.query_plan, "constraints", None):
            self.constraints = self.query_plan.constraints
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_plan(
        cls,
        plan: QueryPlan,
        *,
        metadata: Dict[str, Any] | None = None,
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
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "QueryUnderstandingSnapshot":
        payload = dict(data or {})
        query = str(payload.get("query") or "")
        query_plan_payload = payload.get("query_plan")
        query_plan = (
            query_plan_payload
            if isinstance(query_plan_payload, QueryPlan)
            else QueryPlan.from_dict(query, dict(query_plan_payload or {}))
        )
        return cls(
            query=query,
            query_plan=query_plan,
            analysis=ensure_query_analysis(payload.get("analysis")),
            constraints=QueryConstraints.from_dict(dict(payload.get("constraints") or {})),
            semantic_profile=QuerySemanticProfile.from_dict(payload.get("semantic_profile")),
            metadata=payload.get("metadata") or {},
        )

    def to_dict(self) -> Dict[str, Any]:
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
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.understanding, dict):
            self.understanding = QueryUnderstandingSnapshot.from_dict(self.understanding)
        elif not isinstance(self.understanding, QueryUnderstandingSnapshot):
            self.understanding = QueryUnderstandingSnapshot()
        if isinstance(self.retrieval, dict):
            self.retrieval = RetrievalOutcome.from_dict(self.retrieval)
        elif not isinstance(self.retrieval, RetrievalOutcome):
            self.retrieval = RetrievalOutcome()
        self.metadata = dict(self.metadata or {})

    @property
    def query(self) -> str:
        return str(self.understanding.query or self.retrieval.query or "")

    @property
    def analysis(self) -> QueryAnalysis:
        return self.understanding.analysis

    @property
    def evidence_documents(self) -> List[EvidenceDocument]:
        return list(self.retrieval.evidence_documents or [])

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "RouteResolution":
        payload = dict(data or {})
        return cls(
            understanding=QueryUnderstandingSnapshot.from_dict(payload.get("understanding")),
            retrieval=RetrievalOutcome.from_dict(payload.get("retrieval")),
            metadata=payload.get("metadata") or {},
        )

    def to_dict(self) -> Dict[str, Any]:
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
    evidence_package: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

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
        if hasattr(self.evidence_package, "to_dict"):
            self.evidence_package = self.evidence_package.to_dict()
        elif isinstance(self.evidence_package, dict):
            self.evidence_package = dict(self.evidence_package)
        else:
            self.evidence_package = {}
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_route_resolution(
        cls,
        resolution: RouteResolution,
        *,
        evidence_package: Any = None,
        metadata: Dict[str, Any] | None = None,
    ) -> "AnswerContext":
        return cls(
            question=resolution.query,
            retrieval=resolution.retrieval,
            analysis=resolution.analysis,
            understanding=resolution.understanding,
            evidence_package=evidence_package or {},
            metadata=metadata or resolution.metadata,
        )

    @property
    def documents(self) -> List[Document]:
        return self.retrieval.documents

    @property
    def evidence_documents(self) -> List[EvidenceDocument]:
        return list(self.retrieval.evidence_documents)

    @property
    def has_evidence_package(self) -> bool:
        items = (
            self.evidence_package.get("items") if isinstance(self.evidence_package, dict) else None
        )
        return bool(items)

    def with_evidence_package(self, payload: Any) -> "AnswerContext":
        if hasattr(payload, "to_dict"):
            payload = payload.to_dict()
        return replace(self, evidence_package=dict(payload or {}))

    def to_dict(self) -> Dict[str, Any]:
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
