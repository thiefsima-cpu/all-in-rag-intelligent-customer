"""Vector retriever backed by Milvus, with optional one-hop neighbor enrichment."""

from __future__ import annotations

import logging
from typing import Dict, List

from ...runtime_contracts import Neo4jDriverPort
from ..contracts import EvidenceDocument

logger = logging.getLogger(__name__)


class VectorRetriever:
    """Wrap Milvus similarity search with graph neighbor enrichment."""

    def __init__(
        self,
        milvus_module,
        driver: Neo4jDriverPort | None = None,
        database: str = "neo4j",
    ):
        self.milvus_module = milvus_module
        self.driver = driver
        self.database = database

    def search(self, query: str, top_k: int = 5) -> List[EvidenceDocument]:
        try:
            vector_docs = self.milvus_module.similarity_search(query, k=top_k * 2)
        except Exception as exc:
            logger.error("Vector retrieval failed: %s", exc)
            return []

        if not vector_docs:
            return []

        node_ids = [
            str(result.get("metadata", {}).get("node_id") or "")
            for result in vector_docs
            if result.get("metadata", {}).get("node_id")
        ]
        neighbor_map = self._batch_get_neighbors(node_ids) if node_ids else {}

        enhanced: List[EvidenceDocument] = []
        for result in vector_docs:
            content = str(result.get("text", "") or "")
            metadata = dict(result.get("metadata", {}) or {})
            node_id = str(metadata.get("node_id") or "")
            neighbors = neighbor_map.get(node_id, [])
            if neighbors:
                content += f"\n鐩稿叧淇℃伅: {', '.join(neighbors[:3])}"

            recipe_name = str(metadata.get("recipe_name") or metadata.get("name") or "")
            vector_score = float(result.get("score", 0.0) or 0.0)
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

    def _batch_get_neighbors(self, node_ids: List[str], max_neighbors: int = 3) -> Dict[str, List[str]]:
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
                return {
                    str(record["nid"]): [str(name) for name in record["names"] if name]
                    for record in result
                }
        except Exception as exc:
            logger.error("Batch neighbor lookup failed: %s", exc)
            return {}
