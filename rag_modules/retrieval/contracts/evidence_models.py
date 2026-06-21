"""Evidence-native retrieval document models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional

from ._common import coerce_float, coerce_str


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
