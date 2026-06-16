"""Generation submodules for decision, planning, prompting, and fallback."""

from .client import GenerationClientAdapter, build_openai_client, resolve_api_key
from .decision import decide_generation_mode
from .fallback import build_evidence_only_fallback_answer, should_skip_model_fallback
from .models import AnswerPlan, GenerationDecision, GenerationSettings, GenerationTrace
from .planner import GenerationPlanner
from .prompt_builder import GenerationPromptBuilder

__all__ = [
    "AnswerPlan",
    "GenerationClientAdapter",
    "GenerationDecision",
    "GenerationPlanner",
    "GenerationPromptBuilder",
    "GenerationSettings",
    "GenerationTrace",
    "build_evidence_only_fallback_answer",
    "build_openai_client",
    "decide_generation_mode",
    "resolve_api_key",
    "should_skip_model_fallback",
]
