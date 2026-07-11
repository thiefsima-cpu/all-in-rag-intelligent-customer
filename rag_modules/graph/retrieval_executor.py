"""Execution and lifecycle layer for graph-native retrieval."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from ..configuration.models import GraphRAGConfig
from ..contracts import (
    EvidenceDocument,
    QuerySemanticRuntimeSettings,
    RequestBudgetExceeded,
    RequestCancelled,
    RequestControl,
    RetrievalRequest,
)
from ..contracts.graph import GraphQuery
from ..contracts.runtime import GraphRetrievalSnapshot
from ..contracts.runtime.errors import graph_error_detail
from ..entity_linker import EntityLinker
from ..kernel.json_types import JsonObject, coerce_json_object
from ..safe_logging import log_failure
from .cache_stats import GraphCacheStatsStore
from .cache_warmup import GraphCacheWarmupService
from .evidence_orchestrator import GraphEvidenceOrchestrator
from .ports import Neo4jDriverPort, Neo4jManagerPort
from .query_executor import GraphQueryExecutor
from .retrieval_plan import GraphRetrievalPlan
from .retrieval_runtime import GraphRetrievalRuntime

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GraphRetrievalExecutorServices:
    """Collaborators required by the graph retrieval executor."""

    config: GraphRAGConfig
    runtime: GraphRetrievalRuntime
    orchestrator: GraphEvidenceOrchestrator
    cache_warmup: GraphCacheWarmupService
    graph_cache_stats_store: GraphCacheStatsStore
    entity_linker: EntityLinker
    graph_executor: GraphQueryExecutor
    neo4j_manager: Neo4jManagerPort | None = None
    database_name: str = "neo4j"


class GraphRetrievalExecutor:
    """Own graph retrieval initialization, cache warmup, tracing, and execution."""

    def __init__(
        self,
        *,
        services: GraphRetrievalExecutorServices,
    ) -> None:
        config = services.config
        self.config = config
        self.storage = config.storage
        self.semantic_settings = QuerySemanticRuntimeSettings.from_config(config)
        self.runtime = services.runtime
        self.orchestrator = services.orchestrator
        self.cache_warmup = services.cache_warmup
        self.graph_cache_stats_store = services.graph_cache_stats_store
        self.entity_linker = services.entity_linker
        self.graph_executor = services.graph_executor
        self.neo4j_manager = services.neo4j_manager
        self.database_name = services.database_name

        self.driver: Neo4jDriverPort | None = None
        self._owns_driver = False
        self.entity_cache: dict[str, JsonObject] = {}
        self.relation_cache: dict[str, int] = {}
        self.subgraph_cache: dict[str, JsonObject] = {}

    def initialize(self) -> None:
        """Initialize graph retrieval dependencies and warm lightweight indexes."""
        logger.info("Initializing GraphRAG retrieval...")
        try:
            if self.neo4j_manager is not None:
                self.driver = self.neo4j_manager.driver
            else:
                raise RuntimeError("Graph retrieval requires an injected Neo4j manager.")

            driver = self.driver
            if driver is None:
                raise RuntimeError("Neo4j driver was not initialized.")

            with driver.session(database=self.database_name) as session:
                session.run("RETURN 1")

            self.entity_linker.driver = self.driver
            self.graph_executor.driver = self.driver
            self.build_graph_index()
            logger.info("GraphRAG retrieval initialized")
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )
            if self._owns_driver and self.driver:
                self.driver.close()
            self.driver = None
            self._owns_driver = False
            raise RuntimeError(f"Graph retrieval initialization failed: {exc}") from exc

    def build_graph_index(self) -> None:
        """Warm graph stats from persistent cache or paged scan."""
        logger.info("Building graph retrieval caches...")
        try:
            driver = self.driver
            if driver is None:
                raise RuntimeError("Neo4j driver was not initialized.")
            warmup = self.cache_warmup.warm(
                driver,
                database_name=self.database_name,
            )
            self.entity_cache = {
                str(key): coerce_json_object(value)
                for key, value in dict(warmup.entity_cache or {}).items()
            }
            self.relation_cache = dict(warmup.relation_cache or {})
            logger.info(
                "Graph caches ready: %s entities, %s relation types",
                len(self.entity_cache),
                len(self.relation_cache),
            )
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "graph_operation_failed",
                code="GRAPH_OPERATION_FAILED",
                error=exc,
            )

    def execute_with_trace(
        self, request: RetrievalRequest
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
        logger.info("Starting GraphRAG retrieval: top_k=%s", request.top_k)
        start_time = time.perf_counter()
        trace = self.runtime.start_trace(
            request.query,
            requested_top_k=request.top_k,
            retrieval_request=request,
        )

        try:
            final_results, final_trace = _execute_retrieval(self, request, trace, start_time)
            return final_results, _snapshot_from_trace(self, final_trace)
        except (RequestCancelled, RequestBudgetExceeded) as exc:
            return [], _handle_control_error(self, trace, start_time, exc)
        except Exception as exc:
            return [], _handle_retrieval_error(self, trace, start_time, exc)

    def close(self) -> None:
        if self._owns_driver and self.driver:
            self.driver.close()
            logger.info("GraphRAG retrieval closed")


def _execute_retrieval(
    executor: GraphRetrievalExecutor,
    request: RetrievalRequest,
    trace: GraphRetrievalSnapshot,
    start_time: float,
) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
    control = request.control
    _raise_if_cancelled(control)
    graph_query, evidence_goals = _resolve_request_context(executor, request, trace, control)

    if not executor.driver:
        return [], _finalize_missing_driver(executor, trace, start_time)

    _raise_if_cancelled(control)
    retrieval_plan = _build_retrieval_plan(executor, graph_query, evidence_goals, trace, control)
    execution = executor.orchestrator.retrieve(
        request=request,
        graph_query=graph_query,
        retrieval_plan=retrieval_plan,
        trace=trace,
        record_event=executor.runtime.record_event,
    )
    _raise_if_cancelled(control)
    final_results = execution.final_documents
    final_trace = executor.runtime.finalize_trace(
        trace,
        start_time=start_time,
        doc_count=len(final_results),
        evidence_unit_count=execution.evidence_unit_count,
    )
    return final_results, final_trace


def _resolve_request_context(
    executor: GraphRetrievalExecutor,
    request: RetrievalRequest,
    trace: GraphRetrievalSnapshot,
    control: RequestControl | None,
) -> tuple[GraphQuery, list[str]]:
    context_start = time.perf_counter()
    graph_query, evidence_goals = executor.runtime.resolve_request_context(request)
    _raise_if_cancelled(control)
    executor.runtime.record_event(
        trace,
        "resolve_request_context",
        start_time=context_start,
        details={
            "query_type": graph_query.query_type.value,
            "source_entity_count": len(graph_query.source_entities or []),
            "target_entity_count": len(graph_query.target_entities or []),
            "relation_type_count": len(graph_query.relation_types or []),
            "evidence_goal_count": len(evidence_goals or []),
        },
    )
    executor.runtime.populate_trace_context(
        trace,
        graph_query=graph_query,
        evidence_goals=evidence_goals,
    )
    return graph_query, evidence_goals


def _build_retrieval_plan(
    executor: GraphRetrievalExecutor,
    graph_query: GraphQuery,
    evidence_goals: list[str],
    trace: GraphRetrievalSnapshot,
    control: RequestControl | None,
) -> GraphRetrievalPlan:
    plan_start = time.perf_counter()
    retrieval_plan = executor.orchestrator.build_retrieval_plan(
        graph_query,
        evidence_goals=evidence_goals,
    )
    _raise_if_cancelled(control)
    trace.retrieval_plan = coerce_json_object(retrieval_plan.to_trace())
    executor.runtime.record_event(
        trace,
        "build_retrieval_plan",
        start_time=plan_start,
        details={
            "linked_source_count": len(retrieval_plan.linked_sources or []),
            "linked_target_count": len(retrieval_plan.linked_targets or []),
            "max_depth": retrieval_plan.max_depth,
            "max_nodes": retrieval_plan.max_nodes,
        },
    )
    return retrieval_plan


def _finalize_missing_driver(
    executor: GraphRetrievalExecutor,
    trace: GraphRetrievalSnapshot,
    start_time: float,
) -> GraphRetrievalSnapshot:
    error = graph_error_detail(detail="neo4j_not_connected")
    executor.runtime.record_event(
        trace,
        "validate_driver",
        status="error",
        details={"error": error.to_dict()},
    )
    return executor.runtime.finalize_trace(trace, start_time=start_time, error=error)


def _handle_control_error(
    executor: GraphRetrievalExecutor,
    trace: GraphRetrievalSnapshot,
    start_time: float,
    exc: RequestCancelled | RequestBudgetExceeded,
) -> GraphRetrievalSnapshot:
    reason = str(exc)
    executor.runtime.record_event(
        trace,
        "request_control_cancelled",
        status="error",
        details={"reason": reason},
    )
    final_trace = executor.runtime.finalize_trace(
        trace,
        start_time=start_time,
        error=graph_error_detail(detail=reason),
    )
    return _snapshot_from_trace(executor, final_trace)


def _handle_retrieval_error(
    executor: GraphRetrievalExecutor,
    trace: GraphRetrievalSnapshot,
    start_time: float,
    exc: Exception,
) -> GraphRetrievalSnapshot:
    log_failure(
        logger,
        logging.ERROR,
        "graph_operation_failed",
        code="GRAPH_OPERATION_FAILED",
        error=exc,
    )
    error = graph_error_detail(exc)
    executor.runtime.record_event(
        trace,
        "graph_retrieval_failed",
        status="error",
        details={"error": error.to_dict()},
    )
    final_trace = executor.runtime.finalize_trace(trace, start_time=start_time, error=error)
    return _snapshot_from_trace(executor, final_trace)


def _snapshot_from_trace(
    executor: GraphRetrievalExecutor, trace: GraphRetrievalSnapshot
) -> GraphRetrievalSnapshot:
    return GraphRetrievalSnapshot.from_dict(
        trace.to_dict(),
        semantic_settings=executor.semantic_settings,
    )


def _raise_if_cancelled(control: RequestControl | None) -> None:
    if control is not None:
        control.raise_if_cancelled()
