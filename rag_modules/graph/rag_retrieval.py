"""GraphRAG retrieval service facade."""

from __future__ import annotations

from ..configuration.models import GraphRAGConfig
from ..contracts import EvidenceDocument, QueryPlan, QuerySemanticRuntimeSettings, RetrievalRequest
from ..contracts.graph import GraphQuery
from ..contracts.runtime import GraphRetrievalSnapshot
from ..query_policy.models import QueryPolicyBundle
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from .ports import LLMClientPort, Neo4jManagerPort
from .retrieval_components import (
    DefaultGraphRetrievalComponentFactory,
    GraphRetrievalComponentFactory,
)
from .retrieval_types import GraphPath, KnowledgeSubgraph, QueryType


class GraphRAGRetrieval:
    """Service facade over graph-native retrieval execution."""

    def __init__(
        self,
        config: GraphRAGConfig,
        llm_client: LLMClientPort,
        neo4j_manager: Neo4jManagerPort | None = None,
        retrieval_profile: RetrievalRuntimeProfile | None = None,
        component_factory: GraphRetrievalComponentFactory | None = None,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.neo4j_manager = neo4j_manager
        self.semantic_settings = (
            retrieval_profile.semantics
            if retrieval_profile is not None
            else QuerySemanticRuntimeSettings.from_config(config)
        )
        self.policy_bundle = policy_bundle
        self.component_factory = component_factory or DefaultGraphRetrievalComponentFactory()
        self._components = self.component_factory.build(
            config=config,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            semantic_settings=self.semantic_settings,
            database_name=config.storage.neo4j_database,
            policy_bundle=policy_bundle,
        )
        self._executor = self._components.executor

    def initialize(self) -> None:
        self._executor.initialize()

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        return self._components.query_factory.graph_query_from_plan(plan)

    def graph_rag_evidence_search_with_trace(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
        return self._executor.execute_with_trace(request)

    def close(self) -> None:
        self._executor.close()


__all__ = [
    "GraphRAGRetrieval",
    "GraphPath",
    "KnowledgeSubgraph",
    "QueryType",
]
