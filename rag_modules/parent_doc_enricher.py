"""Parent document enrichment for retrieval results."""

from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional

from langchain_core.documents import Document

from .retrieval.contracts import EvidenceDocument

logger = logging.getLogger(__name__)


def _iter_metadata_values(value: object) -> list[object]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


class ParentDocumentEnricher:
    """Replace top ranked chunks or graph snippets with full recipe documents."""

    def __init__(self, config, documents: Optional[Iterable[Document]] = None):
        self.config = config
        self.retrieval = config.retrieval
        self.parent_doc_map: Dict[str, Document] = {}
        if documents is not None:
            self.rebuild(documents)

    def rebuild(self, documents: Iterable[Document]) -> Dict[str, Document]:
        mapping: Dict[str, Document] = {}
        for doc in documents or []:
            node_id = doc.metadata.get("node_id")
            if node_id is not None:
                mapping[str(node_id)] = doc
        self.parent_doc_map = mapping
        return mapping

    def attach(self, docs: List[Document], top_n: Optional[int] = None) -> List[Document]:
        if not self.parent_doc_map:
            logger.warning("Parent document map is empty; parent-document attachment is skipped.")
            return docs

        top_n = self._resolved_top_n(top_n)
        max_chars = self._max_chars()
        enriched: List[Document] = []
        for index, doc in enumerate(docs):
            if index >= top_n:
                enriched.append(doc)
                continue
            parent = self.parent_doc_map.get(self._doc_parent_key(doc.metadata))
            if parent is None:
                enriched.append(doc)
                continue
            enriched.append(
                Document(
                    page_content=self._truncate_parent_content(
                        parent.page_content or "", max_chars
                    ),
                    metadata=dict(doc.metadata or {}),
                )
            )
        return enriched

    def attach_evidence(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        if not self.parent_doc_map:
            logger.warning("Parent document map is empty; parent-evidence attachment is skipped.")
            return docs

        top_n = self._resolved_top_n(top_n)
        max_chars = self._max_chars()
        enriched: List[EvidenceDocument] = []
        for index, doc in enumerate(docs):
            if index >= top_n:
                enriched.append(doc)
                continue
            parent = self.parent_doc_map.get(self._evidence_parent_key(doc))
            if parent is None:
                enriched.append(doc)
                continue
            metadata = dict(doc.metadata or {})
            metadata.setdefault("node_id", doc.node_id or parent.metadata.get("node_id"))
            metadata.setdefault(
                "recipe_name", doc.recipe_name or parent.metadata.get("recipe_name")
            )
            enriched.append(
                doc.copy_with(
                    content=self._truncate_parent_content(parent.page_content or "", max_chars),
                    node_id=doc.node_id or str(parent.metadata.get("node_id") or ""),
                    recipe_name=doc.recipe_name or str(parent.metadata.get("recipe_name") or ""),
                    metadata=metadata,
                )
            )
        return enriched

    def enrich_graph_documents(
        self, docs: List[Document], top_n: Optional[int] = None
    ) -> List[Document]:
        if not docs or not self.parent_doc_map:
            return docs

        enriched: List[Document] = []
        for doc in docs:
            replacement = self._find_parent(doc.metadata or {})
            if replacement is None:
                enriched.append(doc)
                continue
            metadata = dict(doc.metadata or {})
            metadata.update(replacement.metadata or {})
            metadata["search_source"] = doc.metadata.get(
                "search_source", doc.metadata.get("search_type", "graph")
            )
            graph_context = (doc.page_content or "").strip()
            parent_context = replacement.page_content or ""
            if graph_context and graph_context not in parent_context:
                page_content = f"{parent_context}\n\n[Graph retrieval evidence]\n{graph_context}"
            else:
                page_content = parent_context
            enriched.append(Document(page_content=page_content, metadata=metadata))

        return self.attach(enriched, top_n=top_n)

    def enrich_graph_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        if not docs or not self.parent_doc_map:
            return docs

        enriched: List[EvidenceDocument] = []
        for doc in docs:
            replacement = self._find_parent(doc.metadata or {})
            if replacement is None:
                enriched.append(doc)
                continue
            metadata = dict(doc.metadata or {})
            metadata.update(replacement.metadata or {})
            metadata["search_source"] = metadata.get(
                "search_source",
                doc.search_type or doc.search_method or doc.source or "graph",
            )
            graph_context = (doc.content or "").strip()
            parent_context = replacement.page_content or ""
            if graph_context and graph_context not in parent_context:
                content = f"{parent_context}\n\n[Graph retrieval evidence]\n{graph_context}"
            else:
                content = parent_context
            enriched.append(
                doc.copy_with(
                    content=content,
                    node_id=doc.node_id or str(metadata.get("node_id") or ""),
                    recipe_name=doc.recipe_name or str(metadata.get("recipe_name") or ""),
                    recipe_id=doc.recipe_id
                    or str(metadata.get("recipe_id") or metadata.get("node_id") or ""),
                    metadata=metadata,
                )
            )

        return self.attach_evidence(enriched, top_n=top_n)

    def _find_parent(self, metadata: Dict[str, object]) -> Optional[Document]:
        for node_id in _iter_metadata_values(metadata.get("recipe_node_ids")):
            parent = self.parent_doc_map.get(str(node_id))
            if parent:
                return parent
        for recipe_name in _iter_metadata_values(metadata.get("recipe_names")):
            for parent in self.parent_doc_map.values():
                if parent.metadata.get("recipe_name") == recipe_name:
                    return parent
        parent = self.parent_doc_map.get(self._doc_parent_key(metadata))
        if parent:
            return parent
        recipe_name = str(metadata.get("recipe_name") or "")
        if recipe_name:
            for candidate in self.parent_doc_map.values():
                if candidate.metadata.get("recipe_name") == recipe_name:
                    return candidate
        return None

    def _resolved_top_n(self, top_n: Optional[int]) -> int:
        return top_n if top_n is not None else self.retrieval.parent_doc_top_n

    def _max_chars(self) -> int:
        return int(self.retrieval.parent_doc_max_chars)

    @staticmethod
    def _truncate_parent_content(content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + "... (truncated parent document)"

    @staticmethod
    def _doc_parent_key(metadata: Dict[str, object]) -> str:
        return str(
            metadata.get("node_id") or metadata.get("parent_id") or metadata.get("recipe_id") or ""
        )

    def _evidence_parent_key(self, doc: EvidenceDocument) -> str:
        metadata = doc.metadata or {}
        return str(
            doc.node_id
            or doc.recipe_id
            or metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
            or ""
        )
