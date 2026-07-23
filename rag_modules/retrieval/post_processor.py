"""
Post-processing for retrieval results.

This module keeps reranking, evidence-unit scoring, graph-evidence preservation,
and final metadata normalization outside the router so routing stays focused on
strategy selection and retrieval orchestration.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import List, Optional

from ..contracts import EvidenceDocument, RequestControl
from ..evidence_processing import EvidenceUnitRanker, normalize_evidence_document
from ..kernel.json_types import as_string_list
from ..safe_logging import log_failure
from .ports import RerankClientPort
from .runtime_profile import RetrievalPostProcessSettings

logger = logging.getLogger(__name__)


@dataclass
class RetrievalPostProcessContext:
    query: str
    strategy: str
    query_complexity: float
    relationship_intensity: float
    route_confidence: float
    query_plan: Optional[dict] = None
    control: RequestControl | None = None


@dataclass(frozen=True)
class RetrievalPostProcessResult:
    documents: tuple[EvidenceDocument, ...]
    rerank_attempted: bool
    rerank_succeeded: bool
    rerank_latency_ms: float | None


class RetrievalPostProcessor:
    """Apply ranking and evidence normalization to retrieved documents."""

    def __init__(
        self,
        config=None,
        *,
        settings: RetrievalPostProcessSettings | None = None,
        rerank_client: RerankClientPort | None = None,
    ):
        self.config = config
        self.settings = settings or RetrievalPostProcessSettings.from_config(config)
        self.evidence_unit_ranker = EvidenceUnitRanker()
        self.rerank_client = rerank_client if self.settings.enable_rerank else None

    def post_process(
        self,
        evidence_documents: List[EvidenceDocument],
        top_k: int,
        context: RetrievalPostProcessContext,
    ) -> List[EvidenceDocument]:
        return list(
            self.post_process_with_trace(
                evidence_documents,
                top_k=top_k,
                context=context,
            ).documents
        )

    def post_process_with_trace(
        self,
        evidence_documents: List[EvidenceDocument],
        top_k: int,
        context: RetrievalPostProcessContext,
    ) -> RetrievalPostProcessResult:
        graph_candidates = [
            doc for doc in evidence_documents if doc.graph_evidence or doc.domain_graph_evidence
        ]
        (
            reranked_documents,
            rerank_attempted,
            rerank_succeeded,
            rerank_latency_ms,
        ) = self._rerank_documents(
            query=context.query,
            documents=list(evidence_documents or []),
            top_k=top_k,
            control=context.control,
        )
        if context.strategy in {"graph_rag", "combined"}:
            reranked_documents = self.evidence_unit_ranker.rank_evidence_documents(
                context.query,
                reranked_documents,
            )
        reranked_documents = self._preserve_graph_evidence(
            documents=reranked_documents,
            graph_candidates=graph_candidates,
            strategy=context.strategy,
            top_k=top_k,
            preserve_graph_evidence=self.settings.should_preserve_graph_evidence(context.strategy),
            preserve_strategies=self.settings.graph_preservation_strategies,
        )

        normalized_docs: List[EvidenceDocument] = []
        for doc in reranked_documents[:top_k]:
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
                normalize_evidence_document(
                    replace(
                        doc,
                        metadata=metadata,
                        route_strategy=context.strategy,
                    ),
                    route_strategy=context.strategy,
                )
            )
        return RetrievalPostProcessResult(
            documents=tuple(normalized_docs),
            rerank_attempted=rerank_attempted,
            rerank_succeeded=rerank_succeeded,
            rerank_latency_ms=rerank_latency_ms,
        )

    def _rerank_documents(
        self,
        query: str,
        documents: List[EvidenceDocument],
        top_k: int,
        control: RequestControl | None = None,
    ) -> tuple[List[EvidenceDocument], bool, bool, float | None]:
        if not documents or not self.rerank_client:
            return documents[:top_k], False, False, None
        if control is not None:
            control.raise_if_cancelled()

        rerank_started = time.perf_counter()
        try:
            ordered_indices = self.rerank_client.rerank(
                query=query,
                documents=[self._build_rerank_text(doc) for doc in documents],
                top_n=min(top_k, len(documents)),
                control=control,
                timeout_seconds=control.remaining_seconds() if control is not None else None,
            )
            if control is not None:
                control.raise_if_cancelled()
        except Exception as exc:
            rerank_latency_ms = round((time.perf_counter() - rerank_started) * 1000, 2)
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return documents, True, False, rerank_latency_ms

        rerank_latency_ms = round((time.perf_counter() - rerank_started) * 1000, 2)
        reranked: List[EvidenceDocument] = []
        seen = set()
        for rank, index in enumerate(ordered_indices, start=1):
            if index < 0 or index >= len(documents) or index in seen:
                continue
            seen.add(index)
            metadata = dict(documents[index].metadata or {})
            metadata["rerank_rank"] = rank
            metadata["rerank_model"] = self.settings.rerank_model
            reranked.append(replace(documents[index], metadata=metadata))
        reranked.extend(doc for index, doc in enumerate(documents) if index not in seen)
        return reranked, True, True, rerank_latency_ms

    @classmethod
    def _preserve_graph_evidence(
        cls,
        documents: List[EvidenceDocument],
        graph_candidates: List[EvidenceDocument],
        strategy: str,
        top_k: int,
        preserve_graph_evidence: bool = True,
        preserve_strategies: tuple[str, ...] = ("graph_rag", "combined"),
    ) -> List[EvidenceDocument]:
        if not preserve_graph_evidence:
            return documents
        if str(strategy or "") not in preserve_strategies:
            return documents
        if not graph_candidates:
            return documents

        top_docs = documents[:top_k]
        if any(doc.graph_evidence or doc.domain_graph_evidence for doc in top_docs):
            return documents

        graph_doc = graph_candidates[0]
        graph_key = cls._document_key(graph_doc)
        without_duplicate = [doc for doc in documents if cls._document_key(doc) != graph_key]
        insert_at = max(0, min(top_k, len(without_duplicate)) - 1)
        return without_duplicate[:insert_at] + [graph_doc] + without_duplicate[insert_at:]

    @staticmethod
    def _document_key(doc: EvidenceDocument) -> str:
        metadata = doc.metadata or {}
        return str(
            doc.node_id
            or doc.entity_id
            or doc.entity_name
            or metadata.get("node_id")
            or metadata.get("recipe_id")
            or metadata.get("recipe_name")
            or f"hash::{hash((doc.content or '')[:200])}"
        )

    @staticmethod
    def _build_rerank_text(doc: EvidenceDocument, max_chars: int = 900) -> str:
        metadata = doc.metadata or {}
        graph_evidence = doc.graph_evidence or metadata.get("graph_evidence") or {}
        graph_parts = []
        if isinstance(graph_evidence, dict):
            description = graph_evidence.get("description")
            if description:
                graph_parts.append(str(description))
            raw_relationships = graph_evidence.get("relationships")
            relationships = raw_relationships if isinstance(raw_relationships, list) else []
            for rel in relationships[:8]:
                if isinstance(rel, dict):
                    graph_parts.append(str(rel.get("type") or "RELATED"))
                else:
                    graph_parts.append(str(rel))
            relationships_text = graph_evidence.get("relationships_text")
            if isinstance(relationships_text, list):
                graph_parts.extend(str(line) for line in relationships_text[:8])

        fields = [
            f"实体: {doc.entity_name or metadata.get('name') or ''}",
            f"来源: {doc.source or metadata.get('search_method') or metadata.get('search_type') or ''}",
            f"证据类型: {doc.evidence_type or metadata.get('search_type') or ''}",
            f"匹配词: {', '.join((doc.matched_terms or as_string_list(metadata.get('matched_ingredients')))[:12])}",
            f"约束证据: {doc.constraint_evidence or metadata.get('constraint_reasons') or ''}",
            f"图谱证据: {'; '.join(graph_parts[:12])}",
            f"内容摘要: {(doc.content or '')[:max_chars]}",
        ]
        text = "\n".join(part for part in fields if part and not part.endswith(": "))
        return text[: max_chars * 2]
