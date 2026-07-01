"""Application-level answering orchestration over runtime state and lifecycle services."""

from __future__ import annotations

from ..services.answer_models import QuestionAnswerResponse, QuestionAnswerResult
from .contracts import SystemOperationsProtocol
from .runtime_state_store import RuntimeStateStore


class SystemAnsweringService:
    """Answer user questions through the runtime-backed answer workflow."""

    def __init__(
        self,
        *,
        backend: SystemOperationsProtocol,
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
        answer_workflow = self.require_answer_workflow()
        result = answer_workflow.answer_question(
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
        answer_workflow = self.require_answer_workflow()
        response = answer_workflow.answer_question_response(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )
        return response

    def require_answer_workflow(self):
        if not self.backend.is_serving_initialized():
            self.backend.initialize_serving_runtime()
        self.backend.require_ready()
        serving_runtime = self.runtime_state_store.serving_runtime
        answer_workflow = serving_runtime.answer_workflow if serving_runtime is not None else None
        if answer_workflow is None:
            raise ValueError("Answer workflow is not initialized.")
        return answer_workflow


__all__ = ["SystemAnsweringService"]
