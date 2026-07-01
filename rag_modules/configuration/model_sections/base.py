"""Shared configuration model primitives."""

from __future__ import annotations

from typing import Any, Dict

from pydantic import BaseModel, ConfigDict


class ConfigSection(BaseModel):
    """Serializable section base."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="python")


__all__ = ["ConfigSection"]
