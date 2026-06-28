"""Graph evidence execution and ranking orchestration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from ..retrieval.contracts import EvidenceDocument, RetrievalRequest
from ..safe_logging import log_failure
from .reasoning_strategy import GraphReasoningOutcome, GraphReasoningStrategy
from .retrieval_plan import GraphRetrievalPlan
from .retrieval_types import GraphPath, GraphQuery, KnowledgeSubgraph, QueryType

logger = logging.getLogger(__name__)


@dataclass
class GraphEvidenceExecutionResult:
    evidence_documents: List[EvidenceDocument] = field(default_factory=list)
    final_documents: List[EvidenceDocument] = field(default_factory=list)
    evidence_unit_count: int = 0


class GraphEvidenceOrchestrator:
    """Own graph plan execution, subgraph reasoning, and final ranking."""

    def __init__(
        self,
        *,
        graph_plan_builder,
        graph_executor,
        postprocessor,
        reasoning_strategy: GraphReasoningStrategy,
    ) -> None:
        self.graph_plan_builder = graph_plan_builder
        self.graph_executor = graph_executor
        self.postprocessor = postprocessor
        self.reasoning_strategy = reasoning_strategy

    def build_retrieval_plan(
        self,
        graph_query: GraphQuery,
        *,
        evidence_goals: List[str],
    ) -> GraphRetrievalPlan:
        return self.graph_plan_builder.build(graph_query, evidence_goals=evidence_goals)

    def execute_graph_plan(self, retrieval_plan: GraphRetrievalPlan) -> List[GraphPath]:
        query_type = retrieval_plan.query_type
        source_count = len(retrieval_plan.source_entities or [])
        target_count = len(retrieval_plan.target_entities or [])
        linked_count = len(retrieval_plan.linked_sources or [])
        logger.info(
            "Executing graph retrieval plan: type=%s source_count=%s target_count=%s linked_count=%s",
            query_type,
            source_count,
            target_count,
            linked_count,
        )
        if retrieval_plan.query_type == QueryType.PATH_FINDING.value:
            records = self.graph_executor.shortest_paths(retrieval_plan)
            path_type = "shortest_path"
        elif retrieval_plan.query_type == QueryType.ENTITY_RELATION.value:
            records = self.graph_executor.entity_relation_paths(retrieval_plan)
            path_type = "entity_relation"
        else:
            records = self.graph_executor.multi_hop_paths(retrieval_plan)
            path_type = "multi_hop"

        paths: List[GraphPath] = []
        for record in records:
            path_data = self.postprocessor.parse_neo4j_path(record, path_type=path_type)
            if path_data:
                paths.append(path_data)
        return paths

    def extract_knowledge_subgraph(self, graph_query: Any) -> KnowledgeSubgraph:
        retrieval_plan = (
            graph_query
            if isinstance(graph_query, GraphRetrievalPlan)
            else self.build_retrieval_plan(graph_query, evidence_goals=[])
        )
        source_count = len(retrieval_plan.source_entities)
        logger.info("Extracting knowledge subgraph: source_count=%s", source_count)

        if not self.graph_executor.driver:
            logger.error("Neo4j is not connected")
            return self.empty_subgraph()

        try:
            records = self.graph_executor.subgraphs(retrieval_plan)
            subgraphs = [
                self.postprocessor.build_knowledge_subgraph(record) for record in records if record
            ]
            if subgraphs:
                return self.postprocessor.merge_subgraphs(subgraphs)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )

        return self.empty_subgraph()

    def graph_structure_reasoning(self, subgraph: KnowledgeSubgraph, query: str) -> List[str]:
        return self.reason_over_subgraph(subgraph, query).validated_chains

    def reason_over_subgraph(
        self,
        subgraph: KnowledgeSubgraph,
        query: str,
    ) -> GraphReasoningOutcome:
        try:
            outcome = self.reasoning_strategy.reason(subgraph, query)
            logger.info(
                "Graph reasoning produced %s chains across %s patterns",
                len(outcome.validated_chains or []),
                len(outcome.patterns or []),
            )
            return outcome
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            return GraphReasoningOutcome()

    def retrieve(
        self,
        *,
        request: RetrievalRequest,
        graph_query: GraphQuery,
        retrieval_plan: GraphRetrievalPlan,
        trace,
        record_event: Callable[..., None],
    ) -> GraphEvidenceExecutionResult:
        evidence_documents = self._execute_graph_evidence(
            request=request,
            graph_query=graph_query,
            retrieval_plan=retrieval_plan,
            trace=trace,
            record_event=record_event,
        )
        postprocess_start = time.perf_counter()
        ranked_documents = self.postprocessor.to_ranked_evidence_documents(
            evidence_documents,
            request.query,
        )
        final_documents = ranked_documents[: request.top_k]
        evidence_unit_count = sum(len(doc.evidence_units or []) for doc in final_documents)
        record_event(
            trace,
            "rank_graph_evidence_documents",
            start_time=postprocess_start,
            details={
                "input_doc_count": len(evidence_documents or []),
                "ranked_doc_count": len(ranked_documents or []),
                "returned_doc_count": len(final_documents or []),
                "returned_evidence_unit_count": evidence_unit_count,
            },
        )
        return GraphEvidenceExecutionResult(
            evidence_documents=evidence_documents,
            final_documents=final_documents,
            evidence_unit_count=evidence_unit_count,
        )

    def paths_to_evidence_documents(
        self,
        paths: List[GraphPath],
        query: str,
    ) -> List[EvidenceDocument]:
        return self.postprocessor.paths_to_evidence_documents(paths, query)

    def subgraph_to_evidence_documents(
        self,
        subgraph: KnowledgeSubgraph,
        reasoning_chains: List[str],
        query: str,
    ) -> List[EvidenceDocument]:
        return self.postprocessor.subgraph_to_evidence_documents(subgraph, reasoning_chains, query)

    def build_path_description(self, path: GraphPath) -> str:
        return self.postprocessor.build_path_description(path)

    def build_subgraph_description(self, subgraph: KnowledgeSubgraph) -> str:
        return self.postprocessor.build_subgraph_description(subgraph)

    def summarize_subgraph_evidence(self, subgraph: KnowledgeSubgraph):
        return self.postprocessor.summarize_subgraph_evidence(subgraph)

    def relationship_lines(self, subgraph: KnowledgeSubgraph, limit: int = 30):
        return self.postprocessor.relationship_lines(subgraph, limit=limit)

    def identify_reasoning_patterns(self, subgraph: KnowledgeSubgraph) -> List[str]:
        return self.reasoning_strategy.identify_reasoning_patterns(subgraph, "")

    def build_reasoning_chain(
        self,
        pattern: str,
        subgraph: KnowledgeSubgraph,
    ) -> Optional[str]:
        chains = self.reasoning_strategy.build_reasoning_chains(pattern, subgraph, "")
        return chains[0] if chains else None

    @staticmethod
    def validate_reasoning_chains(chains: List[str], query: str) -> List[str]:
        del query
        return list(dict.fromkeys(str(chain).strip() for chain in chains if str(chain).strip()))[:3]

    def empty_subgraph(self) -> KnowledgeSubgraph:
        return self.postprocessor.empty_subgraph()

    def _execute_graph_evidence(
        self,
        *,
        request: RetrievalRequest,
        graph_query: GraphQuery,
        retrieval_plan: GraphRetrievalPlan,
        trace,
        record_event: Callable[..., None],
    ) -> List[EvidenceDocument]:
        if graph_query.query_type in {
            QueryType.MULTI_HOP,
            QueryType.PATH_FINDING,
            QueryType.ENTITY_RELATION,
        }:
            path_start = time.perf_counter()
            paths = self.execute_graph_plan(retrieval_plan)
            trace.path_count = len(paths)
            record_event(
                trace,
                "execute_graph_paths",
                start_time=path_start,
                details={
                    "path_type": graph_query.query_type.value,
                    "path_count": len(paths or []),
                },
            )
            return self.paths_to_evidence_documents(paths, request.query)
        if graph_query.query_type in {QueryType.SUBGRAPH, QueryType.CLUSTERING}:
            subgraph_start = time.perf_counter()
            subgraph = self.extract_knowledge_subgraph(retrieval_plan)
            trace.subgraph_count = len(subgraph.central_nodes)
            record_event(
                trace,
                "extract_knowledge_subgraph",
                start_time=subgraph_start,
                details={
                    "central_node_count": len(subgraph.central_nodes or []),
                    "connected_node_count": len(subgraph.connected_nodes or []),
                    "relationship_count": len(subgraph.relationships or []),
                },
            )
            reasoning_start = time.perf_counter()
            reasoning_outcome = self.reason_over_subgraph(subgraph, request.query)
            trace.reasoning_patterns = list(reasoning_outcome.patterns or [])
            trace.reasoning_chain_count = len(reasoning_outcome.validated_chains or [])
            record_event(
                trace,
                "graph_structure_reasoning",
                start_time=reasoning_start,
                details=reasoning_outcome.to_trace_details(),
            )
            return self.subgraph_to_evidence_documents(
                subgraph,
                reasoning_outcome.validated_chains,
                request.query,
            )
        return []
