"""SSE runner for serving answer streams."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager
from typing import Protocol

from ....app.application_protocol import GraphRAGApplication
from ....application.answering.answer_models import QuestionAnswerResponse
from ....contracts import RequestControl
from ....safe_logging import log_failure
from ..answer_copy import answer_failed_message_from_system
from ..answer_models import (
    AnswerPayloadModel,
    AnswerStreamEventModel,
    PublicAnswerPayloadModel,
)
from ..error_models import ErrorCode
from .errors import (
    AnswerFailedError,
    ApiBackpressureError,
    SystemNotReadyError,
    _StreamCancelledError,
)

logger = logging.getLogger(__name__)

_STREAM_QUEUE_POLL_SECONDS = 0.1


class _StreamEnd:
    pass


_STREAM_END = _StreamEnd()


class _AdmissionController(Protocol):
    def permit(self) -> AbstractContextManager[None]: ...


class _ReadinessGuard(Protocol):
    def raise_if_system_not_ready(self) -> None: ...


class _SseStreamSession:
    def __init__(
        self,
        runner: "ServingSseRunner",
        *,
        question: str,
        explain_routing: bool,
        request_id: str,
        include_traces: bool,
    ) -> None:
        self.runner = runner
        self.question = question
        self.explain_routing = explain_routing
        self.request_id = request_id
        self.include_traces = include_traces
        self.event_queue: "queue.Queue[AnswerStreamEventModel | _StreamEnd]" = queue.Queue(
            maxsize=runner.queue_max_size
        )
        self.stream_closed = threading.Event()
        self.request_control = runner.request_control_factory()
        self.future: Future[None] | None = None
        self.completed = False

    def events(self) -> Iterator[AnswerStreamEventModel]:
        try:
            self.future = self.runner._resolve_executor().submit(self._run)
        except RuntimeError:
            yield AnswerStreamEventModel.error(
                code=ErrorCode.SYSTEM_NOT_READY,
                request_id=self.request_id,
            )
            yield AnswerStreamEventModel.done()
            return

        try:
            yield from self._drain_events(self.future)
        finally:
            self._close()

    def _drain_events(self, future: Future[None]) -> Iterator[AnswerStreamEventModel]:
        while True:
            try:
                item = self.event_queue.get(timeout=_STREAM_QUEUE_POLL_SECONDS)
            except queue.Empty:
                if future.done():
                    yield AnswerStreamEventModel.error(
                        code=ErrorCode.SYSTEM_NOT_READY,
                        request_id=self.request_id,
                    )
                    yield AnswerStreamEventModel.done()
                    break
                continue
            if isinstance(item, _StreamEnd):
                yield AnswerStreamEventModel.done()
                self.completed = True
                break
            yield item

    def _emit(self, event: AnswerStreamEventModel) -> None:
        while True:
            if self.stream_closed.is_set():
                raise _StreamCancelledError()
            try:
                self.event_queue.put(event, timeout=_STREAM_QUEUE_POLL_SECONDS)
                return
            except queue.Full:
                continue

    def _finish_stream(self) -> None:
        while True:
            if self.stream_closed.is_set():
                return
            try:
                self.event_queue.put(_STREAM_END, timeout=_STREAM_QUEUE_POLL_SECONDS)
                return
            except queue.Full:
                continue

    def _on_message(self, message: str) -> None:
        self._emit(AnswerStreamEventModel.message(str(message)))

    def _on_chunk(self, chunk: str) -> None:
        self._emit(AnswerStreamEventModel.chunk(str(chunk)))

    def _emit_error(self, code: ErrorCode) -> None:
        if not self.stream_closed.is_set():
            message = (
                answer_failed_message_from_system(self.runner.system)
                if code == ErrorCode.ANSWER_FAILED
                else None
            )
            self._emit(
                AnswerStreamEventModel.error(
                    code=code,
                    request_id=self.request_id,
                    message=message,
                )
            )

    def _run(self) -> None:
        try:
            response = self._answer_question()
            result_payload = self._result_payload(response)
            self._emit(AnswerStreamEventModel.result(result_payload))
        except ApiBackpressureError:
            self._emit_error(ErrorCode.RATE_LIMITED)
        except _StreamCancelledError:
            pass
        except SystemNotReadyError:
            self._emit_error(ErrorCode.SYSTEM_NOT_READY)
        except AnswerFailedError:
            self._emit_error(ErrorCode.ANSWER_FAILED)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "answer_workflow_failed",
                code=ErrorCode.ANSWER_FAILED.value,
                error=exc,
                request_id=self.request_id,
            )
            self._emit_error(ErrorCode.ANSWER_FAILED)
        finally:
            self._finish_stream()

    def _answer_question(self) -> QuestionAnswerResponse:
        with self.runner.admission_controller.permit():
            with self.runner.answer_operation():
                self.runner.readiness_guard.raise_if_system_not_ready()
                return self.runner.system.answer_question_response(
                    question=self.question,
                    stream=True,
                    explain_routing=self.explain_routing,
                    message_callback=self._on_message,
                    chunk_callback=self._on_chunk,
                    control=self.request_control,
                )

    def _result_payload(
        self,
        response: QuestionAnswerResponse,
    ) -> AnswerPayloadModel | PublicAnswerPayloadModel:
        answer_payload = self.runner.answer_payload_factory(response)
        if self.include_traces:
            return answer_payload
        return PublicAnswerPayloadModel.from_debug_payload(answer_payload)

    def _close(self) -> None:
        if not self.completed:
            self.request_control.cancel("stream_consumer_closed")
        self.stream_closed.set()
        if self.future is not None:
            self.future.cancel()


def _iter_sse_session_events(
    runner: "ServingSseRunner",
    *,
    question: str,
    explain_routing: bool,
    request_id: str,
    include_traces: bool,
) -> Iterator[AnswerStreamEventModel]:
    session = _SseStreamSession(
        runner,
        question=question,
        explain_routing=explain_routing,
        request_id=request_id,
        include_traces=include_traces,
    )
    yield from session.events()


class ServingSseRunner:
    """Run answer generation in a background executor and expose typed SSE events."""

    def __init__(
        self,
        *,
        system: GraphRAGApplication,
        admission_controller: _AdmissionController,
        answer_operation: Callable[[], AbstractContextManager[None]],
        readiness_guard: _ReadinessGuard,
        answer_payload_factory: Callable[[QuestionAnswerResponse], AnswerPayloadModel],
        request_control_factory: Callable[[], RequestControl],
        max_workers: int,
        queue_max_size: int,
    ) -> None:
        self.system = system
        self.admission_controller = admission_controller
        self.answer_operation = answer_operation
        self.readiness_guard = readiness_guard
        self.answer_payload_factory = answer_payload_factory
        self.request_control_factory = request_control_factory
        self.max_workers = max(1, int(max_workers or 1))
        self.queue_max_size = max(1, int(queue_max_size or 1))
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    def shutdown(self) -> None:
        with self._executor_lock:
            executor = self._executor
            self._executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def stream_answer_question_events(
        self,
        *,
        question: str,
        explain_routing: bool,
        request_id: str,
        include_traces: bool,
    ) -> Iterator[AnswerStreamEventModel]:
        return _iter_sse_session_events(
            self,
            question=question,
            explain_routing=explain_routing,
            request_id=request_id,
            include_traces=include_traces,
        )

    def _resolve_executor(self) -> ThreadPoolExecutor:
        executor = self._executor
        if executor is not None:
            return executor
        with self._executor_lock:
            executor = self._executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix="graph-rag-answer",
                )
                self._executor = executor
        return executor


__all__ = ["ServingSseRunner"]
