"""Statistics helpers for graph-preparation state."""

from __future__ import annotations

from ...contracts.graph_preparation import GraphPreparationStats as _GraphPreparationStats
from ...domains.contracts import DomainBuildDataView
from ...kernel.json_types import JsonObject, coerce_int, coerce_json_value
from .state import GraphPreparationState

UNKNOWN_VALUE = "未知"


class GraphPreparationStatisticsService:
    """Compute neutral build diagnostics plus a DomainPack-owned metric projection."""

    def __init__(self, *, domain_name: str, data_view: DomainBuildDataView) -> None:
        self.domain_name = str(domain_name)
        self.data_view = data_view

    def build(self, state: GraphPreparationState) -> _GraphPreparationStats:
        entities = state.entities
        entity_types: dict[str, int] = {}
        for entity in entities:
            for label in entity.labels:
                entity_types[label] = entity_types.get(label, 0) + 1

        document_types: dict[str, int] = {}
        for document in state.documents:
            document_type = str(
                document.metadata.get("document_type")
                or document.metadata.get("doc_type")
                or UNKNOWN_VALUE
            )
            document_types[document_type] = document_types.get(document_type, 0) + 1

        return _GraphPreparationStats(
            domain_name=self.domain_name,
            total_entities=len(entities),
            total_documents=len(state.documents),
            total_chunks=len(state.chunks),
            entity_types=entity_types,
            document_types=document_types,
            avg_content_length=_average_metadata(state.documents, "content_length"),
            avg_chunk_size=_average_metadata(state.chunks, "chunk_size"),
            include_distributions=bool(state.documents or entities),
            domain_metrics=self._domain_metrics(state),
        )

    def _domain_metrics(self, state: GraphPreparationState) -> JsonObject:
        groups = {
            self.data_view.primary_group: state.primary_entities,
            **state.related_entity_groups,
        }
        metrics: JsonObject = {
            metric_name: len(groups.get(group_name, ()))
            for group_name, metric_name in self.data_view.count_metrics
        }
        for metadata_field, metric_name in self.data_view.distribution_metrics:
            distribution: dict[str, int] = {}
            for document in state.documents:
                value = str(document.metadata.get(metadata_field, UNKNOWN_VALUE) or UNKNOWN_VALUE)
                distribution[value] = distribution.get(value, 0) + 1
            metrics[metric_name] = coerce_json_value(distribution)
        return metrics


def _average_metadata(documents: list, field_name: str) -> float:
    if not documents:
        return 0.0
    return sum(coerce_int(document.metadata.get(field_name), 0) for document in documents) / len(
        documents
    )


__all__ = ["GraphPreparationStatisticsService"]
