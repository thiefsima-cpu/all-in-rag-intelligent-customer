"""
Structured evidence builder for answer generation.

This module turns retrieved evidence into a compact, citation-ready package.
The package can be sliced differently for planning, direct answering, and final
composition so generation cost stays configurable instead of being hardcoded in
prompts.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Dict, List, cast

from .contracts import EvidenceDocument, PageDocumentLike, ensure_evidence_documents
from .evidence_processing import aggregate_recipe_evidence


def _float_value(value: object, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _iter_values(value: object) -> Iterable[object]:
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    if isinstance(value, Iterable):
        return value
    return []


def _string_list(value: object) -> List[str]:
    return [text for item in _iter_values(value) if (text := str(item).strip())]


def _dict_list(value: object) -> List[dict]:
    return [dict(item) for item in _iter_values(value) if isinstance(item, dict)]


@dataclass
class AnswerEvidenceItem:
    citation: str
    recipe_id: str
    recipe_name: str
    confidence: float
    retrieval_sources: List[str] = field(default_factory=list)
    matched_terms: List[str] = field(default_factory=list)
    constraint_reasons: List[str] = field(default_factory=list)
    graph_paths: List[dict] = field(default_factory=list)
    evidence_units: List[dict] = field(default_factory=list)
    document_evidence: List[dict] = field(default_factory=list)
    content: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, object] | None) -> "AnswerEvidenceItem":
        data = dict(payload or {})
        return cls(
            citation=str(data.get("citation") or ""),
            recipe_id=str(data.get("recipe_id") or ""),
            recipe_name=str(data.get("recipe_name") or ""),
            confidence=_float_value(data.get("confidence")),
            retrieval_sources=_string_list(data.get("retrieval_sources")),
            matched_terms=_string_list(data.get("matched_terms")),
            constraint_reasons=_string_list(data.get("constraint_reasons")),
            graph_paths=_dict_list(data.get("graph_paths")),
            evidence_units=_dict_list(data.get("evidence_units")),
            document_evidence=_dict_list(data.get("document_evidence")),
            content=str(data.get("content") or ""),
        )

    def to_dict(self) -> Dict[str, object]:
        return {
            "citation": self.citation,
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "confidence": self.confidence,
            "retrieval_sources": list(self.retrieval_sources or []),
            "matched_terms": list(self.matched_terms or []),
            "constraint_reasons": list(self.constraint_reasons or []),
            "graph_paths": [dict(item) for item in self.graph_paths],
            "evidence_units": [dict(item) for item in self.evidence_units],
            "document_evidence": [dict(item) for item in self.document_evidence],
            "content": self.content,
        }

    def to_summary_dict(
        self,
        max_graph_claims: int = 4,
        max_text_claims: int = 4,
    ) -> Dict[str, object]:
        return {
            "citation": self.citation,
            "recipe_name": self.recipe_name,
            "confidence": round(float(self.confidence or 0.0), 4),
            "retrieval_sources": self.retrieval_sources[:4],
            "matched_terms": self.matched_terms[:8],
            "constraint_reasons": self.constraint_reasons[:6],
            "graph_claims": [
                unit.get("claim")
                for unit in self.evidence_units
                if unit.get("is_graph_evidence") and unit.get("claim")
            ][:max_graph_claims],
            "text_claims": [
                unit.get("claim")
                for unit in self.evidence_units
                if not unit.get("is_graph_evidence") and unit.get("claim")
            ][:max_text_claims],
        }

    def to_context_block(
        self,
        *,
        include_content: bool = True,
        include_document_evidence: bool = False,
        max_graph_paths: int = 2,
        max_evidence_units: int = 6,
        max_content_chars: int | None = None,
    ) -> str:
        payload = {
            "citation": self.citation,
            "recipe_id": self.recipe_id,
            "recipe_name": self.recipe_name,
            "confidence": round(float(self.confidence or 0.0), 4),
            "retrieval_sources": self.retrieval_sources[:4],
            "matched_terms": self.matched_terms[:8],
            "constraint_reasons": self.constraint_reasons[:6],
            "graph_paths": self.graph_paths[:max_graph_paths],
            "evidence_units": self.evidence_units[:max_evidence_units],
        }
        if include_document_evidence:
            payload["document_evidence"] = self.document_evidence[:6]
        payload = {key: value for key, value in payload.items() if value not in (None, "", [], {})}

        parts = [f"[{self.citation}]", json.dumps(payload, ensure_ascii=False)]
        if include_content and self.content.strip():
            content = self.content.strip()
            if max_content_chars and len(content) > max_content_chars:
                content = content[:max_content_chars].rstrip() + "\n...[内容已截断]"
            parts.append("内容摘要:")
            parts.append(content)
        return "\n".join(parts)


@dataclass
class AnswerEvidencePackage:
    question: str
    items: List[AnswerEvidenceItem]

    @classmethod
    def from_dict(cls, payload: Mapping[str, object] | None) -> "AnswerEvidencePackage":
        data = dict(payload or {})
        items: List[AnswerEvidenceItem] = []
        for item in _iter_values(data.get("items")):
            if isinstance(item, AnswerEvidenceItem):
                items.append(item)
            elif isinstance(item, dict):
                items.append(AnswerEvidenceItem.from_dict(cast(Dict[str, object], item)))
        return cls(
            question=str(data.get("question") or ""),
            items=items,
        )

    def limit_items(self, max_items: int | None) -> "AnswerEvidencePackage":
        if not max_items or max_items <= 0:
            return AnswerEvidencePackage(question=self.question, items=list(self.items))
        return AnswerEvidencePackage(question=self.question, items=list(self.items[:max_items]))

    def to_context_text(
        self,
        *,
        include_content: bool = True,
        include_document_evidence: bool = False,
        max_graph_paths: int = 2,
        max_evidence_units: int = 6,
        max_content_chars: int | None = None,
    ) -> str:
        return "\n\n".join(
            item.to_context_block(
                include_content=include_content,
                include_document_evidence=include_document_evidence,
                max_graph_paths=max_graph_paths,
                max_evidence_units=max_evidence_units,
                max_content_chars=max_content_chars,
            )
            for item in self.items
            if item.content.strip() or item.evidence_units or item.graph_paths
        )

    def summarize_for_plan(self, max_items: int | None = None) -> List[Dict[str, object]]:
        items = self.items if not max_items or max_items <= 0 else self.items[:max_items]
        return [item.to_summary_dict() for item in items]

    @property
    def citation_list(self) -> List[str]:
        return [item.citation for item in self.items]

    def to_dict(self) -> Dict[str, object]:
        return {
            "question": self.question,
            "items": [item.to_dict() for item in self.items],
        }


class AnswerEvidenceBuilder:
    """Build structured answer evidence from retrieved documents."""

    def __init__(self, max_content_chars: int = 1800):
        self.max_content_chars = max(300, int(max_content_chars or 1800))

    def build(
        self, question: str, evidence_documents: List[EvidenceDocument]
    ) -> AnswerEvidencePackage:
        items: List[AnswerEvidenceItem] = []
        recipe_evidence = aggregate_recipe_evidence(list(evidence_documents or []))
        for index, recipe in enumerate(recipe_evidence, start=1):
            content = (recipe.full_recipe_doc or "").strip()
            if not content:
                continue
            if len(content) > self.max_content_chars:
                content = content[: self.max_content_chars].rstrip() + "\n...[内容已截断]"
            items.append(
                AnswerEvidenceItem(
                    citation=f"菜谱证据 {index}",
                    recipe_id=recipe.recipe_id,
                    recipe_name=recipe.recipe_name,
                    confidence=recipe.confidence,
                    retrieval_sources=recipe.retrieval_sources,
                    matched_terms=recipe.matched_terms,
                    constraint_reasons=recipe.constraint_reasons,
                    graph_paths=recipe.graph_paths[:4],
                    evidence_units=[
                        {
                            "claim": unit.get("claim"),
                            "type": unit.get("evidence_type"),
                            "relation_type": unit.get("relation_type"),
                            "entities": unit.get("entities"),
                            "is_graph_evidence": unit.get("is_graph_evidence"),
                        }
                        for unit in recipe.evidence_units[:10]
                        if unit.get("claim")
                    ],
                    document_evidence=[
                        {
                            "doc_id": doc.doc_id,
                            "source": doc.source,
                            "score": doc.score,
                            "evidence_type": doc.evidence_type,
                        }
                        for doc in recipe.documents[:8]
                    ],
                    content=content,
                )
            )
        return AnswerEvidencePackage(question=question, items=items)

    def build_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
    ) -> AnswerEvidencePackage:
        return self.build(question, ensure_evidence_documents(documents))

    def build_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
    ) -> AnswerEvidencePackage:
        return self.build(question, evidence_documents)
