"""Resolve lazy runtime-bound application services for grouped runtime views."""

from __future__ import annotations

from typing import Any

from .runtime_state import ServingRuntime
from .services.question_answer_service import QuestionAnswerService


class QuestionAnswerServiceResolver:
    """Resolve the compat question-answer service from a serving runtime lazily."""

    def resolve(self, serving_runtime: ServingRuntime | None) -> Any:
        if not serving_runtime:
            return None
        if serving_runtime.question_answer_service is not None:
            return serving_runtime.question_answer_service
        if serving_runtime.answer_workflow is None:
            return None
        workflow = serving_runtime.answer_workflow
        service = QuestionAnswerService(
            config=getattr(workflow, "config", serving_runtime.config),
            query_router=getattr(workflow, "query_router", None),
            generation_module=getattr(workflow, "generation_module", None),
            query_tracer=getattr(workflow, "query_tracer", None),
            answer_workflow=workflow,
        )
        serving_runtime.question_answer_service = service
        return service


__all__ = ["QuestionAnswerServiceResolver"]
