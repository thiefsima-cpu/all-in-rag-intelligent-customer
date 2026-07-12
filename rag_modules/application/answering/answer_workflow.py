"""Canonical question-answer application use case."""

from __future__ import annotations

import logging
import time

from ...contracts import RequestControl
from ...contracts.runtime.errors import answer_error_detail
from ...safe_logging import log_failure
from ..ports import AnswerTelemetryPort
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
        *,
        pipeline: AnswerPipelineService,
        trace_assembler: AnswerTraceAssembler,
        result_factory: QuestionAnswerResultFactory,
        telemetry: AnswerTelemetryPort,
        generation_latency_budget_seconds: float,
    ) -> None:
        self.pipeline = pipeline
        self.trace_assembler = trace_assembler
        self.result_factory = result_factory
        self.telemetry = telemetry
        self.generation_latency_budget_seconds = max(
            0.0,
            float(generation_latency_budget_seconds),
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
        return RequestControl.for_timeout(
            self.generation_latency_budget_seconds,
            scope="answer",
        )

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
