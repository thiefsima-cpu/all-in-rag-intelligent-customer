"""Split graph-preparation package for build-time document materialization."""

from typing import cast

from ...contracts.graph_preparation import LoadedGraphData
from .chunker import DomainDocumentChunker
from .domain_loader import DomainDocumentBuilder, DomainGraphDataLoader
from .models import GraphRelation
from .module import GraphDataPreparationModule
from .state import (
    DomainDocumentBuilder as DomainDocumentBuilderContract,
)
from .state import (
    DomainDocumentChunker as DomainDocumentChunkerContract,
)
from .state import (
    GraphDataLoader,
    GraphPreparationState,
)
from .statistics import GraphPreparationStatisticsService


def create_domain_build_collaborators(domain_pack):
    """Resolve build adapters from the adapter key owned by a DomainPack."""

    chunker = DomainDocumentChunker()
    loader_factory = getattr(domain_pack, "build_loader_factory", None)
    builder_factory = getattr(domain_pack, "build_document_builder_factory", None)
    if loader_factory is not None and builder_factory is not None:
        return (
            cast(GraphDataLoader, loader_factory()),
            cast(DomainDocumentBuilderContract, builder_factory()),
            chunker,
        )
    if domain_pack.build_adapter == "ontology":
        return (
            DomainGraphDataLoader(
                domain_pack.ontology,
                domain_name=domain_pack.name,
                primary_group=domain_pack.build_data_view.primary_group,
            ),
            DomainDocumentBuilder(domain_pack.document_mapper),
            chunker,
        )
    raise ValueError(f"Unsupported domain build adapter: {domain_pack.build_adapter}")


__all__ = [
    "GraphDataPreparationModule",
    "GraphDataLoader",
    "DomainDocumentBuilderContract",
    "DomainDocumentChunkerContract",
    "DomainDocumentBuilder",
    "DomainGraphDataLoader",
    "GraphPreparationState",
    "GraphRelation",
    "LoadedGraphData",
    "DomainDocumentChunker",
    "GraphPreparationStatisticsService",
    "create_domain_build_collaborators",
]
