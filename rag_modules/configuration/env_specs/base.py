"""Shared environment override spec primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvValueKind = Literal["str", "int", "float", "bool", "json_dict"]


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    """Schema destination for one environment override field."""

    names: tuple[str, ...]
    path: tuple[str, ...]
    value_kind: EnvValueKind

    @property
    def dotted_path(self) -> str:
        return ".".join(self.path)


def spec(
    names: str | tuple[str, ...],
    path: tuple[str, ...],
    value_kind: EnvValueKind,
) -> EnvFieldSpec:
    normalized_names = (names,) if isinstance(names, str) else names
    return EnvFieldSpec(names=normalized_names, path=path, value_kind=value_kind)


__all__ = ["EnvFieldSpec", "EnvValueKind", "spec"]
