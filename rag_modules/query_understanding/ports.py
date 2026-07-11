"""Ports consumed by query-understanding services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from ..contracts import RequestControl
from ..contracts.runtime import QueryAnalysis, QueryUnderstandingSnapshot


class LLMCompletionMessagePort(Protocol):
    """Completion message shape consumed by query planning."""

    content: str | None


class LLMCompletionChoicePort(Protocol):
    """Completion choice shape consumed by query planning."""

    message: LLMCompletionMessagePort


class LLMCompletionResponsePort(Protocol):
    """Completion response shape consumed by query planning."""

    choices: Sequence[LLMCompletionChoicePort]


class LLMClientPort(Protocol):
    """Provider-neutral LLM behavior consumed by query-understanding services."""

    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int | float,
        model_name: str | None = None,
        control: RequestControl | None = None,
    ) -> LLMCompletionResponsePort: ...


class LLMCompletionsPort(Protocol):
    """OpenAI-compatible chat completions namespace used at adapter boundaries."""

    def create(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: int | float,
    ) -> LLMCompletionResponsePort: ...


class LLMChatPort(Protocol):
    """OpenAI-compatible chat namespace used at adapter boundaries."""

    completions: LLMCompletionsPort


class OpenAICompatibleLLMClientPort(Protocol):
    """Raw OpenAI-compatible client shape used at adapter boundaries."""

    chat: LLMChatPort


class QueryUnderstandingPort(Protocol):
    """Query-understanding behavior consumed by routing and app composition."""

    def understand(
        self,
        query: str,
        *,
        control: RequestControl | None = None,
    ) -> QueryUnderstandingSnapshot: ...

    def analyze(
        self,
        query: str,
        *,
        control: RequestControl | None = None,
    ) -> QueryAnalysis: ...

    def explain(
        self,
        query: str,
        *,
        control: RequestControl | None = None,
    ) -> str: ...


__all__ = [
    "LLMChatPort",
    "LLMClientPort",
    "LLMCompletionChoicePort",
    "LLMCompletionMessagePort",
    "LLMCompletionResponsePort",
    "LLMCompletionsPort",
    "OpenAICompatibleLLMClientPort",
    "QueryUnderstandingPort",
]
