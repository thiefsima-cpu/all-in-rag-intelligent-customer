"""Shared helpers for environment-backed configuration section loaders."""

from __future__ import annotations

from typing import Any, Mapping


def mapping_defaults(defaults: Mapping[str, Any] | None) -> dict[str, Any]:
    return dict(defaults or {})


__all__ = ["mapping_defaults"]
