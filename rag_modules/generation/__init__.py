"""Generation submodules for decision, planning, prompting, and fallback."""

from .clients import GenerationClientAdapter, build_openai_client, resolve_api_key
from .decision import decide_generation_mode
from .execution import GenerationExecutionEngine
from .fallback import build_evidence_only_fallback_answer, should_skip_model_fallback
from .models import (
    AnswerPlan,
    GenerationDecision,
    GenerationSettings,
    GenerationTrace,
    RenderedPrompt,
)
from .planner import GenerationPlanner
from .prompt_builder import GenerationPromptBuilder
from .service import GenerationWorkflowService

__all__ = [
    "AnswerPlan",
    "GenerationWorkflowService",
    "GenerationClientAdapter",
    "GenerationDecision",
    "GenerationExecutionEngine",
    "GenerationPlanner",
    "GenerationPromptBuilder",
    "GenerationSettings",
    "GenerationTrace",
    "RenderedPrompt",
    "build_evidence_only_fallback_answer",
    "build_openai_client",
    "decide_generation_mode",
    "resolve_api_key",
    "should_skip_model_fallback",
]
