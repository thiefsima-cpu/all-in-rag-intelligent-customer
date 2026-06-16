"""Runtime assembly for the generation module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..answer_evidence_builder import AnswerEvidenceBuilder
from .client import GenerationClientAdapter, build_openai_client, resolve_api_key
from .execution import GenerationExecutionEngine
from .models import GenerationSettings
from .planner import GenerationPlanner
from .prompt_builder import GenerationPromptBuilder

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMPTY_EVIDENCE_ANSWER = "抱歉，我暂时没有检索到足够的证据来回答这个问题。"


@dataclass(slots=True)
class GenerationRuntimeComponents:
    settings: GenerationSettings
    base_url: str
    evidence_max_chars: int
    evidence_builder: AnswerEvidenceBuilder
    client: Any
    client_adapter: GenerationClientAdapter
    prompt_builder: GenerationPromptBuilder
    planner: GenerationPlanner
    executor: GenerationExecutionEngine


def build_generation_runtime(
    *,
    model_name: str = "qwen3.7-plus",
    temperature: float = 0.1,
    max_tokens: int = 2048,
    api_key: str = "",
    base_url: str = DEFAULT_BASE_URL,
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
    empty_evidence_answer: str = EMPTY_EVIDENCE_ANSWER,
) -> GenerationRuntimeComponents:
    settings = GenerationSettings(
        model_name=model_name,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        stream_timeout_seconds=stream_timeout_seconds,
        latency_budget_seconds=latency_budget_seconds,
        planner_max_tokens=planner_max_tokens,
        composer_max_tokens=composer_max_tokens,
        planner_temperature=planner_temperature,
        planner_mode=planner_mode,
        max_retries=max_retries,
        request_retries=request_retries,
        stream_retries=stream_retries,
        direct_max_tokens=direct_max_tokens,
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
        input_cost_per_million_tokens=input_cost_per_million_tokens,
        output_cost_per_million_tokens=output_cost_per_million_tokens,
    )
    resolved_base_url = str(base_url or DEFAULT_BASE_URL)
    resolved_evidence_max_chars = max(300, int(evidence_max_chars or 700))
    evidence_builder = AnswerEvidenceBuilder(max_content_chars=resolved_evidence_max_chars)
    client = build_openai_client(
        api_key=resolve_api_key(api_key),
        base_url=resolved_base_url,
    )
    client_adapter = GenerationClientAdapter(
        client=client,
        model_name=settings.model_name,
        default_temperature=settings.temperature,
        request_retries=settings.request_retries,
        stream_timeout_seconds=settings.stream_timeout_seconds,
        circuit_breaker_failure_threshold=circuit_breaker_failure_threshold,
        circuit_breaker_recovery_seconds=circuit_breaker_recovery_seconds,
    )
    prompt_builder = GenerationPromptBuilder(
        settings,
        evidence_max_chars=resolved_evidence_max_chars,
    )
    planner = GenerationPlanner(
        settings=settings,
        client_adapter=client_adapter,
        prompt_builder=prompt_builder,
    )
    executor = GenerationExecutionEngine(
        settings=settings,
        client_adapter=client_adapter,
        prompt_builder=prompt_builder,
        planner=planner,
        empty_evidence_answer=empty_evidence_answer,
    )
    return GenerationRuntimeComponents(
        settings=settings,
        base_url=resolved_base_url,
        evidence_max_chars=resolved_evidence_max_chars,
        evidence_builder=evidence_builder,
        client=client,
        client_adapter=client_adapter,
        prompt_builder=prompt_builder,
        planner=planner,
        executor=executor,
    )
