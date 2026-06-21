"""Fusion utilities for multi-retriever evidence results."""

from __future__ import annotations

from typing import Dict, List, Tuple

from .retrieval.contracts import EvidenceDocument


class FusionRanker:
    """Rank and merge retrieval results from multiple ranked lists."""

    def __init__(self, rrf_k: int = 60):
        self.rrf_k = rrf_k

    def rrf_merge(
        self,
        ranked_lists: List[Tuple[str, List[EvidenceDocument]]],
        top_k: int,
    ) -> List[EvidenceDocument]:
        best_rank_per_source: Dict[str, Dict[str, int]] = {}
        chunk_hits_per_source: Dict[str, Dict[str, int]] = {}
        best_doc_info: Dict[str, Tuple[int, int, EvidenceDocument]] = {}

        for source_priority, (source_name, ranked_docs) in enumerate(ranked_lists):
            for rank, doc in enumerate(ranked_docs, start=1):
                doc_id = self._doc_id(doc)

                if doc_id not in best_rank_per_source:
                    best_rank_per_source[doc_id] = {}
                    chunk_hits_per_source[doc_id] = {}

                curr_best = best_rank_per_source[doc_id].get(source_name)
                if curr_best is None or rank < curr_best:
                    best_rank_per_source[doc_id][source_name] = rank

                chunk_hits_per_source[doc_id][source_name] = (
                    chunk_hits_per_source[doc_id].get(source_name, 0) + 1
                )

                new_key = (rank, source_priority)
                if doc_id not in best_doc_info or new_key < (
                    best_doc_info[doc_id][0],
                    best_doc_info[doc_id][1],
                ):
                    best_doc_info[doc_id] = (rank, source_priority, doc)

        rrf_scores: Dict[str, float] = {
            doc_id: sum(1.0 / (self.rrf_k + rank) for rank in source_ranks.values())
            for doc_id, source_ranks in best_rank_per_source.items()
        }
        sorted_ids = sorted(rrf_scores.keys(), key=lambda doc_id: rrf_scores[doc_id], reverse=True)

        merged: List[EvidenceDocument] = []
        for doc_id in sorted_ids[:top_k]:
            _, _, source_doc = best_doc_info[doc_id]
            metadata = dict(source_doc.metadata or {})
            metadata["rrf_score"] = rrf_scores[doc_id]
            metadata["rrf_sources"] = list(best_rank_per_source[doc_id].keys())
            metadata["rrf_ranks"] = dict(best_rank_per_source[doc_id])
            metadata["rrf_chunk_hits"] = dict(chunk_hits_per_source[doc_id])
            metadata["final_score"] = rrf_scores[doc_id]
            merged.append(
                source_doc.copy_with(
                    score=float(metadata.get("final_score") or source_doc.score or 0.0),
                    metadata=metadata,
                )
            )
        return merged

    @staticmethod
    def _doc_id(doc: EvidenceDocument) -> str:
        return doc.document_key()
