"""Ports consumed by graph retrieval and execution."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Protocol

from ..contracts import RequestControl


class Neo4jRecordPort(Protocol):
    """Neo4j record behavior consumed by graph retrieval."""

    def __getitem__(self, key: str) -> object: ...

    def get(self, key: str, default: object | None = None) -> object: ...


class Neo4jResultPort(Protocol):
    """Neo4j result behavior consumed by graph retrieval."""

    def __iter__(self) -> Iterator[Neo4jRecordPort]: ...


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior consumed by graph execution."""

    def __enter__(self) -> Neo4jSessionPort: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(
        self,
        query: str,
        parameters: object | None = None,
        **kwargs: object,
    ) -> Neo4jResultPort: ...

    def execute_read(
        self,
        transaction_function: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def execute_write(
        self,
        transaction_function: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior consumed by graph execution."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...

    def close(self) -> None: ...


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior consumed by graph services."""

    @property
    def driver(self) -> Neo4jDriverPort: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class LLMCompletionMessagePort(Protocol):
    """Completion message shape consumed by graph retrieval."""

    content: str | None


class LLMCompletionChoicePort(Protocol):
    """Completion choice shape consumed by graph retrieval."""

    message: LLMCompletionMessagePort


class LLMCompletionResponsePort(Protocol):
    """Completion response shape consumed by graph retrieval."""

    choices: Sequence[LLMCompletionChoicePort]


class LLMClientPort(Protocol):
    """Provider-neutral LLM behavior consumed by graph retrieval."""

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


__all__ = [
    "LLMChatPort",
    "LLMClientPort",
    "LLMCompletionChoicePort",
    "LLMCompletionMessagePort",
    "LLMCompletionResponsePort",
    "LLMCompletionsPort",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "Neo4jRecordPort",
    "Neo4jResultPort",
    "Neo4jSessionPort",
    "OpenAICompatibleLLMClientPort",
]
