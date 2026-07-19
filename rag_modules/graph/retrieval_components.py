"""Component assembly for the graph retrieval facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..configuration.models import GraphRAGConfig
from ..contracts import QuerySemanticRuntimeSettings
from ..domains import DomainPack, get_domain_pack
from ..query_policy.models import QueryPolicyBundle
from .cache_stats import GraphCacheStatsStore
from .cache_warmup import GraphCacheWarmupService
from .entity_linker import EntityLinker
from .evidence_builder import GraphEvidenceBuilder
from .evidence_orchestrator import GraphEvidenceOrchestrator
from .path_ranker import GraphDocumentRanker
from .ports import LLMClientPort, Neo4jManagerPort
from .query_executor import GraphQueryExecutor
from .query_resolution import GraphQueryFactory
from .reasoning_strategy import GraphReasoningStrategy
from .retrieval_executor import GraphRetrievalExecutor, GraphRetrievalExecutorServices
from .retrieval_plan import GraphPlanBuilder
from .retrieval_postprocess import GraphRetrievalPostProcessor
from .retrieval_runtime import GraphRetrievalRuntime


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
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort | None,
        semantic_settings: QuerySemanticRuntimeSettings,
        database_name: str,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> GraphRetrievalComponents: ...


class DefaultGraphRetrievalComponentFactory:
    """Default wiring for the graph retrieval runtime stack."""

    def build(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort | None,
        semantic_settings: QuerySemanticRuntimeSettings,
        database_name: str,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> GraphRetrievalComponents:
        del llm_client
        domain_pack = get_domain_pack(config.domain.name)
        query_factory = GraphQueryFactory(
            semantic_settings=semantic_settings,
            policy_bundle=policy_bundle,
        )
        runtime = GraphRetrievalRuntime(query_factory, policy_bundle=policy_bundle)
        entity_linker = EntityLinker(
            None,
            database=database_name,
            graph_settings=config.graph,
            preferred_labels=domain_pack.ontology.primary_labels,
            lookup_fields=domain_pack.ontology.entity_lookup_fields,
            allowed_labels=domain_pack.ontology.primary_labels,
            domain_name=domain_pack.name,
        )
        graph_plan_builder = GraphPlanBuilder(entity_linker)
        graph_executor = GraphQueryExecutor(
            None,
            database=database_name,
            domain_name=domain_pack.name,
            primary_node_labels=domain_pack.ontology.primary_labels,
            semantic_relation_types=tuple(
                relation.name for relation in domain_pack.ontology.relation_types
            ),
            semantic_node_labels=(),
            allowed_node_labels=domain_pack.ontology.node_labels,
        )
        postprocessor = GraphRetrievalPostProcessor(
            evidence_builder=GraphEvidenceBuilder(
                domain_name=domain_pack.name,
                primary_labels=domain_pack.ontology.primary_labels,
            ),
            ranker=GraphDocumentRanker(config.graph),
        )
        reasoning_strategy = GraphReasoningStrategy(policy_bundle=policy_bundle)
        orchestrator = GraphEvidenceOrchestrator(
            graph_plan_builder=graph_plan_builder,
            graph_executor=graph_executor,
            postprocessor=postprocessor,
            reasoning_strategy=reasoning_strategy,
        )
        graph_cache_stats_store, cache_warmup = _cache_warmup_services(config, domain_pack)
        services = GraphRetrievalExecutorServices(
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
        executor = GraphRetrievalExecutor(services=services)
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


def _cache_warmup_services(
    config: GraphRAGConfig,
    domain_pack: DomainPack,
) -> tuple[GraphCacheStatsStore, GraphCacheWarmupService]:
    store = GraphCacheStatsStore(config)
    return store, GraphCacheWarmupService(
        store,
        domain_name=domain_pack.name,
        allowed_node_labels=domain_pack.ontology.node_labels,
    )
