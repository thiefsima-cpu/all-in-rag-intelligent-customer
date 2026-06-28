"""Vector retriever backed by Milvus, with optional one-hop neighbor enrichment."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, cast

from ...contracts import EvidenceDocument
from ...runtime_contracts import Neo4jDriverPort, VectorIndexModulePort
from ...safe_logging import log_failure

logger = logging.getLogger(__name__)


def _metadata_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


class VectorRetriever:
    """Wrap Milvus similarity search with graph neighbor enrichment."""

    def __init__(
        self,
        milvus_module: VectorIndexModulePort,
        driver: Neo4jDriverPort | None = None,
        database: str = "neo4j",
    ) -> None:
        self.milvus_module = milvus_module
        self.driver = driver
        self.database = database

    def search(self, query: str, top_k: int = 5) -> List[EvidenceDocument]:
        try:
            vector_docs = self.milvus_module.similarity_search(query, k=top_k * 2)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return []

        if not vector_docs:
            return []

        node_ids = []
        for result in vector_docs:
            node_id = _metadata_dict(result.get("metadata")).get("node_id")
            if node_id:
                node_ids.append(str(node_id))
        neighbor_map = self._batch_get_neighbors(node_ids) if node_ids else {}

        enhanced: List[EvidenceDocument] = []
        for result in vector_docs:
            content = str(result.get("text", "") or "")
            metadata = _metadata_dict(result.get("metadata"))
            node_id = str(metadata.get("node_id") or "")
            neighbors = neighbor_map.get(node_id, [])
            if neighbors:
                content += f"\n鐩稿叧淇℃伅: {', '.join(neighbors[:3])}"

            recipe_name = str(metadata.get("recipe_name") or metadata.get("name") or "")
            vector_score = _coerce_float(result.get("score", 0.0))
            metadata.update(
                {
                    "recipe_name": recipe_name,
                    "score": vector_score,
                    "search_type": "vector_enhanced",
                    "search_method": "vector",
                    "source": "vector",
                }
            )
            enhanced.append(
                EvidenceDocument(
                    content=content,
                    node_id=node_id,
                    recipe_name=recipe_name,
                    node_type=str(metadata.get("node_type") or metadata.get("entity_type") or ""),
                    score=vector_score,
                    search_type="vector_enhanced",
                    search_method="vector",
                    retrieval_level=str(metadata.get("retrieval_level") or "chunk"),
                    doc_id=str(metadata.get("doc_id") or ""),
                    recipe_id=str(metadata.get("recipe_id") or node_id),
                    source="vector",
                    metadata=metadata,
                )
            )

        return enhanced[:top_k]

    def _batch_get_neighbors(
        self, node_ids: List[str], max_neighbors: int = 3
    ) -> Dict[str, List[str]]:
        if not self.driver or not node_ids:
            return {}
        try:
            with self.driver.session(database=self.database) as session:
                query = """
                UNWIND $node_ids AS nid
                MATCH (n {nodeId: nid})-[r]-(neighbor)
                WITH nid, collect(DISTINCT neighbor.name)[0..$max_n] AS names
                RETURN nid, names
                """
                result = session.run(
                    query,
                    {"node_ids": list(set(node_ids)), "max_n": max_neighbors},
                )
                records = cast(Iterable[Mapping[str, Any]], result)
                return {
                    str(record["nid"]): [str(name) for name in record["names"] if name]
                    for record in records
                }
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return {}
