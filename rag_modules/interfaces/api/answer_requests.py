"""Request DTOs for the answer API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUESTION_CHARS = 4000


class AnswerRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    stream: bool = Field(
        default=False,
        description="Compatibility flag. Prefer POST /v1/answers/stream for SSE responses.",
        deprecated=True,
    )
    explain_routing: bool = Field(
        default=False,
        description="Include route-explanation messages in the response diagnostics or SSE events.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if "\x00" in normalized:
            raise ValueError("question must not contain NUL characters")
        return normalized


class AnswerStreamRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    explain_routing: bool = Field(
        default=False,
        description="Include route-explanation messages in the SSE event stream.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value: Any) -> Any:
        return AnswerRequestModel.normalize_question(value)


__all__ = [
    "MAX_QUESTION_CHARS",
    "AnswerRequestModel",
    "AnswerStreamRequestModel",
]
