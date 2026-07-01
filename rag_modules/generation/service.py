"""Canonical context-native generation service."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..configuration.models import GraphRAGConfig
from ..runtime import AnswerContext, GenerationSnapshot
from .context_factory import GenerationContextFactory
from .models import AnswerPlan, GenerationSettings, RenderedPrompt
from .module_builder import (
    DEFAULT_BASE_URL,
    EMPTY_EVIDENCE_ANSWER,
    GenerationClientFactory,
    build_generation_runtime,
)

if TYPE_CHECKING:
    from ..query_policy.models import QueryPolicyBundle

logger = logging.getLogger(__name__)


class GenerationWorkflowService:
    """Canonical generation workflow that only accepts runtime contracts."""

    def __init__(
        self,
        settings: GenerationSettings | None = None,
        *,
        api_key: str = "",
        base_url: str = DEFAULT_BASE_URL,
        evidence_max_chars: int = 700,
        client_factory: GenerationClientFactory | None = None,
        prompt_policy: QueryPolicyBundle | None = None,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
        empty_evidence_answer: str = EMPTY_EVIDENCE_ANSWER,
    ) -> None:
        components = build_generation_runtime(
            settings=settings,
            api_key=api_key,
            base_url=base_url,
            evidence_max_chars=evidence_max_chars,
            client_factory=client_factory,
            prompt_policy=prompt_policy,
            circuit_breaker_failure_threshold=circuit_breaker_failure_threshold,
            circuit_breaker_recovery_seconds=circuit_breaker_recovery_seconds,
            empty_evidence_answer=empty_evidence_answer,
        )
        self.settings = components.settings
        self.model_name = self.settings.model_name
        self.temperature = self.settings.temperature
        self.max_tokens = self.settings.max_tokens
        self.base_url = components.base_url
        self.evidence_max_chars = components.evidence_max_chars
        self.evidence_builder = components.evidence_builder
        self.client = components.client
        self.llm_client = components.llm_client
        self.client_adapter = components.client_adapter
        self.prompt_builder = components.prompt_builder
        self.planner = components.planner
        self.executor = components.executor
        self.context_factory = GenerationContextFactory(self.evidence_builder)

        logger.info("Generation workflow service initialized")

    @classmethod
    def from_config(
        cls,
        config: GraphRAGConfig,
        *,
        client_factory: GenerationClientFactory | None = None,
        prompt_policy: QueryPolicyBundle | None = None,
    ) -> "GenerationWorkflowService":
        models = config.models
        generation = config.generation
        settings = GenerationSettings(
            model_name=models.llm_model,
            temperature=generation.temperature,
            max_tokens=generation.max_tokens,
            timeout_seconds=generation.generation_timeout_seconds,
            stream_timeout_seconds=generation.generation_stream_timeout_seconds,
            latency_budget_seconds=generation.generation_latency_budget_seconds,
            planner_max_tokens=generation.generation_plan_max_tokens,
            composer_max_tokens=generation.generation_compose_max_tokens,
            direct_max_tokens=generation.generation_direct_max_tokens,
            planner_temperature=generation.generation_plan_temperature,
            planner_mode=generation.generation_planner_mode,
            max_retries=generation.generation_max_retries,
            request_retries=generation.generation_request_retries,
            stream_retries=generation.generation_stream_retries,
            enable_two_stage=generation.generation_enable_two_stage,
            two_stage_complexity_threshold=generation.generation_two_stage_complexity_threshold,
            two_stage_relationship_threshold=generation.generation_two_stage_relationship_threshold,
            direct_max_evidence_items=generation.generation_direct_max_evidence_items,
            two_stage_max_evidence_items=generation.generation_two_stage_max_evidence_items,
            plan_max_evidence_items=generation.generation_plan_max_evidence_items,
            max_graph_paths_per_item=generation.generation_max_graph_paths_per_item,
            max_evidence_units_per_item=generation.generation_max_evidence_units_per_item,
            include_document_evidence=generation.generation_include_document_evidence,
            compose_include_content=generation.generation_compose_include_content,
            fallback_on_timeout=generation.generation_fallback_on_timeout,
            input_cost_per_million_tokens=models.llm_input_cost_per_million_tokens,
            output_cost_per_million_tokens=models.llm_output_cost_per_million_tokens,
        )
        return cls(
            settings=settings,
            api_key=models.api_key,
            base_url=models.llm_base_url,
            evidence_max_chars=generation.generation_evidence_max_chars,
            client_factory=client_factory,
            prompt_policy=prompt_policy,
            circuit_breaker_failure_threshold=(models.circuit_breaker_failure_threshold),
            circuit_breaker_recovery_seconds=(models.circuit_breaker_recovery_seconds),
        )

    def generate_answer_from_context(self, answer_context: AnswerContext | dict) -> str:
        context = self._ensure_context(answer_context)
        return self.executor.generate(answer_context=context)

    def generate_answer_with_trace_from_context(
        self,
        answer_context: AnswerContext | dict,
    ) -> tuple[str, GenerationSnapshot]:
        context = self._ensure_context(answer_context)
        answer, trace = self.executor.generate_with_trace(answer_context=context)
        return answer, GenerationSnapshot.from_dict(trace.to_dict())

    def generate_answer_stream_from_context(
        self,
        answer_context: AnswerContext | dict,
        max_retries: int | None = None,
    ):
        context = self._ensure_context(answer_context)
        return self.executor.stream(
            answer_context=context,
            max_retries=max_retries,
        )

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context: AnswerContext | dict,
        *,
        max_retries: int | None = None,
        chunk_callback=None,
    ) -> tuple[str, GenerationSnapshot]:
        context = self._ensure_context(answer_context)
        answer, trace = self.executor.stream_with_trace(
            answer_context=context,
            max_retries=max_retries,
            chunk_callback=chunk_callback,
        )
        return answer, GenerationSnapshot.from_dict(trace.to_dict())

    def build_answer_plan_from_context(
        self,
        answer_context: AnswerContext | dict,
    ) -> AnswerPlan:
        context = self._ensure_context(answer_context)
        return self.planner.build_answer_plan_from_context(context)

    def compose_answer_from_context(
        self,
        answer_context: AnswerContext | dict,
        *,
        plan: AnswerPlan | dict | None = None,
    ) -> str:
        context = self._ensure_context(answer_context)
        resolved_plan = self.context_factory.ensure_plan(
            plan
        ) or self.build_answer_plan_from_context(context)
        return self.executor.compose_from_context(context, resolved_plan)

    def render_plan_prompt_from_context(
        self,
        answer_context: AnswerContext | dict,
    ) -> RenderedPrompt:
        return self.prompt_builder.render_plan_prompt_from_context(
            self._ensure_context(answer_context)
        )

    def render_compose_prompt_from_context(
        self,
        answer_context: AnswerContext | dict,
        *,
        plan: AnswerPlan | dict | None = None,
    ) -> RenderedPrompt:
        context = self._ensure_context(answer_context)
        resolved_plan = self.context_factory.ensure_plan(
            plan
        ) or self.build_answer_plan_from_context(context)
        return self.prompt_builder.render_compose_prompt_from_context(
            context,
            resolved_plan,
        )

    def render_direct_answer_prompt_from_context(
        self,
        answer_context: AnswerContext | dict,
    ) -> RenderedPrompt:
        return self.prompt_builder.render_direct_answer_prompt_from_context(
            self._ensure_context(answer_context)
        )

    def _ensure_context(self, answer_context: AnswerContext | dict) -> AnswerContext:
        return self.context_factory.ensure_evidence_package(
            self.context_factory.ensure_answer_context(answer_context)
        )


__all__ = ["GenerationWorkflowService"]
