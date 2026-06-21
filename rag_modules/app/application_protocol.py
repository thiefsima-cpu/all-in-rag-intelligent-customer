"""Application protocol used by thin API interfaces."""

from __future__ import annotations

from typing import Protocol

from .diagnostics import StartupDiagnostics
from .services.answer_models import QuestionAnswerResponse, QuestionAnswerResult


class GraphRAGApplication(Protocol):
    """Thin application contract for CLI and future service adapters."""

    @property
    def system_ready(self) -> bool: ...

    def is_build_initialized(self) -> bool: ...

    def is_serving_initialized(self) -> bool: ...

    def initialize_build_runtime(self, progress=None, *, neo4j_manager=None): ...

    def initialize_serving_runtime(
        self,
        progress=None,
        *,
        query_tracer=None,
        neo4j_manager=None,
    ): ...

    def build_knowledge_base(self, progress=None) -> None: ...

    def rebuild_knowledge_base(self, progress=None) -> None: ...

    def refresh_serving_runtime(self, progress=None, *, force: bool = True): ...

    def collect_system_stats(self) -> dict: ...

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics: ...

    def answer_question(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResult: ...

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResponse: ...

    def close(self) -> None: ...


__all__ = ["GraphRAGApplication"]
