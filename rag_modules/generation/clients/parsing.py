"""Provider response parsing helpers for generation clients."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from .errors import GenerationProviderResponseError


def response_content(response: Any) -> str:
    choices = (
        response.get("choices")
        if isinstance(response, dict)
        else getattr(response, "choices", None)
    ) or []
    if not choices:
        return ""
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    if message is None:
        return ""
    content = (
        message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    )
    return str(content or "")


def estimate_tokens(text: str) -> int:
    value = str(text or "")
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", value))
    non_cjk_count = max(0, len(value) - cjk_count)
    return max(0, cjk_count + math.ceil(non_cjk_count / 4))


def response_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise GenerationProviderResponseError(
            "Generation provider returned no choices.",
            failure_code="generation_provider_empty_choices",
        )
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not content or not str(content).strip():
        raise GenerationProviderResponseError(
            "Generation provider returned empty content.",
            failure_code="generation_provider_empty_content",
        )
    return str(content).strip()


def strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def load_json_payload(text: str) -> dict[str, Any]:
    stripped = strip_code_fence(text)
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        payload = json.loads(stripped[start : end + 1])
        if isinstance(payload, dict):
            return payload
    raise ValueError("Planner did not return a valid JSON object.")


__all__ = [
    "estimate_tokens",
    "load_json_payload",
    "response_content",
    "response_text",
    "strip_code_fence",
]
