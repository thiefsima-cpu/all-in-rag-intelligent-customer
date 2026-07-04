"""Build/runtime-neutral text document contract."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict


@dataclass
class TextDocument:
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.content = str(self.content or "")
        self.metadata = dict(self.metadata or {})

    @property
    def page_content(self) -> str:
        return self.content

    def copy_with(self, **changes: Any) -> "TextDocument":
        return replace(self, **changes)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "TextDocument":
        data = dict(payload or {})
        content = data.get("content")
        if content is None:
            content = data.get("page_content")
        return cls(
            content=str(content or ""),
            metadata=dict(data.get("metadata") or {}),
        )
