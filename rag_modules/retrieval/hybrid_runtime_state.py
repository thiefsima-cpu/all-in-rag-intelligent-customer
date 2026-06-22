"""State models for hybrid retrieval runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from ..domain.shared.query_constraints import RecipeConstraintMatcher
from ..runtime_contracts import Neo4jDriverPort
from .adapters import VectorRetriever
from .dual_level_retriever import DualLevelRetriever


@dataclass
class HybridRetrievalState:
    """Mutable runtime state for hybrid retrieval resources and indexes."""

    driver: Neo4jDriverPort | None = None
    owns_driver: bool = False
    bm25: Optional[BM25Okapi] = None
    bm25_corpus_docs: List[Document] = field(default_factory=list)
    graph_indexed: bool = False
    parent_doc_map: Dict[str, Document] = field(default_factory=dict)
    recipe_matcher: Optional[RecipeConstraintMatcher] = None
    vector_retriever: Optional[VectorRetriever] = None
    dual_level_service: Optional[DualLevelRetriever] = None


__all__ = ["HybridRetrievalState"]
