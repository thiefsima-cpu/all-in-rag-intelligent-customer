"""Serving API service implementation."""

from __future__ import annotations

from typing import Any, Iterator, Optional

from ....app.application_protocol import GraphRAGApplication
from ....app.services.answer_models import QuestionAnswerResponse
from ....configuration.models import GraphRAGConfig
from ....runtime.artifacts import ArtifactManifestStore
from ....runtime.artifacts.registry import ArtifactRegistry
from ..answer_models import AnswerPayloadModel, AnswerStreamEventModel
from ..request_context import normalize_or_generate_request_id
from .base import _BaseGraphRAGApiService
from .errors import AnswerFailedError
from .serving_admission import (
    DEFAULT_MAX_CONCURRENT_ANSWERS,
    ServingAnswerAdmissionController,
)
from .serving_hot_refresh import ServingHotRefreshCoordinator
from .serving_readiness import ServingRuntimeReadinessGuard
from .serving_streams import ServingSseRunner


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
        resolved_config = config or getattr(self.system, "config", None)
        api_settings = getattr(resolved_config, "api", None)
        self._answer_admission = ServingAnswerAdmissionController(
            max_concurrent_answers=getattr(
                api_settings,
                "max_concurrent_answers",
                DEFAULT_MAX_CONCURRENT_ANSWERS,
            ),
            acquire_timeout_seconds=getattr(
                api_settings,
                "answer_acquire_timeout_seconds",
                0.25,
            ),
        )
        stream_executor_max_workers = getattr(api_settings, "stream_executor_max_workers", 4)
        stream_queue_max_size = getattr(api_settings, "stream_queue_max_size", 64)
        self._runtime_readiness = ServingRuntimeReadinessGuard(
            system=self.system,
            ensure_runtime_initialized=self._ensure_runtime_initialized,
            collect_startup_diagnostics=self._collect_startup_diagnostics_unlocked,
            mode=self._MODE,
        )
        resolved_artifact_registry = artifact_registry
        if resolved_artifact_registry is None and resolved_config is not None:
            resolved_artifact_registry = ArtifactRegistry(ArtifactManifestStore(resolved_config))
        self._hot_refresh = ServingHotRefreshCoordinator(
            system=self.system,
            artifact_registry=resolved_artifact_registry,
            enabled=getattr(api_settings, "serving_hot_refresh_enabled", True),
            interval_seconds=getattr(
                api_settings,
                "serving_hot_refresh_interval_seconds",
                2.0,
            ),
            exclusive_runtime_operation=self._exclusive_runtime_operation,
            invalidate_runtime_cache=self._invalidate_runtime_cache,
        )
        self._stream_runner = ServingSseRunner(
            system=self.system,
            admission_controller=self._answer_admission,
            answer_operation=self._locks.answer_operation,
            readiness_guard=self._runtime_readiness,
            answer_payload_factory=self._answer_payload,
            max_workers=stream_executor_max_workers,
            queue_max_size=stream_queue_max_size,
        )
        self._stream_executor_max_workers = self._stream_runner.max_workers
        self._stream_queue_max_size = self._stream_runner.queue_max_size

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
        self._runtime_readiness.ensure_initialized()

    def _raise_if_system_not_ready(self) -> None:
        self._runtime_readiness.raise_if_system_not_ready()

    def _refresh_serving_runtime_if_stale(self, *, force_check: bool = False) -> bool:
        return self._hot_refresh.refresh_if_stale(force_check=force_check)

    def _invalidate_runtime_cache(self) -> None:
        self._stats_cache = None
        self._diagnostics_cache.clear()

    def startup(self, *, auto_initialize_serving: bool = False) -> None:
        self._validate_required_model_api_key()
        if not auto_initialize_serving:
            return
        self._ensure_serving_runtime_initialized()

    def health(self) -> dict[str, Any]:
        if self.system.is_serving_initialized():
            self._refresh_serving_runtime_if_stale()
        return self._health_payload(self.collect_startup_diagnostics(self._MODE))

    def readiness(self) -> dict[str, Any]:
        if self.system.is_serving_initialized():
            self._refresh_serving_runtime_if_stale()
        diagnostics = self.collect_startup_diagnostics(self._MODE)
        return self._readiness_payload(
            diagnostics,
            ready=bool(diagnostics["system_ready"]),
        )

    def initialize_serving_runtime(self) -> dict[str, Any]:
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

    def refresh_serving_runtime(self) -> dict[str, Any]:
        self._ensure_serving_runtime_initialized()
        return self._hot_refresh.refresh_runtime(
            after_refresh=lambda: self._operation_response(
                message="Serving runtime refreshed from the active artifact manifest.",
                mode=self._MODE,
            )
        )

    def shutdown(self) -> None:
        self._stream_runner.shutdown()
        super().shutdown()

    @staticmethod
    def _answer_payload(response: QuestionAnswerResponse) -> AnswerPayloadModel:
        payload = AnswerPayloadModel.from_dto(response)
        if str(payload.summary.status or "").lower() == "failed":
            raise AnswerFailedError()
        return payload

    def answer_question(
        self,
        *,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
    ) -> AnswerPayloadModel:
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
        include_traces: bool = True,
    ) -> Iterator[AnswerStreamEventModel]:
        self._ensure_serving_runtime_initialized()
        self._refresh_serving_runtime_if_stale()
        self._raise_if_system_not_ready()
        resolved_request_id = normalize_or_generate_request_id(request_id)
        return self._stream_runner.stream_answer_question_events(
            question=question,
            explain_routing=explain_routing,
            request_id=resolved_request_id,
            include_traces=include_traces,
        )


__all__ = ["GraphRAGServingApiService"]
