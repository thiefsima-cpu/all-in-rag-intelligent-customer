"""Build/runtime-neutral text document contract."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .json_types import JsonObject, coerce_json_object, coerce_str


@dataclass
class TextDocument:
    content: str
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.content = coerce_str(self.content)
        self.metadata = coerce_json_object(self.metadata)

    @property
    def page_content(self) -> str:
        return self.content

    def to_dict(self) -> JsonObject:
        return {
            "content": self.content,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object] | None) -> "TextDocument":
        data = payload or {}
        content = data.get("content")
        if content is None:
            content = data.get("page_content")
        return cls(
            content=coerce_str(content),
            metadata=coerce_json_object(data.get("metadata")),
        )
