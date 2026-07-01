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
from ....app.services.answer_models import QuestionAnswerResponse
from ....safe_logging import log_failure
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
        max_workers: int,
        queue_max_size: int,
    ) -> None:
        self.system = system
        self.admission_controller = admission_controller
        self.answer_operation = answer_operation
        self.readiness_guard = readiness_guard
        self.answer_payload_factory = answer_payload_factory
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
        event_queue: "queue.Queue[AnswerStreamEventModel | _StreamEnd]" = queue.Queue(
            maxsize=self.queue_max_size
        )
        stream_closed = threading.Event()

        def emit(event: AnswerStreamEventModel) -> None:
            while True:
                if stream_closed.is_set():
                    raise _StreamCancelledError()
                try:
                    event_queue.put(event, timeout=_STREAM_QUEUE_POLL_SECONDS)
                    return
                except queue.Full:
                    continue

        def finish_stream() -> None:
            while True:
                if stream_closed.is_set():
                    return
                try:
                    event_queue.put(_STREAM_END, timeout=_STREAM_QUEUE_POLL_SECONDS)
                    return
                except queue.Full:
                    continue

        def on_message(message: str) -> None:
            emit(AnswerStreamEventModel.message(str(message)))

        def on_chunk(chunk: str) -> None:
            emit(AnswerStreamEventModel.chunk(str(chunk)))

        def emit_error(code: ErrorCode) -> None:
            if not stream_closed.is_set():
                emit(AnswerStreamEventModel.error(code=code, request_id=request_id))

        def runner() -> None:
            try:
                with self.admission_controller.permit():
                    with self.answer_operation():
                        self.readiness_guard.raise_if_system_not_ready()
                        response = self.system.answer_question_response(
                            question=question,
                            stream=True,
                            explain_routing=explain_routing,
                            message_callback=on_message,
                            chunk_callback=on_chunk,
                        )
                answer_payload = self.answer_payload_factory(response)
                result_payload: AnswerPayloadModel | PublicAnswerPayloadModel = answer_payload
                if not include_traces:
                    result_payload = PublicAnswerPayloadModel.from_debug_payload(answer_payload)
                emit(AnswerStreamEventModel.result(result_payload))
            except ApiBackpressureError:
                emit_error(ErrorCode.RATE_LIMITED)
            except _StreamCancelledError:
                pass
            except SystemNotReadyError:
                emit_error(ErrorCode.SYSTEM_NOT_READY)
            except AnswerFailedError:
                emit_error(ErrorCode.ANSWER_FAILED)
            except Exception as exc:
                log_failure(
                    logger,
                    logging.ERROR,
                    "answer_workflow_failed",
                    code=ErrorCode.ANSWER_FAILED.value,
                    error=exc,
                    request_id=request_id,
                )
                emit_error(ErrorCode.ANSWER_FAILED)
            finally:
                finish_stream()

        try:
            future: Future[None] = self._resolve_executor().submit(runner)
        except RuntimeError:
            yield AnswerStreamEventModel.error(
                code=ErrorCode.SYSTEM_NOT_READY,
                request_id=request_id,
            )
            yield AnswerStreamEventModel.done()
            return

        try:
            while True:
                try:
                    item = event_queue.get(timeout=_STREAM_QUEUE_POLL_SECONDS)
                except queue.Empty:
                    if future.done():
                        yield AnswerStreamEventModel.error(
                            code=ErrorCode.SYSTEM_NOT_READY,
                            request_id=request_id,
                        )
                        yield AnswerStreamEventModel.done()
                        break
                    continue
                if isinstance(item, _StreamEnd):
                    yield AnswerStreamEventModel.done()
                    break
                yield item
        finally:
            stream_closed.set()
            future.cancel()

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
