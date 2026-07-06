"""Token usage accounting for generation client calls."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from .parsing import estimate_tokens

_TokenUsage = tuple[int, int, int, str]


class GenerationTokenUsageTracker:
    def __init__(self, namespace: str) -> None:
        self._token_usage: ContextVar[_TokenUsage] = ContextVar(
            namespace,
            default=(0, 0, 0, ""),
        )

    def consume(self) -> dict[str, int | str]:
        prompt_tokens, completion_tokens, total_tokens, source = self._token_usage.get()
        self._token_usage.set((0, 0, 0, ""))
        return {
            "prompt_tokens": max(0, int(prompt_tokens or 0)),
            "completion_tokens": max(0, int(completion_tokens or 0)),
            "total_tokens": max(0, int(total_tokens or 0)),
            "token_usage_source": str(source or ""),
        }

    def record_provider(self, response: Any) -> bool:
        usage = (
            response.get("usage")
            if isinstance(response, dict)
            else getattr(response, "usage", None)
        )
        if usage is None:
            return False

        def value(*names: str) -> int:
            for name in names:
                raw = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
                if raw is not None:
                    return max(0, int(raw or 0))
            return 0

        prompt_tokens = value("prompt_tokens", "input_tokens")
        completion_tokens = value("completion_tokens", "output_tokens")
        total_tokens = value("total_tokens") or prompt_tokens + completion_tokens
        current_prompt, current_completion, current_total, _source = self._token_usage.get()
        self._token_usage.set(
            (
                current_prompt + prompt_tokens,
                current_completion + completion_tokens,
                current_total + total_tokens,
                "provider",
            )
        )
        return True

    def record_estimated(self, *, prompt: str, completion: str) -> None:
        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(completion)
        current_prompt, current_completion, current_total, current_source = self._token_usage.get()
        self._token_usage.set(
            (
                current_prompt + prompt_tokens,
                current_completion + completion_tokens,
                current_total + prompt_tokens + completion_tokens,
                current_source or "estimated",
            )
        )


__all__ = ["GenerationTokenUsageTracker"]
