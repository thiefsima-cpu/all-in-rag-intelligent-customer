"""Retrieval request models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional

from ...domain.shared.query_constraints import QueryConstraints
from ...query_understanding import QueryPlan
from ._common import coerce_str


@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 5
    candidate_k: int = 0
    strategy: str = ""
    constraints: QueryConstraints = field(default_factory=QueryConstraints)
    query_plan: Optional[QueryPlan] = None
    entity_keywords: List[str] = field(default_factory=list)
    topic_keywords: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.query = coerce_str(self.query)
        self.top_k = max(1, int(self.top_k or 1))
        self.candidate_k = max(0, int(self.candidate_k or 0))
        self.strategy = coerce_str(self.strategy)
        self.constraints = self.constraints or QueryConstraints()
        self.entity_keywords = [
            str(item).strip() for item in (self.entity_keywords or []) if str(item).strip()
        ]
        self.topic_keywords = [
            str(item).strip() for item in (self.topic_keywords or []) if str(item).strip()
        ]
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RetrievalRequest":
        payload = dict(data or {})
        query = coerce_str(payload.get("query"))
        constraints_data = payload.get("constraints") or {}
        constraints = (
            constraints_data
            if isinstance(constraints_data, QueryConstraints)
            else QueryConstraints.from_dict(constraints_data)
        )
        query_plan_data = payload.get("query_plan")
        query_plan = None
        if isinstance(query_plan_data, QueryPlan):
            query_plan = query_plan_data
        elif isinstance(query_plan_data, dict):
            query_plan = QueryPlan.from_dict(query, query_plan_data)
        return cls(
            query=query,
            top_k=payload.get("top_k", 5),
            candidate_k=payload.get("candidate_k", 0),
            strategy=payload.get("strategy", ""),
            constraints=constraints,
            query_plan=query_plan,
            entity_keywords=payload.get("entity_keywords") or [],
            topic_keywords=payload.get("topic_keywords") or [],
            metadata=payload.get("metadata") or {},
        )

    @classmethod
    def from_inputs(
        cls,
        *,
        query: str,
        top_k: int = 5,
        candidate_k: Optional[int] = None,
        strategy: str = "",
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
        entity_keywords: Optional[Iterable[str]] = None,
        topic_keywords: Optional[Iterable[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "RetrievalRequest":
        resolved_constraints = constraints or (
            query_plan.constraints if query_plan else QueryConstraints()
        )
        resolved_strategy = strategy or (query_plan.strategy if query_plan else "")
        return cls(
            query=query,
            top_k=max(1, int(top_k or 1)),
            candidate_k=max(0, int(candidate_k or 0)),
            strategy=resolved_strategy,
            constraints=resolved_constraints,
            query_plan=query_plan,
            entity_keywords=[str(item) for item in (entity_keywords or []) if str(item).strip()],
            topic_keywords=[str(item) for item in (topic_keywords or []) if str(item).strip()],
            metadata=dict(metadata or {}),
        )

    @property
    def effective_constraints(self) -> QueryConstraints:
        return self.constraints or QueryConstraints()

    @property
    def effective_candidate_k(self) -> int:
        return max(1, int(self.candidate_k or self.top_k or 1))

    @property
    def planned_entity_keywords(self) -> List[str]:
        if self.entity_keywords:
            return list(self.entity_keywords)
        if not self.query_plan:
            return []
        return list(
            dict.fromkeys(
                [
                    *self.query_plan.entity_keywords,
                    *self.query_plan.source_entities,
                ]
            )
        )

    @property
    def planned_topic_keywords(self) -> List[str]:
        if self.topic_keywords:
            return list(self.topic_keywords)
        if not self.query_plan:
            return []
        return list(dict.fromkeys(self.query_plan.topic_keywords))

    def copy_with(self, **changes: Any) -> "RetrievalRequest":
        return replace(self, **changes)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["constraints"] = self.effective_constraints.to_dict()
        payload["query_plan"] = self.query_plan.to_dict() if self.query_plan else None
        return payload
