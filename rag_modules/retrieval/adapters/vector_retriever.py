"""Vector retriever backed by Milvus, with optional one-hop neighbor enrichment."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import cast

from ...contracts import EvidenceDocument, RetrievalRequest
from ...safe_logging import log_failure
from ..ports import Neo4jDriverPort, VectorIndexModulePort

logger = logging.getLogger(__name__)


def _metadata_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item) for item in value if item]


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
        self.domain_name = str(getattr(milvus_module, "domain_name", "recipe") or "recipe")

    def search(self, request: RetrievalRequest) -> list[EvidenceDocument]:
        control = request.control
        if control is not None:
            control.raise_if_cancelled()
        try:
            vector_docs = self.milvus_module.similarity_search(request)
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
        if control is not None:
            control.raise_if_cancelled()

        node_ids = []
        for result in vector_docs:
            node_id = _metadata_dict(result.get("metadata")).get("node_id")
            if node_id:
                node_ids.append(str(node_id))
        neighbor_map = self._batch_get_neighbors(request, node_ids) if node_ids else {}

        enhanced: list[EvidenceDocument] = []
        for result in vector_docs:
            content = str(result.get("text", "") or "")
            metadata = _metadata_dict(result.get("metadata"))
            node_id = str(metadata.get("node_id") or "")
            neighbors = neighbor_map.get(node_id, [])
            if neighbors:
                content += f"\n鐩稿叧淇℃伅: {', '.join(neighbors[:3])}"

            entity_name = str(
                metadata.get("entity_name")
                or metadata.get("recipe_name")
                or metadata.get("name")
                or ""
            )
            entity_id = str(metadata.get("entity_id") or metadata.get("recipe_id") or node_id)
            entity_type = str(metadata.get("entity_type") or metadata.get("node_type") or "")
            vector_score = _coerce_float(result.get("score", 0.0))
            metadata.update(
                {
                    "entity_id": entity_id,
                    "entity_name": entity_name,
                    "entity_type": entity_type,
                    "score": vector_score,
                    "search_type": "vector_enhanced",
                    "search_method": "vector",
                    "source": "vector",
                }
            )
            enhanced.append(
                EvidenceDocument(
                    content=content,
                    entity_id=entity_id,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    node_id=node_id,
                    node_type=entity_type,
                    score=vector_score,
                    search_type="vector_enhanced",
                    search_method="vector",
                    retrieval_level=str(metadata.get("retrieval_level") or "chunk"),
                    doc_id=str(metadata.get("doc_id") or ""),
                    source="vector",
                    metadata=metadata,
                )
            )

        return enhanced[: request.effective_candidate_k]

    def _batch_get_neighbors(
        self,
        request: RetrievalRequest,
        node_ids: list[str],
        max_neighbors: int = 3,
    ) -> dict[str, list[str]]:
        if not self.driver or not node_ids:
            return {}
        control = request.control
        if control is not None:
            control.raise_if_cancelled()
        try:
            with self.driver.session(database=self.database) as session:
                query = """
                UNWIND $node_ids AS nid
                MATCH (n {nodeId: nid})
                WHERE n.domain = $domain_name
                   OR ($domain_name = 'recipe' AND n.domain IS NULL)
                MATCH (n)-[r]-(neighbor)
                WHERE neighbor.domain = $domain_name
                   OR ($domain_name = 'recipe' AND neighbor.domain IS NULL)
                WITH nid, collect(DISTINCT neighbor.name)[0..$max_n] AS names
                RETURN nid, names
                """
                result = session.run(
                    query,
                    {
                        "node_ids": list(set(node_ids)),
                        "max_n": max_neighbors,
                        "domain_name": self.domain_name,
                    },
                    timeout=control.remaining_seconds() if control is not None else None,
                )
                records = cast(Iterable[Mapping[str, object]], result)
                return {
                    str(record.get("nid") or ""): _string_list(record.get("names"))
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
