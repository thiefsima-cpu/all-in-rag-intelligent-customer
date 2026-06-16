"""
Post-processing for retrieval results.

This module keeps reranking, evidence-unit scoring, graph-evidence preservation,
and final metadata normalization outside the router so routing stays focused on
strategy selection and retrieval orchestration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from langchain_core.documents import Document

from .dashscope_clients import DashScopeRerankClient
from .evidence import EvidenceUnitRanker, normalize_document_evidence

logger = logging.getLogger(__name__)


@dataclass
class RetrievalPostProcessContext:
    query: str
    strategy: str
    query_complexity: float
    relationship_intensity: float
    route_confidence: float
    query_plan: Optional[dict] = None


class RetrievalPostProcessor:
    """Apply ranking and evidence normalization to retrieved documents."""

    def __init__(self, config):
        self.config = config
        self.evidence_unit_ranker = EvidenceUnitRanker()
        self.rerank_client = None
        if getattr(config, "enable_rerank", False):
            self.rerank_client = DashScopeRerankClient(
                api_key=getattr(config, "api_key", ""),
                model_name=getattr(config, "rerank_model", "qwen3-vl-rerank"),
                base_url=getattr(config, "rerank_base_url", ""),
                timeout=getattr(config, "rerank_timeout_seconds", 20),
            )

    def post_process(
        self,
        documents: List[Document],
        top_k: int,
        context: RetrievalPostProcessContext,
    ) -> List[Document]:
        graph_candidates = [
            doc for doc in documents
            if doc.metadata.get("graph_evidence") or doc.metadata.get("recipe_graph_evidence")
        ]
        documents = self._rerank_documents(context.query, documents, top_k)
        if context.strategy in {"graph_rag", "combined"}:
            documents = self.evidence_unit_ranker.rank_documents(context.query, documents)
        documents = self._preserve_graph_evidence(
            documents=documents,
            graph_candidates=graph_candidates,
            strategy=context.strategy,
            top_k=top_k,
        )

        normalized_docs = []
        for doc in documents[:top_k]:
            metadata = dict(doc.metadata or {})
            metadata.update(
                {
                    "route_strategy": context.strategy,
                    "query_complexity": context.query_complexity,
                    "relationship_intensity": context.relationship_intensity,
                    "route_confidence": context.route_confidence,
                    "query_plan": context.query_plan or {},
                }
            )
            normalized_docs.append(
                normalize_document_evidence(
                    Document(page_content=doc.page_content, metadata=metadata),
                    route_strategy=context.strategy,
                )
            )
        return normalized_docs

    def _rerank_documents(self, query: str, documents: List[Document], top_k: int) -> List[Document]:
        if not documents or not self.rerank_client:
            return documents[:top_k]

        try:
            ordered_indices = self.rerank_client.rerank(
                query=query,
                documents=[self._build_rerank_text(doc) for doc in documents],
                top_n=min(top_k, len(documents)),
            )
        except Exception as exc:
            logger.warning("Rerank failed, keeping retrieval order: %s", exc)
            return documents

        reranked = []
        seen = set()
        for rank, index in enumerate(ordered_indices, start=1):
            if index < 0 or index >= len(documents) or index in seen:
                continue
            seen.add(index)
            metadata = dict(documents[index].metadata or {})
            metadata["rerank_rank"] = rank
            metadata["rerank_model"] = getattr(self.config, "rerank_model", "")
            reranked.append(Document(page_content=documents[index].page_content, metadata=metadata))
        reranked.extend(doc for index, doc in enumerate(documents) if index not in seen)
        return reranked

    @classmethod
    def _preserve_graph_evidence(
        cls,
        documents: List[Document],
        graph_candidates: List[Document],
        strategy: str,
        top_k: int,
    ) -> List[Document]:
        if strategy not in {"graph_rag", "combined"}:
            return documents
        if not graph_candidates:
            return documents

        top_docs = documents[:top_k]
        if any(doc.metadata.get("graph_evidence") or doc.metadata.get("recipe_graph_evidence") for doc in top_docs):
            return documents

        graph_doc = graph_candidates[0]
        graph_key = cls._document_key(graph_doc)
        without_duplicate = [
            doc for doc in documents
            if cls._document_key(doc) != graph_key
        ]
        insert_at = max(0, min(top_k, len(without_duplicate)) - 1)
        return without_duplicate[:insert_at] + [graph_doc] + without_duplicate[insert_at:]

    @staticmethod
    def _document_key(doc: Document) -> str:
        metadata = doc.metadata or {}
        return str(
            metadata.get("node_id")
            or metadata.get("recipe_id")
            or metadata.get("recipe_name")
            or f"hash::{hash((doc.page_content or '')[:200])}"
        )

    @staticmethod
    def _build_rerank_text(doc: Document, max_chars: int = 900) -> str:
        metadata = doc.metadata or {}
        graph_evidence = metadata.get("graph_evidence") or {}
        graph_parts = []
        if isinstance(graph_evidence, dict):
            description = graph_evidence.get("description")
            if description:
                graph_parts.append(str(description))
            relationships = graph_evidence.get("relationships") or []
            for rel in relationships[:8]:
                if isinstance(rel, dict):
                    graph_parts.append(str(rel.get("type") or "RELATED"))
                else:
                    graph_parts.append(str(rel))
            relationships_text = graph_evidence.get("relationships_text")
            if isinstance(relationships_text, list):
                graph_parts.extend(str(line) for line in relationships_text[:8])

        fields = [
            f"菜谱: {metadata.get('recipe_name') or metadata.get('name') or ''}",
            f"来源: {metadata.get('source') or metadata.get('search_method') or metadata.get('search_type') or ''}",
            f"证据类型: {metadata.get('evidence_type') or metadata.get('search_type') or ''}",
            f"匹配词: {', '.join(str(x) for x in (metadata.get('matched_terms') or metadata.get('matched_ingredients') or [])[:12])}",
            f"约束证据: {metadata.get('constraint_evidence') or metadata.get('constraint_reasons') or ''}",
            f"图证据: {'; '.join(graph_parts[:12])}",
            f"内容摘要: {(doc.page_content or '')[:max_chars]}",
        ]
        text = "\n".join(part for part in fields if part and not part.endswith(": "))
        return text[: max_chars * 2]
