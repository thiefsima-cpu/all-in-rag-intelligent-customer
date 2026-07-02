"""Milvus vector search operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from ...contracts import RetrievalRequest
from ...runtime.json_types import JsonObject, JsonValue
from ...safe_logging import log_failure
from .contracts import MilvusOperationHost

logger = logging.getLogger(__name__)


class _MilvusSearchOperations(MilvusOperationHost):
    def similarity_search(self, request: RetrievalRequest) -> list[JsonObject]:
        if not self.collection_created:
            raise ValueError("Vector collection must be built or loaded before search.")

        try:
            control = request.control
            if control is not None:
                control.raise_if_cancelled()

            requested_k = max(1, int(request.effective_candidate_k or 1))
            if self.vector_search_max_k:
                requested_k = min(requested_k, max(1, int(self.vector_search_max_k)))
            search_ef = max(int(self.vector_search_ef or 64), requested_k)

            query_vector = self.embeddings.embed_query(
                request.query,
                timeout_seconds=control.remaining_seconds() if control is not None else None,
            )
            filter_expr = _filter_expression(_metadata_filter(request.metadata))
            search_params = {"metric_type": "COSINE", "params": {"ef": search_ef}}
            search_kwargs: dict[str, object] = {
                "collection_name": self.collection_name,
                "data": [query_vector],
                "anns_field": "vector",
                "limit": requested_k,
                "output_fields": [
                    "text",
                    "node_id",
                    "recipe_name",
                    "node_type",
                    "category",
                    "cuisine_type",
                    "difficulty",
                    "doc_type",
                    "chunk_id",
                    "parent_id",
                ],
                "search_params": search_params,
            }
            if filter_expr:
                search_kwargs["filter"] = filter_expr
            if control is not None:
                control.raise_if_cancelled()
                search_kwargs["timeout"] = control.remaining_seconds()

            results = self.client.search(**search_kwargs)
            if control is not None:
                control.raise_if_cancelled()
            return _format_hits(results)

        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            return []


def _metadata_filter(metadata: Mapping[str, object]) -> dict[str, JsonValue]:
    raw_filter = metadata.get("milvus_filter") or metadata.get("filters")
    if not isinstance(raw_filter, dict):
        return {}
    return {str(key): value for key, value in raw_filter.items()}


def _filter_expression(filters: Mapping[str, JsonValue]) -> str:
    filter_conditions: list[str] = []
    for key, value in filters.items():
        if isinstance(value, str):
            filter_conditions.append(f'{key} == "{value}"')
        elif isinstance(value, (int, float)):
            filter_conditions.append(f"{key} == {value}")
        elif isinstance(value, list):
            string_values = [item for item in value if isinstance(item, str)]
            if len(string_values) == len(value):
                value_str = '", "'.join(string_values)
                filter_conditions.append(f'{key} in ["{value_str}"]')
            else:
                value_str = ", ".join(map(str, value))
                filter_conditions.append(f"{key} in [{value_str}]")
    return " and ".join(filter_conditions)


def _format_hits(results: object) -> list[JsonObject]:
    formatted_results: list[JsonObject] = []
    if not results:
        return formatted_results
    first_result = results[0] if isinstance(results, list) and results else []
    for hit in first_result:
        entity = hit["entity"]
        formatted_results.append(
            {
                "id": hit["id"],
                "score": hit["distance"],
                "text": entity["text"],
                "metadata": {
                    "node_id": entity["node_id"],
                    "recipe_name": entity["recipe_name"],
                    "node_type": entity["node_type"],
                    "category": entity["category"],
                    "cuisine_type": entity["cuisine_type"],
                    "difficulty": entity["difficulty"],
                    "doc_type": entity["doc_type"],
                    "chunk_id": entity["chunk_id"],
                    "parent_id": entity["parent_id"],
                },
            }
        )
    return formatted_results
