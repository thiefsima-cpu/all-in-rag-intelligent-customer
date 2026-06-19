"""Retrieval component providers."""

from __future__ import annotations

from typing import Any

from ...configuration.models import GraphRAGConfig

from ...graph.retrieval import GraphRAGRetrieval
from ...retrieval import HybridRetrievalModule
from ...query_understanding.service import QueryUnderstandingService
from ...retrieval.runtime_profile import RetrievalRuntimeProfile
from ...routing import RoutingWorkflowProtocol, RoutingWorkflowService
from ..runtime_contracts import GraphDataModulePort, Neo4jManagerPort, VectorIndexModulePort


class DefaultRetrievalComponentProvider:
    """Default retrieval module providers."""

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: Any,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> HybridRetrievalModule:
        return HybridRetrievalModule(
            config=config,
            milvus_module=milvus_module,
            data_module=data_module,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=retrieval_profile,
        )

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: Any,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> GraphRAGRetrieval:
        return GraphRAGRetrieval(
            config=config,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=retrieval_profile,
        )

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: HybridRetrievalModule,
        graph_rag_retrieval: GraphRAGRetrieval,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol:
        return RoutingWorkflowService(
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            config=config,
            retrieval_profile=retrieval_profile,
            query_understanding_service=query_understanding_service,
        )

    def provide_query_router(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: HybridRetrievalModule,
        graph_rag_retrieval: GraphRAGRetrieval,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingService,
    ) -> RoutingWorkflowProtocol:
        return self.provide_routing_workflow(
            config=config,
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            retrieval_profile=retrieval_profile,
            query_understanding_service=query_understanding_service,
        )
