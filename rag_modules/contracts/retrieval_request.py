"""Retrieval request DTO and parsing helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..kernel.json_types import (
    JsonObject,
    as_string_list,
    coerce_int,
    coerce_json_object,
    coerce_str,
)
from .query_constraints import QueryConstraints
from .query_plan import QueryPlan
from .query_settings import QuerySemanticRuntimeSettings

if TYPE_CHECKING:
    from .request_control import RequestControl


@dataclass
class RetrievalRequest:
    query: str
    top_k: int = 5
    candidate_k: int = 0
    strategy: str = ""
    constraints: QueryConstraints = field(default_factory=QueryConstraints)
    query_plan: QueryPlan | None = None
    entity_keywords: list[str] = field(default_factory=list)
    topic_keywords: list[str] = field(default_factory=list)
    metadata: JsonObject = field(default_factory=dict)
    control: RequestControl | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.query = coerce_str(self.query)
        self.top_k = max(1, int(self.top_k or 1))
        self.candidate_k = max(0, int(self.candidate_k or 0))
        self.strategy = coerce_str(self.strategy)
        self.constraints = self.constraints or QueryConstraints()
        self.entity_keywords = as_string_list(self.entity_keywords)
        self.topic_keywords = as_string_list(self.topic_keywords)
        self.metadata = coerce_json_object(self.metadata)

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, object] | None,
        *,
        semantic_settings: QuerySemanticRuntimeSettings,
    ) -> "RetrievalRequest":
        payload = dict(data or {})
        query = coerce_str(payload.get("query"))
        constraints_data = payload.get("constraints")
        constraints = (
            constraints_data
            if isinstance(constraints_data, QueryConstraints)
            else QueryConstraints.from_dict(
                constraints_data if isinstance(constraints_data, Mapping) else None
            )
        )
        query_plan_data = payload.get("query_plan")
        query_plan = None
        if isinstance(query_plan_data, QueryPlan):
            query_plan = query_plan_data
        elif isinstance(query_plan_data, Mapping):
            query_plan = QueryPlan.from_dict(
                query,
                query_plan_data,
                semantic_settings=semantic_settings,
            )
        return cls(
            query=query,
            top_k=coerce_int(payload.get("top_k"), 5, minimum=1),
            candidate_k=coerce_int(payload.get("candidate_k")),
            strategy=coerce_str(payload.get("strategy")),
            constraints=constraints,
            query_plan=query_plan,
            entity_keywords=as_string_list(payload.get("entity_keywords")),
            topic_keywords=as_string_list(payload.get("topic_keywords")),
            metadata=coerce_json_object(payload.get("metadata")),
            control=None,
        )

    @classmethod
    def from_inputs(
        cls,
        *,
        query: str,
        top_k: int = 5,
        candidate_k: int | None = None,
        strategy: str = "",
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
        entity_keywords: Iterable[str] | None = None,
        topic_keywords: Iterable[str] | None = None,
        metadata: JsonObject | None = None,
        control: RequestControl | None = None,
    ) -> "RetrievalRequest":
        resolved_constraints = constraints or (
            query_plan.constraints if query_plan else QueryConstraints()
        )
        resolved_strategy = strategy or (query_plan.strategy_value if query_plan else "")
        return cls(
            query=query,
            top_k=max(1, int(top_k or 1)),
            candidate_k=max(0, int(candidate_k or 0)),
            strategy=resolved_strategy,
            constraints=resolved_constraints,
            query_plan=query_plan,
            entity_keywords=as_string_list(list(entity_keywords or [])),
            topic_keywords=as_string_list(list(topic_keywords or [])),
            metadata=coerce_json_object(metadata),
            control=control,
        )

    @property
    def effective_constraints(self) -> QueryConstraints:
        return self.constraints or QueryConstraints()

    @property
    def effective_candidate_k(self) -> int:
        return max(1, int(self.candidate_k or self.top_k or 1))

    @property
    def planned_entity_keywords(self) -> list[str]:
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
    def planned_topic_keywords(self) -> list[str]:
        if self.topic_keywords:
            return list(self.topic_keywords)
        if not self.query_plan:
            return []
        return list(dict.fromkeys(self.query_plan.topic_keywords))

    def to_dict(self) -> JsonObject:
        from .request_control import control_trace_details

        payload = {
            "query": self.query,
            "top_k": self.top_k,
            "candidate_k": self.candidate_k,
            "strategy": self.strategy,
            "constraints": self.effective_constraints.to_dict(),
            "query_plan": self.query_plan.to_dict() if self.query_plan else None,
            "entity_keywords": list(self.entity_keywords),
            "topic_keywords": list(self.topic_keywords),
            "metadata": coerce_json_object(self.metadata),
        }
        control_details = control_trace_details(self.control)
        if control_details:
            payload["control"] = control_details
        return coerce_json_object(payload)


__all__ = ["RetrievalRequest"]
