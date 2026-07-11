"""Canonical question-answer workflow."""

from __future__ import annotations

import logging
import time
from typing import cast

from ...configuration.models import GraphRAGConfig
from ...contracts import RequestControl
from ...contracts.runtime.errors import answer_error_detail
from ...query_policy import get_query_policy
from ...retrieval.runtime_profile import RetrievalRuntimeProfileFactory
from ...safe_logging import log_failure
from ...telemetry import RuntimeTelemetry, get_runtime_telemetry
from ..ports import QueryTracerPort
from .answer_copy import AnswerWorkflowCopy
from .answer_models import (
    AnswerPipelineState,
    ChunkCallback,
    MessageCallback,
    QuestionAnswerResponse,
    QuestionAnswerResult,
)
from .answer_pipeline import AnswerPipelineService
from .answer_result_factory import QuestionAnswerResultFactory
from .answer_trace_assembler import AnswerTraceAssembler
from .trace_adapters import GenerationServiceSource, QueryRouterSource

logger = logging.getLogger(__name__)


class AnswerWorkflow:
    """Execute the full question-answer lifecycle over stable runtime contracts."""

    def __init__(
        self,
        config: GraphRAGConfig,
        query_router: QueryRouterSource,
        generation_module: GenerationServiceSource,
        query_tracer: QueryTracerPort | None,
        *,
        pipeline: AnswerPipelineService | None = None,
        trace_assembler: AnswerTraceAssembler | None = None,
        result_factory: QuestionAnswerResultFactory | None = None,
        answer_workflow_copy: AnswerWorkflowCopy | None = None,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        self.config = config
        self.retrieval_settings = config.retrieval
        self.query_router = query_router
        self.generation_service = generation_module
        self.generation_module = generation_module
        self.query_tracer = query_tracer
        self.telemetry = telemetry or get_runtime_telemetry(config)
        retrieval_profile = RetrievalRuntimeProfileFactory().build(config)
        if answer_workflow_copy is None:
            answer_workflow_copy = cast(
                AnswerWorkflowCopy,
                get_query_policy().generation.answer_workflow_copy,
            )
        self.answer_workflow_copy = answer_workflow_copy
        self.pipeline = pipeline or AnswerPipelineService(
            query_router=query_router,
            generation_service=generation_module,
            semantic_settings=retrieval_profile.semantics,
            top_k=self.retrieval_settings.top_k,
            answer_workflow_copy=self.answer_workflow_copy,
            telemetry=self.telemetry,
        )
        self.trace_assembler = trace_assembler or AnswerTraceAssembler(
            query_tracer=query_tracer,
            semantic_settings=retrieval_profile.semantics,
        )
        self.result_factory = result_factory or QuestionAnswerResultFactory(
            answer_workflow_copy=self.answer_workflow_copy,
        )

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResult:
        start_time = time.perf_counter()
        request_control = control or self._new_request_control()
        state = AnswerPipelineState(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
            request_control=request_control,
        )

        with self.telemetry.span(
            "rag.answer",
            attributes={
                "rag.question.length": len(question or ""),
                "rag.stream": bool(stream),
            },
        ) as span:
            try:
                state = self.pipeline.execute(state)
                state = self.pipeline.capture_runtime_traces(state)
                latency_ms = (time.perf_counter() - start_time) * 1000
                if state.has_evidence:
                    self.pipeline.emit_completion(message_callback, latency_ms)
                trace_bundle = self.trace_assembler.record(
                    state=state,
                    latency_ms=latency_ms,
                    answer=state.answer,
                )
                state.trace_event = trace_bundle.trace_event
                result = self.result_factory.from_pipeline_state(
                    state,
                    latency_ms=latency_ms,
                    trace_bundle=trace_bundle,
                )
            except Exception as exc:
                request_control.cancel("answer_workflow_failed")
                log_failure(
                    logger,
                    logging.ERROR,
                    "answer_workflow_failed",
                    code="ANSWER_FAILED",
                    error=exc,
                )
                state = self.pipeline.capture_runtime_traces(state)
                latency_ms = (time.perf_counter() - start_time) * 1000
                trace_bundle = self.trace_assembler.record(
                    state=state,
                    latency_ms=latency_ms,
                    error=answer_error_detail(exc),
                )
                state.trace_event = trace_bundle.trace_event
                result = self.result_factory.from_error(
                    state,
                    latency_ms=latency_ms,
                    trace_bundle=trace_bundle,
                    error=exc,
                )
            self.telemetry.enrich_answer_span(span, result)
            self.telemetry.record_answer(result)
            return result

    def _new_request_control(self) -> RequestControl:
        generation = self.config.generation
        budget = float(getattr(generation, "generation_latency_budget_seconds", 30.0) or 30.0)
        return RequestControl.for_timeout(budget, scope="answer")

    def answer_question_response(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResponse:
        return self.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
            control=control,
        ).to_response()


__all__ = ["AnswerWorkflow"]
