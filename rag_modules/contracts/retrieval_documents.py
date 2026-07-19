"""Evidence document DTOs and page-like conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, TypeVar, cast

from ._common import coerce_float, coerce_str


class PageDocumentLike(Protocol):
    @property
    def page_content(self) -> str: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


@dataclass(init=False)
class EvidenceDocument:
    content: str
    entity_id: str = ""
    entity_name: str = ""
    entity_type: str = ""
    node_id: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: List[str] = field(default_factory=list)
    graph_evidence: Dict[str, Any] = field(default_factory=dict)
    domain_graph_evidence: Dict[str, Any] = field(default_factory=dict)
    constraint_evidence: Dict[str, Any] = field(default_factory=dict)
    evidence_units: List[Dict[str, Any]] = field(default_factory=list)
    route_strategy: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        content: str,
        node_id: str = "",
        recipe_name: str = "",
        node_type: str = "",
        score: float = 0.0,
        search_type: str = "",
        search_method: str = "",
        retrieval_level: str = "",
        doc_id: str = "",
        recipe_id: str = "",
        source: str = "unknown",
        evidence_type: str = "text",
        matched_terms: List[str] | None = None,
        graph_evidence: Dict[str, Any] | None = None,
        recipe_graph_evidence: Dict[str, Any] | None = None,
        constraint_evidence: Dict[str, Any] | None = None,
        evidence_units: List[Dict[str, Any]] | None = None,
        route_strategy: str = "",
        metadata: Dict[str, Any] | None = None,
        *,
        entity_id: str = "",
        entity_name: str = "",
        entity_type: str = "",
        domain_graph_evidence: Dict[str, Any] | None = None,
    ) -> None:
        self.content = content
        self.entity_id = entity_id or recipe_id
        self.entity_name = entity_name or recipe_name
        self.entity_type = entity_type or node_type
        self.node_id = node_id
        self.node_type = node_type
        self.score = score
        self.search_type = search_type
        self.search_method = search_method
        self.retrieval_level = retrieval_level
        self.doc_id = doc_id
        self.source = source
        self.evidence_type = evidence_type
        self.matched_terms = list(matched_terms or [])
        self.graph_evidence = dict(graph_evidence or {})
        self.domain_graph_evidence = dict(domain_graph_evidence or recipe_graph_evidence or {})
        self.constraint_evidence = dict(constraint_evidence or {})
        self.evidence_units = list(evidence_units or [])
        self.route_strategy = route_strategy
        self.metadata = dict(metadata or {})
        self._legacy_recipe_compat = bool(
            recipe_id
            or recipe_name
            or recipe_graph_evidence
            or "recipe_id" in self.metadata
            or "recipe_name" in self.metadata
            or self.metadata.get("domain") == "recipe"
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        self.content = coerce_str(self.content)
        self.entity_id = coerce_str(self.entity_id or self.node_id)
        self.entity_name = coerce_str(self.entity_name)
        self.entity_type = coerce_str(self.entity_type or self.node_type)
        self.node_id = coerce_str(self.node_id)
        self.node_type = coerce_str(self.node_type or self.entity_type)
        self.score = coerce_float(self.score)
        self.search_type = coerce_str(self.search_type)
        self.search_method = coerce_str(self.search_method)
        self.retrieval_level = coerce_str(self.retrieval_level)
        self.doc_id = coerce_str(self.doc_id)
        self.source = coerce_str(self.source or self.search_method or self.search_type or "unknown")
        self.evidence_type = coerce_str(self.evidence_type or "text")
        self.matched_terms = [
            str(item).strip() for item in (self.matched_terms or []) if str(item).strip()
        ]
        self.graph_evidence = dict(self.graph_evidence or {})
        self.domain_graph_evidence = dict(self.domain_graph_evidence or {})
        self.constraint_evidence = dict(self.constraint_evidence or {})
        self.evidence_units = [
            dict(item) for item in (self.evidence_units or []) if isinstance(item, dict)
        ]
        self.route_strategy = coerce_str(self.route_strategy)
        self.metadata = dict(self.metadata or {})

    @property
    def recipe_id(self) -> str:
        """Deprecated recipe-domain alias for ``entity_id``."""

        return self.entity_id

    @recipe_id.setter
    def recipe_id(self, value: object) -> None:
        self.entity_id = coerce_str(value)
        self._legacy_recipe_compat = True

    @property
    def recipe_name(self) -> str:
        """Deprecated recipe-domain alias for ``entity_name``."""

        return self.entity_name

    @recipe_name.setter
    def recipe_name(self, value: object) -> None:
        self.entity_name = coerce_str(value)
        self._legacy_recipe_compat = True

    @property
    def recipe_graph_evidence(self) -> Dict[str, Any]:
        """Deprecated recipe-domain alias for ``domain_graph_evidence``."""

        return self.domain_graph_evidence

    @recipe_graph_evidence.setter
    def recipe_graph_evidence(self, value: object) -> None:
        self.domain_graph_evidence = dict(value or {}) if isinstance(value, Mapping) else {}
        self._legacy_recipe_compat = True

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "EvidenceDocument":
        data = dict(payload or {})
        return cls(
            content=coerce_str(data.get("content")),
            entity_id=coerce_str(data.get("entity_id")),
            entity_name=coerce_str(data.get("entity_name")),
            entity_type=coerce_str(data.get("entity_type")),
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
            domain_graph_evidence=dict(data.get("domain_graph_evidence") or {}),
            recipe_graph_evidence=dict(data.get("recipe_graph_evidence") or {}),
            constraint_evidence=dict(data.get("constraint_evidence") or {}),
            evidence_units=[
                dict(item) for item in (data.get("evidence_units") or []) if isinstance(item, dict)
            ],
            route_strategy=coerce_str(data.get("route_strategy")),
            metadata=dict(data.get("metadata") or {}),
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
            search_method=self.search_method or coerce_str(search_method),
            search_type=self.search_type or coerce_str(search_type),
            retrieval_level=self.retrieval_level or coerce_str(retrieval_level),
            metadata=metadata,
        )

    def document_key(self) -> str:
        metadata = self.metadata or {}
        node_id = self.node_id or coerce_str(
            metadata.get("entity_id")
            or self.entity_id
            or metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        )
        if node_id:
            return node_id
        entity_name = self.entity_name or coerce_str(
            metadata.get("entity_name") or metadata.get("recipe_name")
        )
        if entity_name:
            entity_type = self.entity_type or coerce_str(metadata.get("entity_type")) or "entity"
            return f"{entity_type.casefold()}::{entity_name}"
        return f"hash::{hash((self.content or '')[:200])}"

    def to_metadata(self) -> Dict[str, Any]:
        payload = {
            "doc_id": self.doc_id,
            "entity_id": self.entity_id or self.node_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "source": self.source,
            "score": self.score,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence or {}),
            "domain_graph_evidence": dict(self.domain_graph_evidence or {}),
            "constraint_evidence": dict(self.constraint_evidence or {}),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
        }
        if self._legacy_recipe_compat:
            payload.update(
                {
                    "recipe_id": self.entity_id or self.node_id,
                    "recipe_name": self.entity_name,
                    "recipe_graph_evidence": dict(self.domain_graph_evidence or {}),
                }
            )
        return payload

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "content": self.content,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "score": self.score,
            "search_type": self.search_type,
            "search_method": self.search_method,
            "retrieval_level": self.retrieval_level,
            "doc_id": self.doc_id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence or {}),
            "domain_graph_evidence": dict(self.domain_graph_evidence or {}),
            "constraint_evidence": dict(self.constraint_evidence or {}),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
            "metadata": dict(self.metadata or {}),
        }
        if self._legacy_recipe_compat:
            payload.update(
                {
                    "recipe_id": self.entity_id,
                    "recipe_name": self.entity_name,
                    "recipe_graph_evidence": dict(self.domain_graph_evidence or {}),
                }
            )
        return payload


EvidenceDocumentT = TypeVar("EvidenceDocumentT", bound=EvidenceDocument)


def matched_terms_from_metadata(metadata: dict) -> List[str]:
    matched_terms = list(metadata.get("matched_terms") or [])
    if matched_terms:
        return list(dict.fromkeys(str(item) for item in matched_terms if str(item).strip()))

    collected: List[str] = []
    for key in (
        "matched_keyword",
        "matched_entities",
        "matched_attributes",
        "matched_ingredients",
        "matched_steps",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            collected.extend(str(item) for item in value if item)
        elif value:
            collected.append(str(value))
    return list(dict.fromkeys(item for item in collected if item.strip()))


def evidence_document_from_page_like(
    doc: PageDocumentLike,
    *,
    cls: type[EvidenceDocumentT] | None = None,
) -> EvidenceDocumentT:
    metadata = dict(doc.metadata or {})
    document_cls = cls or cast(type[EvidenceDocumentT], EvidenceDocument)
    return document_cls(
        content=doc.page_content or "",
        entity_id=coerce_str(
            metadata.get("entity_id")
            or metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        entity_name=coerce_str(
            metadata.get("entity_name") or metadata.get("recipe_name") or metadata.get("name")
        ),
        entity_type=coerce_str(metadata.get("entity_type") or metadata.get("node_type")),
        node_id=coerce_str(
            metadata.get("node_id")
            or metadata.get("entity_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        recipe_name=coerce_str(metadata.get("recipe_name") or metadata.get("name")),
        node_type=coerce_str(metadata.get("node_type") or metadata.get("entity_type")),
        score=coerce_float(
            metadata.get("final_score")
            or metadata.get("relevance_score")
            or metadata.get("constraint_score")
            or metadata.get("score")
            or metadata.get("bm25_score")
        ),
        search_type=coerce_str(metadata.get("search_type")),
        search_method=coerce_str(metadata.get("search_method") or metadata.get("search_source")),
        retrieval_level=coerce_str(metadata.get("retrieval_level")),
        doc_id=coerce_str(metadata.get("doc_id")),
        recipe_id=coerce_str(
            metadata.get("recipe_id") or metadata.get("node_id") or metadata.get("parent_id")
        ),
        source=coerce_str(
            metadata.get("source")
            or metadata.get("search_source")
            or metadata.get("search_method")
            or metadata.get("search_type")
            or "unknown"
        ),
        evidence_type=coerce_str(
            metadata.get("evidence_type")
            or metadata.get("search_type")
            or ("recipe" if metadata.get("recipe_name") else "text")
        ),
        matched_terms=matched_terms_from_metadata(metadata),
        graph_evidence=dict(metadata.get("graph_evidence") or {}),
        domain_graph_evidence=dict(metadata.get("domain_graph_evidence") or {}),
        recipe_graph_evidence=dict(metadata.get("recipe_graph_evidence") or {}),
        constraint_evidence=dict(metadata.get("constraint_evidence") or {}),
        evidence_units=[
            dict(item) for item in (metadata.get("evidence_units") or []) if isinstance(item, dict)
        ],
        route_strategy=coerce_str(metadata.get("route_strategy")),
        metadata=metadata,
    )


def ensure_evidence_documents(
    documents: Iterable[PageDocumentLike | EvidenceDocument],
) -> List[EvidenceDocument]:
    evidence_documents: List[EvidenceDocument] = []
    for doc in documents or []:
        if isinstance(doc, EvidenceDocument):
            evidence_documents.append(doc)
        else:
            evidence_documents.append(evidence_document_from_page_like(doc))
    return evidence_documents


__all__ = [
    "EvidenceDocument",
    "PageDocumentLike",
    "ensure_evidence_documents",
    "evidence_document_from_page_like",
    "matched_terms_from_metadata",
]
