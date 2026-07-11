"""Default retrieval runtime provider implementations."""

from __future__ import annotations

from typing import cast

from ...configuration.models import GraphRAGConfig
from ...generation.ports import LLMClientPort
from ...graph.ports import Neo4jManagerPort as GraphNeo4jManagerPort
from ...graph.rag_retrieval import GraphRAGRetrieval
from ...infra.providers.dashscope import DashScopeRerankClient
from ...query_policy.models import QueryPolicyBundle
from ...query_understanding.ports import QueryUnderstandingPort
from ...query_understanding.service import QueryUnderstandingService
from ...retrieval.hybrid_service import HybridRetrievalService
from ...retrieval.ports import Neo4jManagerPort as RetrievalNeo4jManagerPort
from ...retrieval.ports import RerankClientPort
from ...retrieval.post_processor import RetrievalPostProcessor
from ...retrieval.runtime_profile import RetrievalRuntimeProfile, RetrievalRuntimeProfileFactory
from ...routing import RoutingWorkflowProtocol, RoutingWorkflowService
from ..ports import (
    GraphDataModulePort,
    Neo4jManagerPort,
    ServingGraphRAGRetrievalPort,
    ServingHybridRetrievalPort,
    VectorIndexModulePort,
)


class _DefaultRetrievalRuntimeProvider:
    """Default query-understanding, retrieval, and routing providers."""

    def __init__(
        self,
        *,
        profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.profile_factory = profile_factory or RetrievalRuntimeProfileFactory()

    def provide_retrieval_runtime_profile(
        self,
        config: GraphRAGConfig,
        *,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> RetrievalRuntimeProfile:
        del policy_bundle
        return self.profile_factory.build(config)

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> QueryUnderstandingPort:
        return QueryUnderstandingService(
            llm_client=llm_client,
            config=config,
            planner_settings=retrieval_profile.planner,
            semantic_settings=retrieval_profile.semantics,
            policy_bundle=policy_bundle,
        )

    def provide_traditional_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> ServingHybridRetrievalPort:
        del policy_bundle
        return HybridRetrievalService(
            config=config,
            milvus_module=milvus_module,
            data_module=data_module,
            llm_client=llm_client,
            neo4j_manager=cast(RetrievalNeo4jManagerPort, neo4j_manager),
            retrieval_profile=retrieval_profile,
        )

    def provide_graph_rag_retrieval(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort,
        retrieval_profile: RetrievalRuntimeProfile,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> ServingGraphRAGRetrievalPort:
        return GraphRAGRetrieval(
            config=config,
            llm_client=llm_client,
            neo4j_manager=cast(GraphNeo4jManagerPort, neo4j_manager),
            retrieval_profile=retrieval_profile,
            policy_bundle=policy_bundle,
        )

    def provide_routing_workflow(
        self,
        *,
        config: GraphRAGConfig,
        traditional_retrieval: ServingHybridRetrievalPort,
        graph_rag_retrieval: ServingGraphRAGRetrievalPort,
        llm_client: LLMClientPort,
        retrieval_profile: RetrievalRuntimeProfile,
        query_understanding_service: QueryUnderstandingPort,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> RoutingWorkflowProtocol:
        post_processor = RetrievalPostProcessor(
            config,
            settings=retrieval_profile.postprocess,
            rerank_client=self._provide_rerank_client(
                config,
                retrieval_profile=retrieval_profile,
            ),
        )
        return RoutingWorkflowService(
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
            llm_client=llm_client,
            config=config,
            retrieval_profile=retrieval_profile,
            query_understanding_service=query_understanding_service,
            post_processor=post_processor,
            policy_bundle=policy_bundle,
        )

    @staticmethod
    def _provide_rerank_client(
        config: GraphRAGConfig,
        *,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> RerankClientPort | None:
        settings = retrieval_profile.postprocess
        if not settings.enable_rerank:
            return None
        models = config.models
        return DashScopeRerankClient(
            api_key=str(models.api_key),
            model_name=settings.rerank_model,
            base_url=settings.rerank_base_url,
            timeout=settings.rerank_timeout_seconds,
            http_pool_connections=int(models.http_pool_connections),
            http_pool_maxsize=int(models.http_pool_maxsize),
            circuit_breaker_failure_threshold=int(models.circuit_breaker_failure_threshold),
            circuit_breaker_recovery_seconds=float(models.circuit_breaker_recovery_seconds),
        )


__all__ = ["_DefaultRetrievalRuntimeProvider"]
