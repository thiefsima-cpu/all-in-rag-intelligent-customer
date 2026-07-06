"""OpenAI-compatible client construction helpers."""

from __future__ import annotations

import os

from openai import OpenAI


def resolve_api_key(explicit_key: str = "") -> str:
    resolved_api_key = (
        explicit_key
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("MOONSHOT_API_KEY")
    )
    if not resolved_api_key:
        raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
    return resolved_api_key


def build_openai_client(*, api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)


__all__ = ["build_openai_client", "resolve_api_key"]
