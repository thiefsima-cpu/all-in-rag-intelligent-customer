"""GraphRAG retrieval service facade."""

from __future__ import annotations

from typing import List, Optional, Union

from ..domain.shared.query_constraints import QueryConstraints
from ..query_understanding import QueryPlan
from ..retrieval.contracts import EvidenceDocument, RetrievalRequest
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..runtime import GraphRetrievalSnapshot
from ..runtime_contracts import Neo4jManagerPort
from .retrieval_components import (
    DefaultGraphRetrievalComponentFactory,
    GraphRetrievalComponentFactory,
)
from .retrieval_types import GraphPath, GraphQuery, KnowledgeSubgraph, QueryType


class GraphRAGRetrieval:
    """Service facade over graph-native retrieval execution."""

    def __init__(
        self,
        config,
        llm_client,
        neo4j_manager: Neo4jManagerPort | None = None,
        retrieval_profile: Optional[RetrievalRuntimeProfile] = None,
        component_factory: Optional[GraphRetrievalComponentFactory] = None,
    ):
        self.config = config
        self.llm_client = llm_client
        self.neo4j_manager = neo4j_manager
        self.retrieval_profile = retrieval_profile or RetrievalRuntimeProfile.from_config(config)
        self.component_factory = component_factory or DefaultGraphRetrievalComponentFactory()
        self._components = self.component_factory.build(
            config=config,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=self.retrieval_profile,
            database_name=config.storage.neo4j_database,
        )
        self._executor = self._components.executor

    def initialize(self):
        self._executor.initialize()

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        return self._components.query_factory.graph_query_from_plan(plan)

    def graph_rag_evidence_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[EvidenceDocument]:
        request = self._components.runtime.build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        return self._executor.execute(request)

    def graph_rag_evidence_search_with_trace(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> tuple[List[EvidenceDocument], GraphRetrievalSnapshot]:
        request = self._components.runtime.build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        return self._executor.execute_with_trace(request)

    def close(self):
        self._executor.close()


__all__ = [
    "GraphRAGRetrieval",
    "GraphPath",
    "GraphQuery",
    "KnowledgeSubgraph",
    "QueryType",
]
