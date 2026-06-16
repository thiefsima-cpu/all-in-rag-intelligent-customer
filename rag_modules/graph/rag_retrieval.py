"""GraphRAG retrieval facade."""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Union

from langchain_core.documents import Document

from .query_intent import GraphQueryIntent
from .retrieval_components import (
    DefaultGraphRetrievalComponentFactory,
    GraphRetrievalComponentFactory,
    GraphRetrievalComponents,
)
from .retrieval_plan import GraphRetrievalPlan
from .retrieval_types import GraphPath, GraphQuery, KnowledgeSubgraph, QueryType
from ..neo4j_pool import Neo4jConnectionManager
from ..query_constraints import QueryConstraints
from ..query_understanding import QueryPlan
from ..retrieval.contracts import EvidenceDocument, RetrievalRequest, to_langchain_documents
from ..retrieval.runtime_profile import RetrievalRuntimeProfile
from ..runtime import GraphRetrievalSnapshot

logger = logging.getLogger(__name__)
_COMPONENT_FIELDS = frozenset(GraphRetrievalComponents.__annotations__)


class GraphRAGRetrieval:
    """Thin facade over graph retrieval planning and executor/service layers."""

    def __init__(
        self,
        config,
        llm_client,
        neo4j_manager: Optional[Neo4jConnectionManager] = None,
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
            database_name=self._database_name,
        )
        self._executor = self._components.executor

    @property
    def components(self) -> GraphRetrievalComponents:
        return self._components

    @property
    def executor(self):
        return self._executor

    @property
    def _database_name(self) -> str:
        return self.config.storage.neo4j_database

    @property
    def driver(self):
        return self._executor.driver

    @property
    def entity_cache(self):
        return self._executor.entity_cache

    @entity_cache.setter
    def entity_cache(self, value):
        self._executor.entity_cache = dict(value or {})

    @property
    def relation_cache(self):
        return self._executor.relation_cache

    @relation_cache.setter
    def relation_cache(self, value):
        self._executor.relation_cache = dict(value or {})

    @property
    def subgraph_cache(self):
        return self._executor.subgraph_cache

    @subgraph_cache.setter
    def subgraph_cache(self, value):
        self._executor.subgraph_cache = dict(value or {})

    def initialize(self):
        self._executor.initialize()

    def _build_graph_index(self):
        self._executor.build_graph_index()

    def understand_graph_query(self, query: str) -> GraphQuery:
        return self._components.query_factory.understand_graph_query(query)

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        return self._components.query_factory.graph_query_from_plan(plan)

    def _graph_query_from_intent(self, intent: GraphQueryIntent, query: str) -> GraphQuery:
        return self._components.query_factory.graph_query_from_intent(intent, query)

    def adaptive_query_planning(self, query: str) -> List[GraphQuery]:
        return self._components.query_factory.adaptive_query_planning(query)

    def graph_retrieval_plan(self, graph_query: GraphQuery, evidence_goals: List[str]) -> GraphRetrievalPlan:
        return self._components.orchestrator.build_retrieval_plan(
            graph_query,
            evidence_goals=evidence_goals,
        )

    def execute_graph_plan(self, retrieval_plan: GraphRetrievalPlan) -> List[GraphPath]:
        return self._components.orchestrator.execute_graph_plan(retrieval_plan)

    def multi_hop_traversal(self, graph_query: GraphQuery) -> List[GraphPath]:
        retrieval_plan = self.graph_retrieval_plan(graph_query, evidence_goals=[])
        paths = self.execute_graph_plan(retrieval_plan)
        logger.info("Graph traversal returned %s paths", len(paths))
        return paths

    def extract_knowledge_subgraph(self, graph_query: Any) -> KnowledgeSubgraph:
        return self._components.orchestrator.extract_knowledge_subgraph(graph_query)

    def graph_structure_reasoning(self, subgraph: KnowledgeSubgraph, query: str) -> List[str]:
        return self._components.orchestrator.graph_structure_reasoning(subgraph, query)

    def graph_rag_evidence_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[EvidenceDocument]:
        request = self._build_request(
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
        request = self._build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        return self._executor.execute_with_trace(request)

    def _legacy_graph_rag_search(
        self,
        query: str,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[Document]:
        return self.graph_rag_search(
            query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )

    def graph_rag_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[Document]:
        return to_langchain_documents(
            self.graph_rag_evidence_search(
                request_or_query,
                top_k=top_k,
                constraints=constraints,
                query_plan=query_plan,
            )
        )

    def _build_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> RetrievalRequest:
        return self._components.runtime.build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )

    def _paths_to_evidence_documents(self, paths: List[GraphPath], query: str) -> List[EvidenceDocument]:
        return self._components.orchestrator.paths_to_evidence_documents(paths, query)

    def _subgraph_to_evidence_documents(
        self,
        subgraph: KnowledgeSubgraph,
        reasoning_chains: List[str],
        query: str,
    ) -> List[EvidenceDocument]:
        return self._components.orchestrator.subgraph_to_evidence_documents(
            subgraph,
            reasoning_chains,
            query,
        )

    def _analyze_query_complexity(self, query: str) -> float:
        return self._components.query_factory.analyze_query_complexity(query)

    def _build_path_description(self, path: GraphPath) -> str:
        return self._components.orchestrator.build_path_description(path)

    def _build_subgraph_description(self, subgraph: KnowledgeSubgraph) -> str:
        return self._components.orchestrator.build_subgraph_description(subgraph)

    def _summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraph):
        return self._components.orchestrator.summarize_subgraph_evidence(subgraph)

    def _relationship_lines(self, subgraph: KnowledgeSubgraph, limit: int = 30):
        return self._components.orchestrator.relationship_lines(subgraph, limit=limit)

    def _identify_reasoning_patterns(self, subgraph: KnowledgeSubgraph) -> List[str]:
        return self._components.orchestrator.identify_reasoning_patterns(subgraph)

    def _build_reasoning_chain(self, pattern: str, subgraph: KnowledgeSubgraph) -> Optional[str]:
        return self._components.orchestrator.build_reasoning_chain(pattern, subgraph)

    def _validate_reasoning_chains(self, chains: List[str], query: str) -> List[str]:
        return self._components.orchestrator.validate_reasoning_chains(chains, query)

    def _reason_over_subgraph(self, subgraph: KnowledgeSubgraph, query: str):
        return self._components.orchestrator.reason_over_subgraph(subgraph, query)

    def _fallback_subgraph_extraction(self) -> KnowledgeSubgraph:
        return self._components.orchestrator.empty_subgraph()

    def close(self):
        self._executor.close()

    def __getattr__(self, name: str):
        if name in _COMPONENT_FIELDS:
            return getattr(self._components, name)
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")


__all__ = [
    "GraphRAGRetrieval",
    "GraphPath",
    "GraphQuery",
    "KnowledgeSubgraph",
    "QueryType",
]
