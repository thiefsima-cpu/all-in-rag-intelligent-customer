"""
Index lifecycle services for hybrid retrieval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

from ..parent_doc_enricher import ParentDocumentEnricher
from ..retrieval_cache import RetrievalCacheStore
from ..safe_logging import log_failure
from .adapters import BM25Retriever
from .evidence import RecipeConstraintMatcher

logger = logging.getLogger(__name__)


@dataclass
class HybridIndexArtifacts:
    bm25: Any = None
    bm25_corpus_docs: List[Document] = field(default_factory=list)
    graph_indexed: bool = False
    parent_doc_map: Dict[str, Document] = field(default_factory=dict)
    recipe_matcher: Optional[RecipeConstraintMatcher] = None


class HybridIndexService:
    """Build, load, and persist hybrid retrieval indexes."""

    def __init__(
        self,
        *,
        config,
        data_module,
        graph_indexing,
        cache_store: RetrievalCacheStore,
        bm25_retriever: BM25Retriever,
        parent_enricher: ParentDocumentEnricher,
    ) -> None:
        self.config = config
        self.storage = config.storage
        self.data_module = data_module
        self.graph_indexing = graph_indexing
        self.cache_store = cache_store
        self.bm25_retriever = bm25_retriever
        self.parent_enricher = parent_enricher
        self.graph_indexed = False
        self.database = self.storage.neo4j_database

    def initialize(self, chunks: List[Document], driver) -> HybridIndexArtifacts:
        if self.storage.enable_index_cache:
            cached = self.load_index_cache(chunks)
            if cached:
                return cached

        if chunks:
            self.bm25_retriever.build(chunks)

        self._build_graph_index(driver)
        artifacts = self._build_artifacts()

        if self.storage.enable_index_cache:
            self.save_index_cache(chunks, artifacts)
        return artifacts

    def load_index_cache(self, chunks: List[Document]) -> Optional[HybridIndexArtifacts]:
        payload = self.cache_store.load(chunks)
        if not payload:
            return None

        try:
            self.graph_indexed = self.graph_indexing.from_cache_dict(payload)
            parent_doc_map = (
                self._deserialize_parent_documents(payload.get("parent_documents"))
                or self._build_parent_doc_map()
            )
            self.parent_enricher.parent_doc_map = parent_doc_map
            recipe_matcher = RecipeConstraintMatcher(list(parent_doc_map.values()))
            if not self.restore_bm25_retriever(payload):
                return None
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return None

        artifacts = HybridIndexArtifacts(
            bm25=self.bm25_retriever.bm25,
            bm25_corpus_docs=list(self.bm25_retriever.corpus_docs),
            graph_indexed=self.graph_indexed,
            parent_doc_map=parent_doc_map,
            recipe_matcher=recipe_matcher,
        )
        if not (
            artifacts.bm25 is not None and artifacts.bm25_corpus_docs and artifacts.graph_indexed
        ):
            return None
        return artifacts

    def save_index_cache(self, chunks: List[Document], artifacts: HybridIndexArtifacts) -> None:
        payload = {
            "bm25_retriever": self.bm25_retriever.to_cache_dict(),
            "parent_documents": self._serialize_parent_documents(artifacts.parent_doc_map),
            **self.graph_indexing.to_cache_dict(),
        }
        self.cache_store.save(chunks, payload)

    def restore_bm25_retriever(self, payload: Dict[str, Any]) -> bool:
        bm25_cache = payload.get("bm25_retriever")
        return bool(
            isinstance(bm25_cache, dict) and self.bm25_retriever.from_cache_dict(bm25_cache)
        )

    @staticmethod
    def _serialize_parent_documents(
        parent_doc_map: Dict[str, Document],
    ) -> Dict[str, Dict[str, Any]]:
        return {
            str(node_id): {
                "page_content": str(document.page_content or ""),
                "metadata": dict(document.metadata or {}),
            }
            for node_id, document in (parent_doc_map or {}).items()
        }

    @staticmethod
    def _deserialize_parent_documents(payload: Any) -> Dict[str, Document]:
        if not isinstance(payload, dict):
            return {}
        try:
            return {
                str(node_id): Document(
                    page_content=str(item.get("page_content") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for node_id, item in payload.items()
                if isinstance(item, dict)
            }
        except (TypeError, ValueError):
            return {}

    def _build_artifacts(self) -> HybridIndexArtifacts:
        parent_doc_map = self._build_parent_doc_map()
        self.parent_enricher.parent_doc_map = parent_doc_map
        return HybridIndexArtifacts(
            bm25=self.bm25_retriever.bm25,
            bm25_corpus_docs=list(self.bm25_retriever.corpus_docs),
            graph_indexed=self.graph_indexed,
            parent_doc_map=parent_doc_map,
            recipe_matcher=RecipeConstraintMatcher(list(parent_doc_map.values())),
        )

    def _build_parent_doc_map(self) -> Dict[str, Document]:
        docs = getattr(self.data_module, "documents", None) or []
        return self.parent_enricher.rebuild(docs)

    def _build_graph_index(self, driver) -> None:
        if self.graph_indexed:
            return

        logger.info("Building hybrid graph index...")
        try:
            recipes = self.data_module.recipes
            ingredients = self.data_module.ingredients
            cooking_steps = self.data_module.cooking_steps
            self.graph_indexing.create_entity_key_values(recipes, ingredients, cooking_steps)
            relationships = self._extract_relationships_from_graph(driver)
            self.graph_indexing.create_relation_key_values(relationships)
            self.graph_indexing.deduplicate_entities_and_relations()
            self.graph_indexed = True
            logger.info("Graph index ready: %s", self.graph_indexing.get_statistics())
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )

    def _extract_relationships_from_graph(self, driver) -> List[Tuple[str, str, str]]:
        relationships: List[Tuple[str, str, str]] = []
        if driver is None:
            return relationships

        try:
            with driver.session(database=self.database) as session:
                query = """
                MATCH (source)-[r]->(target)
                WHERE source.nodeId >= '200000000' OR target.nodeId >= '200000000'
                RETURN source.nodeId as source_id, type(r) as relation_type, target.nodeId as target_id
                """
                for record in session.run(query):
                    relationships.append(
                        (
                            str(record["source_id"]),
                            str(record["relation_type"]),
                            str(record["target_id"]),
                        )
                    )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )

        return relationships
