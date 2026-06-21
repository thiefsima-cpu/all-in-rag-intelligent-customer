"""Application-level answering orchestration over runtime state and lifecycle services."""

from __future__ import annotations

from ..services.answer_models import QuestionAnswerResponse, QuestionAnswerResult
from .contracts import SystemAnsweringBackendProtocol
from .runtime_state_store import RuntimeStateStore


class SystemAnsweringService:
    """Answer user questions through the runtime-backed question-answer contract."""

    def __init__(
        self,
        *,
        backend: SystemAnsweringBackendProtocol,
        runtime_state_store: RuntimeStateStore,
    ) -> None:
        self.backend = backend
        self.runtime_state_store = runtime_state_store

    def answer_question(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResult:
        answer_service = self.require_question_answer_service()
        result = answer_service.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )
        return result

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResponse:
        answer_service = self.require_question_answer_service()
        response = answer_service.answer_question_response(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )
        return response

    def require_question_answer_service(self):
        if not self.backend.is_serving_initialized():
            self.backend.initialize_serving_runtime()
        self.backend.require_ready()
        serving_runtime = self.runtime_state_store.serving_runtime
        answer_service = (
            serving_runtime.question_answer_service if serving_runtime is not None else None
        )
        if answer_service is None:
            raise ValueError("Question-answer service is not initialized.")
        return answer_service


__all__ = ["SystemAnsweringService"]
