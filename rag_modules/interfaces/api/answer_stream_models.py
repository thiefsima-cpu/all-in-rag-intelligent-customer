"""Server-sent event DTOs for streaming answer responses."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict

from .answer_debug_models import AnswerPayloadModel
from .answer_public_models import PublicAnswerPayloadModel
from .error_models import ErrorCode, ErrorResponseModel, build_error_model


class AnswerStreamEventType(str, Enum):
    message = "message"
    chunk = "chunk"
    result = "result"
    error = "error"
    done = "done"


class AnswerStreamMessageDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class AnswerStreamChunkDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class AnswerStreamResultDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AnswerPayloadModel | PublicAnswerPayloadModel


class AnswerStreamDoneDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class AnswerStreamEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: AnswerStreamEventType
    data: (
        AnswerStreamMessageDataModel
        | AnswerStreamChunkDataModel
        | AnswerStreamResultDataModel
        | ErrorResponseModel
        | AnswerStreamDoneDataModel
    )

    @classmethod
    def message(cls, message: str) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.message,
            data=AnswerStreamMessageDataModel(message=str(message)),
        )

    @classmethod
    def chunk(cls, content: str) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.chunk,
            data=AnswerStreamChunkDataModel(content=str(content)),
        )

    @classmethod
    def result(
        cls,
        response: AnswerPayloadModel | PublicAnswerPayloadModel,
    ) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.result,
            data=AnswerStreamResultDataModel(response=response),
        )

    @classmethod
    def error(
        cls,
        *,
        code: ErrorCode,
        request_id: str,
    ) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.error,
            data=build_error_model(code, request_id=request_id),
        )

    @classmethod
    def done(cls) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.done,
            data=AnswerStreamDoneDataModel(ok=True),
        )


__all__ = [
    "AnswerStreamChunkDataModel",
    "AnswerStreamDoneDataModel",
    "AnswerStreamEventModel",
    "AnswerStreamEventType",
    "AnswerStreamMessageDataModel",
    "AnswerStreamResultDataModel",
]
