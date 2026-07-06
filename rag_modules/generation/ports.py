"""Ports consumed by generation services."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import Protocol

from ..contracts import RequestControl


class LLMCompletionMessagePort(Protocol):
    """Completion message shape consumed by generation adapters."""

    content: str | None


class LLMCompletionChoicePort(Protocol):
    """Completion choice shape consumed by generation adapters."""

    message: LLMCompletionMessagePort


class LLMCompletionResponsePort(Protocol):
    """Completion response shape consumed by generation adapters."""

    choices: Sequence[LLMCompletionChoicePort]


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


class LLMClientPort(Protocol):
    """Provider-neutral LLM behavior consumed by generation services."""

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


class StreamingLLMClientPort(LLMClientPort, Protocol):
    """Provider-neutral streaming LLM behavior consumed by answer generation."""

    def stream_prompt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        retries: int,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
    ) -> Iterator[str]: ...


__all__ = [
    "LLMChatPort",
    "LLMClientPort",
    "LLMCompletionChoicePort",
    "LLMCompletionMessagePort",
    "LLMCompletionResponsePort",
    "LLMCompletionsPort",
    "OpenAICompatibleLLMClientPort",
    "StreamingLLMClientPort",
]
