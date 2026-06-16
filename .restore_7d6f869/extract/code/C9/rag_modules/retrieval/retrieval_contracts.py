"""
Shared contracts for retrieval orchestration.

These dataclasses make query requests and retrieval evidence explicit so the
retrieval stack stops relying on ad hoc metadata conventions alone.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional

from langchain_core.documents import Document

from ..query_constraints import QueryConstraints
from ..query_plan import QueryPlan


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
        self.query = _coerce_str(self.query)
        self.top_k = max(1, int(self.top_k or 1))
        self.candidate_k = max(0, int(self.candidate_k or 0))
        self.strategy = _coerce_str(self.strategy)
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
        query = _coerce_str(payload.get("query"))
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
        return list(dict.fromkeys([
            *self.query_plan.entity_keywords,
            *self.query_plan.source_entities,
        ]))

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
        self.content = _coerce_str(self.content)
        self.node_id = _coerce_str(self.node_id)
        self.recipe_name = _coerce_str(self.recipe_name)
        self.node_type = _coerce_str(self.node_type)
        self.score = _coerce_float(self.score)
        self.search_type = _coerce_str(self.search_type)
        self.search_method = _coerce_str(self.search_method)
        self.retrieval_level = _coerce_str(self.retrieval_level)
        self.doc_id = _coerce_str(self.doc_id)
        self.recipe_id = _coerce_str(self.recipe_id or self.node_id)
        self.source = _coerce_str(self.source or self.search_method or self.search_type or "unknown")
        self.evidence_type = _coerce_str(self.evidence_type or "text")
        self.matched_terms = [
            str(item).strip() for item in (self.matched_terms or []) if str(item).strip()
        ]
        self.graph_evidence = dict(self.graph_evidence or {})
        self.recipe_graph_evidence = dict(self.recipe_graph_evidence or {})
        self.constraint_evidence = dict(self.constraint_evidence or {})
        self.evidence_units = [
            dict(item) for item in (self.evidence_units or []) if isinstance(item, dict)
        ]
        self.route_strategy = _coerce_str(self.route_strategy)
        self.metadata = dict(self.metadata or {})

    @classmethod
    def from_langchain(cls, doc: Document) -> "EvidenceDocument":
        metadata = dict(doc.metadata or {})
        matched_terms = metadata.get("matched_terms") or []
        if not matched_terms:
            for key in ("matched_keyword", "matched_ingredients", "matched_steps"):
                value = metadata.get(key)
                if isinstance(value, list):
                    matched_terms.extend(str(item) for item in value if item)
                elif value:
                    matched_terms.append(str(value))
        return cls(
            content=doc.page_content or "",
            node_id=_coerce_str(
                metadata.get("node_id")
                or metadata.get("parent_id")
                or metadata.get("recipe_id")
            ),
            recipe_name=_coerce_str(metadata.get("recipe_name") or metadata.get("name")),
            node_type=_coerce_str(metadata.get("node_type") or metadata.get("entity_type")),
            score=_coerce_float(
                metadata.get("final_score")
                or metadata.get("relevance_score")
                or metadata.get("constraint_score")
                or metadata.get("score")
                or metadata.get("bm25_score")
            ),
            search_type=_coerce_str(metadata.get("search_type")),
            search_method=_coerce_str(metadata.get("search_method") or metadata.get("search_source")),
            retrieval_level=_coerce_str(metadata.get("retrieval_level")),
            doc_id=_coerce_str(metadata.get("doc_id")),
            recipe_id=_coerce_str(
                metadata.get("recipe_id")
                or metadata.get("node_id")
                or metadata.get("parent_id")
            ),
            source=_coerce_str(
                metadata.get("source")
                or metadata.get("search_source")
                or metadata.get("search_method")
                or metadata.get("search_type")
                or "unknown"
            ),
            evidence_type=_coerce_str(
                metadata.get("evidence_type")
                or metadata.get("search_type")
                or ("recipe" if metadata.get("recipe_name") else "text")
            ),
            matched_terms=list(dict.fromkeys(matched_terms)),
            graph_evidence=dict(metadata.get("graph_evidence") or {}),
            recipe_graph_evidence=dict(metadata.get("recipe_graph_evidence") or {}),
            constraint_evidence=dict(metadata.get("constraint_evidence") or {}),
            evidence_units=[
                dict(item) for item in (metadata.get("evidence_units") or []) if isinstance(item, dict)
            ],
            route_strategy=_coerce_str(metadata.get("route_strategy")),
            metadata=metadata,
        )

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
            search_method=self.search_method or _coerce_str(search_method),
            search_type=self.search_type or _coerce_str(search_type),
            retrieval_level=self.retrieval_level or _coerce_str(retrieval_level),
            metadata=metadata,
        )

    def document_key(self) -> str:
        metadata = self.metadata or {}
        node_id = self.node_id or _coerce_str(
            metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
            or self.recipe_id
        )
        if node_id:
            return node_id
        recipe_name = self.recipe_name or _coerce_str(metadata.get("recipe_name"))
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

    def to_langchain(self) -> Document:
        metadata = dict(self.metadata or {})
        metadata.update({
            key: value
            for key, value in self.to_metadata().items()
            if value not in (None, "", [], {})
        })
        if self.node_id:
            metadata.setdefault("node_id", self.node_id)
        if self.recipe_name:
            metadata.setdefault("recipe_name", self.recipe_name)
        if self.node_type:
            metadata.setdefault("node_type", self.node_type)
        if self.retrieval_level:
            metadata.setdefault("retrieval_level", self.retrieval_level)
        if self.search_type:
            metadata.setdefault("search_type", self.search_type)
        if self.search_method:
            metadata.setdefault("search_method", self.search_method)
        metadata.setdefault("score", self.score)
        return Document(page_content=self.content, metadata=metadata)

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


def ensure_evidence_documents(documents: Iterable[Document | EvidenceDocument]) -> List[EvidenceDocument]:
    evidence_documents: List[EvidenceDocument] = []
    for doc in documents or []:
        if isinstance(doc, EvidenceDocument):
            evidence_documents.append(doc)
        elif isinstance(doc, Document):
            evidence_documents.append(EvidenceDocument.from_langchain(doc))
    return evidence_documents


def to_langchain_documents(documents: Iterable[EvidenceDocument]) -> List[Document]:
    return [doc.to_langchain() for doc in documents or []]


def from_langchain_documents(documents: Iterable[Document]) -> List[EvidenceDocument]:
    return [EvidenceDocument.from_langchain(doc) for doc in documents or []]
