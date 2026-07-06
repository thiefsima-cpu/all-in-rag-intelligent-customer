"""Configuration-specific validation diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigErrorDetail:
    source_kind: str
    source: str
    path: str
    message: str

    def format(self) -> str:
        source_text = f"{self.source_kind} {self.source}".strip()
        path_text = self.path or "<root>"
        return f"{source_text}: {path_text}: {self.message}"


class ConfigurationError(ValueError):
    """Raised when profile, environment, or override configuration is invalid."""

    def __init__(self, details: Iterable[ConfigErrorDetail]) -> None:
        self.details = tuple(details)
        message = "Invalid configuration"
        if self.details:
            message = "Invalid configuration: " + "; ".join(
                detail.format() for detail in self.details
            )
        super().__init__(message)


__all__ = ["ConfigErrorDetail", "ConfigurationError"]
