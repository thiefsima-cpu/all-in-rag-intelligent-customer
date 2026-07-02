"""Application protocol used by thin API interfaces."""

from __future__ import annotations

from typing import Any, Protocol

from ..configuration.models import GraphRAGConfig
from .composition.shared import ProgressCallback
from .diagnostics import StartupDiagnostics
from .runtime_state import BuildRuntime, ServingRuntime
from .services.answer_models import QuestionAnswerResponse, QuestionAnswerResult


class GraphRAGApplication(Protocol):
    """Thin application contract for CLI and future service adapters."""

    config: GraphRAGConfig

    @property
    def system_ready(self) -> bool: ...

    def is_build_initialized(self) -> bool: ...

    def is_serving_initialized(self) -> bool: ...

    def initialize_build_runtime(
        self,
        progress: ProgressCallback = None,
        *,
        neo4j_manager: Any | None = None,
    ) -> BuildRuntime: ...

    def initialize_serving_runtime(
        self,
        progress: ProgressCallback = None,
        *,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
    ) -> ServingRuntime: ...

    def build_knowledge_base(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def rebuild_knowledge_base(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def refresh_serving_runtime(
        self,
        progress: ProgressCallback = None,
        *,
        force: bool = True,
    ) -> ServingRuntime: ...

    def collect_system_stats(self) -> dict[str, Any]: ...

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics: ...

    def answer_question(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: ProgressCallback = None,
        chunk_callback: ProgressCallback = None,
    ) -> QuestionAnswerResult: ...

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: ProgressCallback = None,
        chunk_callback: ProgressCallback = None,
    ) -> QuestionAnswerResponse: ...

    def close(self) -> None: ...


__all__ = ["GraphRAGApplication"]
