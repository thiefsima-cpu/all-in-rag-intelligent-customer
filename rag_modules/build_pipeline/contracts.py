"""Build-pipeline contracts for artifact materialization and graph schema sync."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, Sequence

from ..text_document import TextDocument

if TYPE_CHECKING:
    from .document_artifacts.models import DocumentArtifactResult


class DocumentArtifactBuilderPort(Protocol):
    """Materialize or load document/chunk artifacts for build workflows."""

    def build_or_load(self, data_module: Any) -> DocumentArtifactResult: ...


@dataclass(slots=True)
class SemanticGraphSchemaSyncResult:
    enabled: bool
    recipes: int = 0
    nodes: int = 0
    relationships: int = 0
    error: str = ""

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enabled": self.enabled,
        }
        if self.enabled and not self.error:
            payload.update(
                {
                    "recipes": self.recipes,
                    "nodes": self.nodes,
                    "relationships": self.relationships,
                }
            )
        if self.error:
            payload["error"] = self.error
        return payload


class SemanticGraphSchemaSyncPort(Protocol):
    """Persist semantic graph schema derived from materialized documents."""

    def sync_from_documents(
        self,
        documents: Sequence[TextDocument],
    ) -> SemanticGraphSchemaSyncResult: ...


__all__ = [
    "DocumentArtifactBuilderPort",
    "SemanticGraphSchemaSyncPort",
    "SemanticGraphSchemaSyncResult",
]
