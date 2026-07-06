"""Request-scoped generation retry and token usage collection."""

from __future__ import annotations

from .contracts import GenerationTokenUsage, non_negative_int


class GenerationUsageCollector:
    """Drain client-adapter counters at explicit execution boundaries."""

    def __init__(self, client_adapter: object) -> None:
        self._client_adapter = client_adapter

    def reset(self) -> None:
        self.drain_token_usage()

    def drain_retry_count(self) -> int:
        consume = getattr(self._client_adapter, "consume_retry_count", None)
        if not callable(consume):
            return 0
        return non_negative_int(consume())

    def drain_token_usage(self) -> GenerationTokenUsage:
        consume = getattr(self._client_adapter, "consume_token_usage", None)
        if not callable(consume):
            return GenerationTokenUsage()
        return GenerationTokenUsage.from_payload(consume())


__all__ = ["GenerationUsageCollector"]
