"""Helpers for turning schema/parser failures into configuration diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, NoReturn

from pydantic import ValidationError


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


def dotted_path(location: Iterable[Any]) -> str:
    return ".".join(str(part) for part in location if str(part))


def normalize_reason(message: str) -> str:
    lowered = message.lower()
    if "valid integer" in lowered or "type=integer" in lowered or "int_type" in lowered:
        return "expected integer"
    if (
        "valid number" in lowered
        or "type=number" in lowered
        or "float_type" in lowered
        or "float_parsing" in lowered
    ):
        return "expected number"
    if "valid boolean" in lowered or "type=boolean" in lowered or "bool_type" in lowered:
        return "expected boolean"
    if (
        "valid dictionary" in lowered
        or "valid dict" in lowered
        or "type=dictionary" in lowered
        or "model_type" in lowered
        or "dict_type" in lowered
    ):
        return "expected dictionary"
    if "extra inputs" in lowered or "extra fields" in lowered or "extra_forbidden" in lowered:
        return "extra field is not allowed"
    return message


def raise_validation_error(
    exc: ValidationError,
    source_kind: str,
    source: str,
) -> NoReturn:
    details = [
        ConfigErrorDetail(
            source_kind=source_kind,
            source=source,
            path=dotted_path(error.get("loc", ())),
            message=normalize_reason(str(error.get("msg", ""))),
        )
        for error in exc.errors()
    ]
    raise ConfigurationError(details) from exc


def raise_parser_error(
    source_kind: str,
    source: str,
    path: str,
    message: str,
) -> NoReturn:
    raise ConfigurationError(
        [
            ConfigErrorDetail(
                source_kind=source_kind,
                source=source,
                path=path,
                message=message,
            )
        ]
    )


__all__ = [
    "ConfigErrorDetail",
    "ConfigurationError",
    "dotted_path",
    "normalize_reason",
    "raise_parser_error",
    "raise_validation_error",
]
