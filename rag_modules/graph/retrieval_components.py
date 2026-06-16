"""Component assembly for the graph retrieval facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol

from ..entity_linker import EntityLinker
from .cache_stats import GraphCacheStatsStore
from .cache_warmup import GraphCacheWarmupService
from .evidence_builder import GraphEvidenceBuilder
from .evidence_orchestrator import GraphEvidenceOrchestrator
from .path_ranker import GraphDocumentRanker
from .query_executor import GraphQueryExecutor
from .query_resolution import GraphQueryFactory
from .reasoning_strategy import GraphReasoningStrategy
from .retrieval_executor import GraphRetrievalExecutor
from .retrieval_plan import GraphPlanBuilder
from .retrieval_postprocess import GraphRetrievalPostProcessor
from .retrieval_runtime import GraphRetrievalRuntime
from ..retrieval.runtime_profile import RetrievalRuntimeProfile


@dataclass
class GraphRetrievalComponents:
    """Concrete collaborators used by the graph retrieval facade."""

    query_factory: GraphQueryFactory
    runtime: GraphRetrievalRuntime
    entity_linker: EntityLinker
    graph_plan_builder: GraphPlanBuilder
    graph_executor: GraphQueryExecutor
    postprocessor: GraphRetrievalPostProcessor
    reasoning_strategy: GraphReasoningStrategy
    orchestrator: GraphEvidenceOrchestrator
    graph_cache_stats_store: GraphCacheStatsStore
    cache_warmup: GraphCacheWarmupService
    executor: GraphRetrievalExecutor


class GraphRetrievalComponentFactory(Protocol):
    """Assembly boundary for graph retrieval collaborators."""

    def build(
        self,
        *,
        config: Any,
        llm_client: Any,
        neo4j_manager: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        database_name: str,
    ) -> GraphRetrievalComponents: ...


class DefaultGraphRetrievalComponentFactory:
    """Default wiring for the graph retrieval runtime stack."""

    def build(
        self,
        *,
        config: Any,
        llm_client: Any,
        neo4j_manager: Any,
        retrieval_profile: RetrievalRuntimeProfile,
        database_name: str,
    ) -> GraphRetrievalComponents:
        del llm_client
        query_factory = GraphQueryFactory(
            semantic_settings=retrieval_profile.semantics,
        )
        runtime = GraphRetrievalRuntime(query_factory)
        entity_linker = EntityLinker(
            None,
            database=database_name,
            graph_settings=config.graph,
        )
        graph_plan_builder = GraphPlanBuilder(entity_linker)
        graph_executor = GraphQueryExecutor(None, database=database_name)
        postprocessor = GraphRetrievalPostProcessor(
            evidence_builder=GraphEvidenceBuilder(),
            ranker=GraphDocumentRanker(config.graph),
        )
        reasoning_strategy = GraphReasoningStrategy()
        orchestrator = GraphEvidenceOrchestrator(
            graph_plan_builder=graph_plan_builder,
            graph_executor=graph_executor,
            postprocessor=postprocessor,
            reasoning_strategy=reasoning_strategy,
        )
        graph_cache_stats_store = GraphCacheStatsStore(config)
        cache_warmup = GraphCacheWarmupService(graph_cache_stats_store)
        executor = GraphRetrievalExecutor(
            config=config,
            runtime=runtime,
            orchestrator=orchestrator,
            cache_warmup=cache_warmup,
            graph_cache_stats_store=graph_cache_stats_store,
            entity_linker=entity_linker,
            graph_executor=graph_executor,
            neo4j_manager=neo4j_manager,
            database_name=database_name,
        )
        return GraphRetrievalComponents(
            query_factory=query_factory,
            runtime=runtime,
            entity_linker=entity_linker,
            graph_plan_builder=graph_plan_builder,
            graph_executor=graph_executor,
            postprocessor=postprocessor,
            reasoning_strategy=reasoning_strategy,
            orchestrator=orchestrator,
            graph_cache_stats_store=graph_cache_stats_store,
            cache_warmup=cache_warmup,
            executor=executor,
        )



