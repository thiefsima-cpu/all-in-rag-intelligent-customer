"""Canonical context-native generation service."""

from __future__ import annotations

import logging

from ..configuration.models import GraphRAGConfig
from ..runtime import AnswerContext, GenerationSnapshot
from .context_factory import GenerationContextFactory
from .models import AnswerPlan, RenderedPrompt
from .module_builder import build_generation_runtime

logger = logging.getLogger(__name__)


class GenerationWorkflowService:
    """Canonical generation workflow that only accepts runtime contracts."""

    def __init__(
        self,
        model_name: str = "qwen3.7-plus",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        *,
        api_key: str = "",
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_seconds: int = 45,
        stream_timeout_seconds: int = 45,
        latency_budget_seconds: int = 24,
        planner_max_tokens: int = 600,
        composer_max_tokens: int = 1100,
        direct_max_tokens: int = 700,
        planner_temperature: float = 0.0,
        planner_mode: str = "rule",
        max_retries: int = 1,
        request_retries: int = 1,
        stream_retries: int = 1,
        evidence_max_chars: int = 700,
        enable_two_stage: bool = True,
        two_stage_complexity_threshold: float = 0.68,
        two_stage_relationship_threshold: float = 0.58,
        direct_max_evidence_items: int = 2,
        two_stage_max_evidence_items: int = 3,
        plan_max_evidence_items: int = 2,
        max_graph_paths_per_item: int = 1,
        max_evidence_units_per_item: int = 4,
        include_document_evidence: bool = False,
        compose_include_content: bool = False,
        fallback_on_timeout: bool = False,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
        input_cost_per_million_tokens: float = 0.0,
        output_cost_per_million_tokens: float = 0.0,
    ) -> None:
        components = build_generation_runtime(
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            stream_timeout_seconds=stream_timeout_seconds,
            latency_budget_seconds=latency_budget_seconds,
            planner_max_tokens=planner_max_tokens,
            composer_max_tokens=composer_max_tokens,
            direct_max_tokens=direct_max_tokens,
            planner_temperature=planner_temperature,
            planner_mode=planner_mode,
            max_retries=max_retries,
            request_retries=request_retries,
            stream_retries=stream_retries,
            evidence_max_chars=evidence_max_chars,
            enable_two_stage=enable_two_stage,
            two_stage_complexity_threshold=two_stage_complexity_threshold,
            two_stage_relationship_threshold=two_stage_relationship_threshold,
            direct_max_evidence_items=direct_max_evidence_items,
            two_stage_max_evidence_items=two_stage_max_evidence_items,
            plan_max_evidence_items=plan_max_evidence_items,
            max_graph_paths_per_item=max_graph_paths_per_item,
            max_evidence_units_per_item=max_evidence_units_per_item,
            include_document_evidence=include_document_evidence,
            compose_include_content=compose_include_content,
            fallback_on_timeout=fallback_on_timeout,
            circuit_breaker_failure_threshold=circuit_breaker_failure_threshold,
            circuit_breaker_recovery_seconds=circuit_breaker_recovery_seconds,
            input_cost_per_million_tokens=input_cost_per_million_tokens,
            output_cost_per_million_tokens=output_cost_per_million_tokens,
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

        logger.info("Generation workflow service initialized with model %s", self.model_name)

    @classmethod
    def from_config(cls, config: GraphRAGConfig) -> "GenerationWorkflowService":
        models = config.models
        generation = config.generation
        return cls(
            model_name=models.llm_model,
            temperature=generation.temperature,
            max_tokens=generation.max_tokens,
            api_key=models.api_key,
            base_url=models.llm_base_url,
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
            evidence_max_chars=generation.generation_evidence_max_chars,
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
            circuit_breaker_failure_threshold=(models.circuit_breaker_failure_threshold),
            circuit_breaker_recovery_seconds=(models.circuit_breaker_recovery_seconds),
            input_cost_per_million_tokens=(models.llm_input_cost_per_million_tokens),
            output_cost_per_million_tokens=(models.llm_output_cost_per_million_tokens),
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
