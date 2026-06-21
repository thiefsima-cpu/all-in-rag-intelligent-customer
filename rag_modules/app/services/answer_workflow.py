"""Canonical question-answer workflow."""

from __future__ import annotations

import logging
import time

from ...telemetry import get_runtime_telemetry
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

logger = logging.getLogger(__name__)


class AnswerWorkflow:
    """Execute the full question-answer lifecycle over stable runtime contracts."""

    def __init__(
        self,
        config,
        query_router,
        generation_module,
        query_tracer,
        *,
        pipeline: AnswerPipelineService | None = None,
        trace_assembler: AnswerTraceAssembler | None = None,
        result_factory: QuestionAnswerResultFactory | None = None,
        telemetry=None,
    ) -> None:
        self.config = config
        self.retrieval_settings = config.retrieval
        self.query_router = query_router
        self.generation_service = generation_module
        self.generation_module = generation_module
        self.query_tracer = query_tracer
        self.telemetry = telemetry or get_runtime_telemetry(config)
        self.pipeline = pipeline or AnswerPipelineService(
            query_router=query_router,
            generation_service=generation_module,
            top_k=self.retrieval_settings.top_k,
            telemetry=self.telemetry,
        )
        self.trace_assembler = trace_assembler or AnswerTraceAssembler(
            query_tracer=query_tracer,
        )
        self.result_factory = result_factory or QuestionAnswerResultFactory()

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResult:
        start_time = time.perf_counter()
        state = AnswerPipelineState(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
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
                logger.error("Question answering failed: %s", exc)
                state = self.pipeline.capture_runtime_traces(state)
                latency_ms = (time.perf_counter() - start_time) * 1000
                trace_bundle = self.trace_assembler.record(
                    state=state,
                    latency_ms=latency_ms,
                    error=str(exc),
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

    def answer_question_response(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResponse:
        return self.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        ).to_response()


__all__ = ["AnswerWorkflow"]
