"""Retrieval request and evidence DTOs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional

from ..domain.shared.query_constraints import QueryConstraints
from ._common import coerce_float, coerce_str
from .query import QueryPlan


@dataclass
class EvidenceDocument:
    content: str
    node_id: str = ""
    recipe_name: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    recipe_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: List[str] = field(default_factory=list)
    graph_evidence: Dict[str, Any] = field(default_factory=dict)
    recipe_graph_evidence: Dict[str, Any] = field(default_factory=dict)
    constraint_evidence: Dict[str, Any] = field(default_factory=dict)
    evidence_units: List[Dict[str, Any]] = field(default_factory=list)
    route_strategy: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.content = coerce_str(self.content)
        self.node_id = coerce_str(self.node_id)
        self.recipe_name = coerce_str(self.recipe_name)
        self.node_type = coerce_str(self.node_type)
        self.score = coerce_float(self.score)
        self.search_type = coerce_str(self.search_type)
        self.search_method = coerce_str(self.search_method)
        self.retrieval_level = coerce_str(self.retrieval_level)
        self.doc_id = coerce_str(self.doc_id)
        self.recipe_id = coerce_str(self.recipe_id or self.node_id)
        self.source = coerce_str(self.source or self.search_method or self.search_type or "unknown")
        self.evidence_type = coerce_str(self.evidence_type or "text")
        self.matched_terms = [
            str(item).strip() for item in (self.matched_terms or []) if str(item).strip()
        ]
        self.graph_evidence = dict(self.graph_evidence or {})
        self.recipe_graph_evidence = dict(self.recipe_graph_evidence or {})
        self.constraint_evidence = dict(self.constraint_evidence or {})
        self.evidence_units = [
            dict(item) for item in (self.evidence_units or []) if isinstance(item, dict)
        ]
        self.route_strategy = coerce_str(self.route_strategy)
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "EvidenceDocument":
        data = dict(payload or {})
        return cls(
            content=coerce_str(data.get("content")),
            node_id=coerce_str(data.get("node_id")),
            recipe_name=coerce_str(data.get("recipe_name")),
            node_type=coerce_str(data.get("node_type")),
            score=coerce_float(data.get("score")),
            search_type=coerce_str(data.get("search_type")),
            search_method=coerce_str(data.get("search_method")),
            retrieval_level=coerce_str(data.get("retrieval_level")),
            doc_id=coerce_str(data.get("doc_id")),
            recipe_id=coerce_str(data.get("recipe_id")),
            source=coerce_str(data.get("source")),
            evidence_type=coerce_str(data.get("evidence_type")),
            matched_terms=[
                str(item).strip() for item in (data.get("matched_terms") or []) if str(item).strip()
            ],
            graph_evidence=dict(data.get("graph_evidence") or {}),
            recipe_graph_evidence=dict(data.get("recipe_graph_evidence") or {}),
            constraint_evidence=dict(data.get("constraint_evidence") or {}),
            evidence_units=[
                dict(item) for item in (data.get("evidence_units") or []) if isinstance(item, dict)
            ],
            route_strategy=coerce_str(data.get("route_strategy")),
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_langchain(cls, doc: Any) -> "EvidenceDocument":
        from .langchain_compat import evidence_document_from_langchain

        return evidence_document_from_langchain(doc, cls=cls)

    def copy_with(self, **changes: Any) -> "EvidenceDocument":
        return replace(self, **changes)

    def with_search_fields(
        self,
        *,
        search_method: Optional[str] = None,
        search_type: Optional[str] = None,
        retrieval_level: Optional[str] = None,
        score: Optional[float] = None,
        metadata_updates: Optional[Dict[str, Any]] = None,
    ) -> "EvidenceDocument":
        metadata = dict(self.metadata or {})
        if metadata_updates:
            metadata.update(metadata_updates)
        if search_method:
            metadata.setdefault("search_method", search_method)
        if search_type:
            metadata.setdefault("search_type", search_type)
        if retrieval_level:
            metadata.setdefault("retrieval_level", retrieval_level)
        if score is not None:
            metadata.setdefault("score", score)
        return self.copy_with(
            score=self.score if score is None else score,
            search_method=self.search_method or coerce_str(search_method),
            search_type=self.search_type or coerce_str(search_type),
            retrieval_level=self.retrieval_level or coerce_str(retrieval_level),
            metadata=metadata,
        )

    def document_key(self) -> str:
        metadata = self.metadata or {}
        node_id = self.node_id or coerce_str(
            metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
            or self.recipe_id
        )
        if node_id:
            return node_id
        recipe_name = self.recipe_name or coerce_str(metadata.get("recipe_name"))
        if recipe_name:
            return f"recipe::{recipe_name}"
        return f"hash::{hash((self.content or '')[:200])}"

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "recipe_id": self.recipe_id or self.node_id,
            "recipe_name": self.recipe_name,
            "source": self.source,
            "score": self.score,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence or {}),
            "recipe_graph_evidence": dict(self.recipe_graph_evidence or {}),
            "constraint_evidence": dict(self.constraint_evidence or {}),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
        }

    def to_langchain(self):
        from .langchain_compat import evidence_document_to_langchain

        return evidence_document_to_langchain(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "node_id": self.node_id,
            "recipe_name": self.recipe_name,
            "node_type": self.node_type,
            "score": self.score,
            "search_type": self.search_type,
            "search_method": self.search_method,
            "retrieval_level": self.retrieval_level,
            "doc_id": self.doc_id,
            "recipe_id": self.recipe_id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence or {}),
            "recipe_graph_evidence": dict(self.recipe_graph_evidence or {}),
            "constraint_evidence": dict(self.constraint_evidence or {}),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
            "metadata": dict(self.metadata or {}),
        }


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


__all__ = ["EvidenceDocument", "RetrievalRequest"]
