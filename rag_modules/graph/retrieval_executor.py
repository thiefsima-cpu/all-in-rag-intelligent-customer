"""Execution and lifecycle layer for graph-native retrieval."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

from ..infra.neo4j import create_neo4j_driver
from ..runtime import GraphRetrievalSnapshot

logger = logging.getLogger(__name__)


class GraphRetrievalExecutor:
    """Own graph retrieval initialization, cache warmup, tracing, and execution."""

    def __init__(
        self,
        *,
        config,
        runtime,
        orchestrator,
        cache_warmup,
        graph_cache_stats_store,
        entity_linker,
        graph_executor,
        neo4j_manager=None,
        database_name: str = "neo4j",
    ) -> None:
        self.config = config
        self.storage = config.storage
        self.runtime = runtime
        self.orchestrator = orchestrator
        self.cache_warmup = cache_warmup
        self.graph_cache_stats_store = graph_cache_stats_store
        self.entity_linker = entity_linker
        self.graph_executor = graph_executor
        self.neo4j_manager = neo4j_manager
        self.database_name = database_name

        self.driver: Any | None = None
        self._owns_driver = False
        self.entity_cache: Dict[str, dict] = {}
        self.relation_cache: Dict[str, int] = {}
        self.subgraph_cache: Dict[str, dict] = {}

    def initialize(self) -> None:
        """Initialize graph retrieval dependencies and warm lightweight indexes."""
        logger.info("Initializing GraphRAG retrieval...")
        try:
            if self.neo4j_manager is not None:
                self.driver = self.neo4j_manager.driver
            else:
                self.driver = create_neo4j_driver(
                    self.storage.neo4j_uri,
                    self.storage.neo4j_user,
                    self.storage.neo4j_password,
                )
                self._owns_driver = True

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
            logger.error("Neo4j connection failed: %s", exc)
            if self._owns_driver and self.driver:
                self.driver.close()
            self.driver = None
            self._owns_driver = False
            raise RuntimeError(f"Graph retrieval initialization failed: {exc}") from exc

    def build_graph_index(self) -> None:
        """Warm graph stats from persistent cache or paged scan."""
        logger.info("Building graph retrieval caches...")
        try:
            warmup = self.cache_warmup.warm(
                self.driver,
                database_name=self.database_name,
            )
            self.entity_cache = dict(warmup.entity_cache or {})
            self.relation_cache = dict(warmup.relation_cache or {})
            logger.info(
                "Graph caches ready: %s entities, %s relation types, stats=%s",
                len(self.entity_cache),
                len(self.relation_cache),
                os.path.abspath(self.graph_cache_stats_store.path),
            )
        except Exception as exc:
            logger.error("Graph cache build failed: %s", exc)

    def execute(self, request) -> List:
        results, _trace = self.execute_with_trace(request)
        return results

    def execute_with_trace(self, request) -> tuple[List, GraphRetrievalSnapshot]:
        logger.info("Starting GraphRAG retrieval: %s", request.query)
        start_time = time.perf_counter()
        trace = self.runtime.start_trace(
            request.query,
            requested_top_k=request.top_k,
            retrieval_request=request,
        )

        context_start = time.perf_counter()
        graph_query, evidence_goals = self.runtime.resolve_request_context(request)
        self.runtime.record_event(
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
        self.runtime.populate_trace_context(
            trace,
            graph_query=graph_query,
            evidence_goals=evidence_goals,
        )

        if not self.driver:
            self.runtime.record_event(
                trace,
                "validate_driver",
                status="error",
                details={"error": "neo4j_not_connected"},
            )
            final_trace = self.runtime.finalize_trace(
                trace,
                start_time=start_time,
                error="neo4j_not_connected",
            )
            return [], GraphRetrievalSnapshot.from_dict(final_trace.to_dict())

        plan_start = time.perf_counter()
        retrieval_plan = self.orchestrator.build_retrieval_plan(
            graph_query,
            evidence_goals=evidence_goals,
        )
        trace.retrieval_plan = retrieval_plan.to_trace()
        self.runtime.record_event(
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

        try:
            execution = self.orchestrator.retrieve(
                request=request,
                graph_query=graph_query,
                retrieval_plan=retrieval_plan,
                trace=trace,
                record_event=self.runtime.record_event,
            )
            final_results = execution.final_documents
            final_trace = self.runtime.finalize_trace(
                trace,
                start_time=start_time,
                doc_count=len(final_results),
                evidence_unit_count=execution.evidence_unit_count,
            )
            return final_results, GraphRetrievalSnapshot.from_dict(final_trace.to_dict())
        except Exception as exc:
            logger.error("GraphRAG evidence retrieval failed: %s", exc)
            self.runtime.record_event(
                trace,
                "graph_retrieval_failed",
                status="error",
                details={"error": str(exc)},
            )
            final_trace = self.runtime.finalize_trace(
                trace,
                start_time=start_time,
                error=str(exc),
            )
            return [], GraphRetrievalSnapshot.from_dict(final_trace.to_dict())

    def close(self) -> None:
        if self._owns_driver and self.driver:
            self.driver.close()
            logger.info("GraphRAG retrieval closed")
