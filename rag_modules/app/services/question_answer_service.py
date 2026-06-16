"""Compatibility wrapper over the canonical answer workflow."""

from __future__ import annotations

from .answer_models import (
    ChunkCallback,
    MessageCallback,
    QuestionAnswerResponse,
    QuestionAnswerResult,
)
from .answer_workflow import AnswerWorkflow


class QuestionAnswerService:
    """Compatibility service that delegates to AnswerWorkflow."""

    def __init__(
        self,
        config,
        query_router,
        generation_module,
        query_tracer,
        *,
        answer_workflow: AnswerWorkflow | None = None,
    ) -> None:
        self.workflow = answer_workflow or AnswerWorkflow(
            config=config,
            query_router=query_router,
            generation_module=generation_module,
            query_tracer=query_tracer,
        )
        fallback_retrieval = getattr(config, "retrieval", None)
        self.config = getattr(self.workflow, "config", config)
        self.retrieval_settings = getattr(self.workflow, "retrieval_settings", fallback_retrieval)
        self.query_router = getattr(self.workflow, "query_router", query_router)
        self.generation_service = getattr(self.workflow, "generation_service", generation_module)
        self.generation_module = getattr(self.workflow, "generation_module", generation_module)
        self.query_tracer = getattr(self.workflow, "query_tracer", query_tracer)

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResult:
        return self.workflow.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )

    def answer_question_response(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
    ) -> QuestionAnswerResponse:
        responder = getattr(self.workflow, "answer_question_response", None)
        if callable(responder):
            return responder(
                question=question,
                stream=stream,
                explain_routing=explain_routing,
                message_callback=message_callback,
                chunk_callback=chunk_callback,
            )
        return self.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        ).to_response()


__all__ = ["QuestionAnswerResponse", "QuestionAnswerResult", "QuestionAnswerService"]
