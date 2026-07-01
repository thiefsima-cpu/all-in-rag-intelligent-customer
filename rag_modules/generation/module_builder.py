"""Runtime assembly for the generation module."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..answer_evidence_builder import AnswerEvidenceBuilder
from ..query_policy.models import QueryPolicyBundle
from ..runtime_contracts import LLMClientPort
from .clients import GenerationClientAdapter, build_openai_client, resolve_api_key
from .execution import GenerationExecutionEngine
from .models import GenerationSettings
from .planner import GenerationPlanner
from .prompt_builder import GenerationPromptBuilder

DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
GenerationClientFactory = Callable[[], Any]
EMPTY_EVIDENCE_ANSWER = "抱歉，我暂时没有检索到足够的证据来回答这个问题。"


@dataclass(slots=True)
class GenerationRuntimeComponents:
    settings: GenerationSettings
    base_url: str
    evidence_max_chars: int
    evidence_builder: AnswerEvidenceBuilder
    client: Any
    llm_client: LLMClientPort
    client_adapter: GenerationClientAdapter
    prompt_builder: GenerationPromptBuilder
    planner: GenerationPlanner
    executor: GenerationExecutionEngine


def build_generation_runtime(
    *,
    settings: GenerationSettings | None = None,
    api_key: str = "",
    base_url: str = DEFAULT_BASE_URL,
    evidence_max_chars: int = 700,
    client_factory: GenerationClientFactory | None = None,
    prompt_policy: QueryPolicyBundle | None = None,
    circuit_breaker_failure_threshold: int = 5,
    circuit_breaker_recovery_seconds: float = 30.0,
    empty_evidence_answer: str = EMPTY_EVIDENCE_ANSWER,
) -> GenerationRuntimeComponents:
    settings = settings or GenerationSettings()
    resolved_base_url = str(base_url or DEFAULT_BASE_URL)
    resolved_evidence_max_chars = max(300, int(evidence_max_chars or 700))
    evidence_builder = AnswerEvidenceBuilder(max_content_chars=resolved_evidence_max_chars)
    client = (
        client_factory()
        if client_factory
        else build_openai_client(
            api_key=resolve_api_key(api_key),
            base_url=resolved_base_url,
        )
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
        policy_bundle=prompt_policy,
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
        llm_client=client_adapter,
        client_adapter=client_adapter,
        prompt_builder=prompt_builder,
        planner=planner,
        executor=executor,
    )
