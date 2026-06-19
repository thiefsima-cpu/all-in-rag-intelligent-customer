from __future__ import annotations

from rag_modules.app.provider_components.contracts import (
    ApplicationServiceComponentProvider,
    InfrastructureComponentProvider,
    RetrievalComponentProvider,
)
from rag_modules.app.provider_components.infrastructure import (
    DefaultInfrastructureComponentProvider,
)
from rag_modules.app.provider_components.retrieval import DefaultRetrievalComponentProvider
from rag_modules.app.provider_components.services import (
    DefaultApplicationServiceComponentProvider,
)
from rag_modules.app.runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)
from rag_modules.configuration.testing import build_test_config


infrastructure_provider: InfrastructureComponentProvider = DefaultInfrastructureComponentProvider()
retrieval_provider: RetrievalComponentProvider = DefaultRetrievalComponentProvider()
service_provider: ApplicationServiceComponentProvider = DefaultApplicationServiceComponentProvider()


def accept_runtime_ports(
    graph_manager: Neo4jManagerPort,
    data_module: GraphDataModulePort,
    index_module: VectorIndexModulePort,
    query_tracer: QueryTracerPort,
) -> tuple[BuildRuntime, ServingRuntime, SystemInfrastructureView]:
    config = build_test_config()
    build_runtime = BuildRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    serving_runtime = ServingRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
        query_tracer=query_tracer,
    )
    infrastructure = SystemInfrastructureView(
        query_tracer=query_tracer,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    return build_runtime, serving_runtime, infrastructure


def accept_grouped_views(
    infrastructure: SystemInfrastructureView,
    retrieval: SystemRetrievalView,
    services: SystemServicesView,
) -> tuple[SystemInfrastructureView, SystemRetrievalView, SystemServicesView]:
    return infrastructure, retrieval, services
