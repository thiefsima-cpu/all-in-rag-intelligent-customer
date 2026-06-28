"""Serving API service implementation."""

from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import Iterator, Optional

from ....app.application_protocol import GraphRAGApplication
from ....configuration.models import GraphRAGConfig
from ....runtime.artifacts import ArtifactManifestStore
from ....runtime.artifacts.registry import ArtifactRegistry
from ..answer_models import AnswerStreamEventModel
from ..error_models import ErrorCode, sanitize_public_error_fields
from ..request_context import normalize_or_generate_request_id
from .base import _BaseGraphRAGApiService
from .errors import (
    AnswerFailedError,
    ApiBackpressureError,
    SystemNotReadyError,
    _StreamCancelledError,
)


class _StreamEnd:
    pass


_STREAM_END = _StreamEnd()


class _AnswerAdmissionController:
    def __init__(self, *, max_concurrent_answers: int, acquire_timeout_seconds: float) -> None:
        self.max_concurrent_answers = max(0, int(max_concurrent_answers or 0))
        self.acquire_timeout_seconds = max(0.0, float(acquire_timeout_seconds or 0.0))
        self._semaphore = (
            threading.BoundedSemaphore(self.max_concurrent_answers)
            if self.max_concurrent_answers > 0
            else None
        )

    @contextmanager
    def permit(self):
        semaphore = self._semaphore
        if semaphore is None:
            yield
            return
        if not semaphore.acquire(timeout=self.acquire_timeout_seconds):
            raise ApiBackpressureError()
        try:
            yield
        finally:
            semaphore.release()


class GraphRAGServingApiService(_BaseGraphRAGApiService):
    """HTTP-facing serving surface for online answer generation."""

    _MODE = "serve"

    def __init__(
        self,
        *,
        system: GraphRAGApplication | None = None,
        config: Optional[GraphRAGConfig] = None,
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        self._validate_startup_config = system is None
        super().__init__(system=system, config=config)
        self._stream_executor: ThreadPoolExecutor | None = None
        self._stream_executor_lock = threading.Lock()
        resolved_config = config or getattr(self.system, "config", None)
        api_settings = getattr(resolved_config, "api", None)
        self._answer_admission = _AnswerAdmissionController(
            max_concurrent_answers=getattr(api_settings, "max_concurrent_answers", 0),
            acquire_timeout_seconds=getattr(
                api_settings,
                "answer_acquire_timeout_seconds",
                0.25,
            ),
        )
        self._stream_executor_max_workers = max(
            1,
            int(getattr(api_settings, "stream_executor_max_workers", 4)),
        )
        self._stream_queue_max_size = max(
            1,
            int(getattr(api_settings, "stream_queue_max_size", 64)),
        )
        self._artifact_registry = artifact_registry
        if self._artifact_registry is None and resolved_config is not None:
            self._artifact_registry = ArtifactRegistry(ArtifactManifestStore(resolved_config))
        api_settings = getattr(resolved_config, "api", None)
        self._hot_refresh_enabled = bool(getattr(api_settings, "serving_hot_refresh_enabled", True))
        self._hot_refresh_interval_seconds = max(
            0.1,
            float(
                getattr(
                    api_settings,
                    "serving_hot_refresh_interval_seconds",
                    2.0,
                )
            ),
        )
        self._last_hot_refresh_check = 0.0
        self._hot_refresh_check_lock = threading.Lock()

    def _validate_required_model_api_key(self) -> None:
        if not self._validate_startup_config:
            return
        api_key = str(getattr(self.system.config.models, "api_key", "") or "").strip()
        if api_key:
            return
        raise ValueError(
            "Missing model provider API key. Set DASHSCOPE_API_KEY, OPENAI_API_KEY, "
            "or MOONSHOT_API_KEY before starting graph-rag-api. When using Docker Compose, "
            "define the key in the project .env file so the api service can receive it."
        )

    def _ensure_serving_runtime_initialized(self) -> None:
        self._ensure_runtime_initialized(
            is_initialized=self.system.is_serving_initialized,
            initializer=self.system.initialize_serving_runtime,
        )

    def _raise_if_system_not_ready(self) -> None:
        if self.system.system_ready:
            return
        raise SystemNotReadyError(
            "Serving runtime is assembled, but required artifacts are not ready. "
            "Build the knowledge base first.",
            diagnostics=self._collect_startup_diagnostics_unlocked(self._MODE),
        )

    def _refresh_serving_runtime_if_stale(self, *, force_check: bool = False) -> bool:
        if not self._hot_refresh_enabled or self._artifact_registry is None:
            return False
        now = time.monotonic()
        with self._hot_refresh_check_lock:
            if (
                not force_check
                and now - self._last_hot_refresh_check < self._hot_refresh_interval_seconds
            ):
                return False
            self._last_hot_refresh_check = now
        current_manifest = getattr(self.system, "artifact_manifest", None)
        if not self._artifact_registry.has_newer_active(current_manifest):
            return False
        refresher = getattr(self.system, "refresh_serving_runtime", None)
        if not callable(refresher):
            return False
        with self._exclusive_runtime_operation():
            current_manifest = getattr(self.system, "artifact_manifest", None)
            if not self._artifact_registry.has_newer_active(current_manifest):
                return False
            refresher(force=True)
            self._stats_cache = None
            self._diagnostics_cache.clear()
        return True

    def startup(self, *, auto_initialize_serving: bool = False) -> None:
        self._validate_required_model_api_key()
        if not auto_initialize_serving:
            return
        self._ensure_serving_runtime_initialized()

    def health(self) -> dict:
        if self.system.is_serving_initialized():
            self._refresh_serving_runtime_if_stale()
        return self._health_payload(self.collect_startup_diagnostics(self._MODE))

    def readiness(self) -> dict:
        if self.system.is_serving_initialized():
            self._refresh_serving_runtime_if_stale()
        diagnostics = self.collect_startup_diagnostics(self._MODE)
        return self._readiness_payload(
            diagnostics,
            ready=bool(diagnostics["system_ready"]),
        )

    def initialize_serving_runtime(self) -> dict:
        with self._exclusive_runtime_operation():
            if not self.system.is_serving_initialized():
                self.system.initialize_serving_runtime()
            diagnostics = self._collect_startup_diagnostics_unlocked(self._MODE)
            message = (
                "Serving runtime initialized."
                if diagnostics["system_ready"]
                else "Serving runtime initialized, but retrieval artifacts are not ready yet."
            )
            return self._operation_response(message=message, mode=self._MODE)

    def refresh_serving_runtime(self) -> dict:
        self._ensure_serving_runtime_initialized()
        refresher = getattr(self.system, "refresh_serving_runtime", None)
        if not callable(refresher):
            raise RuntimeError("Application does not support serving-runtime refresh.")
        with self._exclusive_runtime_operation():
            refresher(force=True)
            self._stats_cache = None
            self._diagnostics_cache.clear()
            return self._operation_response(
                message="Serving runtime refreshed from the active artifact manifest.",
                mode=self._MODE,
            )

    def shutdown(self) -> None:
        executor = self._stream_executor
        self._stream_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        super().shutdown()

    @staticmethod
    def _answer_payload(response) -> dict:
        payload = response.to_dict()
        summary = dict(payload.get("summary") or {})
        if str(summary.get("status") or "").lower() == "failed":
            raise AnswerFailedError()
        return payload

    def answer_question(
        self,
        *,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
    ) -> dict:
        self._ensure_serving_runtime_initialized()
        self._refresh_serving_runtime_if_stale()
        self._raise_if_system_not_ready()
        with self._answer_admission.permit():
            with self._locks.answer_operation():
                self._raise_if_system_not_ready()
                response = self.system.answer_question_response(
                    question=question,
                    stream=stream,
                    explain_routing=explain_routing,
                )
                return self._answer_payload(response)

    def stream_answer_question_events(
        self,
        *,
        question: str,
        explain_routing: bool = False,
        request_id: str = "",
    ) -> Iterator[AnswerStreamEventModel]:
        self._ensure_serving_runtime_initialized()
        self._refresh_serving_runtime_if_stale()
        self._raise_if_system_not_ready()
        resolved_request_id = normalize_or_generate_request_id(request_id)
        return self._iter_stream_answer_question_events(
            question=question,
            explain_routing=explain_routing,
            request_id=resolved_request_id,
        )

    def _iter_stream_answer_question_events(
        self,
        *,
        question: str,
        explain_routing: bool = False,
        request_id: str,
    ) -> Iterator[AnswerStreamEventModel]:
        event_queue: "queue.Queue[AnswerStreamEventModel | _StreamEnd]" = queue.Queue(
            maxsize=self._stream_queue_max_size
        )
        stream_closed = threading.Event()

        def emit(event: AnswerStreamEventModel) -> None:
            while True:
                if stream_closed.is_set():
                    raise _StreamCancelledError()
                try:
                    event_queue.put(event, timeout=0.1)
                    return
                except queue.Full:
                    continue

        def finish_stream() -> None:
            while True:
                if stream_closed.is_set():
                    return
                try:
                    event_queue.put(_STREAM_END, timeout=0.1)
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
                with self._answer_admission.permit():
                    with self._locks.answer_operation():
                        self._raise_if_system_not_ready()
                        response = self.system.answer_question_response(
                            question=question,
                            stream=True,
                            explain_routing=explain_routing,
                            message_callback=on_message,
                            chunk_callback=on_chunk,
                        )
                safe_payload = sanitize_public_error_fields(
                    self._answer_payload(response),
                    code=ErrorCode.ANSWER_FAILED,
                )
                emit(AnswerStreamEventModel.result(safe_payload))
            except ApiBackpressureError:
                emit_error(ErrorCode.RATE_LIMITED)
            except _StreamCancelledError:
                pass
            except SystemNotReadyError:
                emit_error(ErrorCode.SYSTEM_NOT_READY)
            except AnswerFailedError:
                emit_error(ErrorCode.ANSWER_FAILED)
            except Exception:
                emit_error(ErrorCode.ANSWER_FAILED)
            finally:
                finish_stream()

        future: Future[None] = self._resolve_stream_executor().submit(runner)

        try:
            while True:
                item = event_queue.get()
                if isinstance(item, _StreamEnd):
                    yield AnswerStreamEventModel.done()
                    break
                yield item
        finally:
            stream_closed.set()
            future.cancel()

    def _resolve_stream_executor(self) -> ThreadPoolExecutor:
        executor = self._stream_executor
        if executor is not None:
            return executor
        with self._stream_executor_lock:
            executor = self._stream_executor
            if executor is None:
                executor = ThreadPoolExecutor(
                    max_workers=self._stream_executor_max_workers,
                    thread_name_prefix="graph-rag-answer",
                )
                self._stream_executor = executor
        return executor


__all__ = ["GraphRAGServingApiService"]
