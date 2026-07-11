"""Timeout policy for combined route branches."""

from __future__ import annotations

from typing import Any, cast

from ...contracts import RequestControl
from .base import RouteExecutionRequestPort

DEFAULT_BRANCH_TIMEOUT_SECONDS = 20.0
MIN_BRANCH_TIMEOUT_SECONDS = 0.001
BRANCH_TIMEOUT_METADATA_KEYS = (
    "combined_branch_timeout_seconds",
    "route_branch_timeout_seconds",
    "retrieval_branch_timeout_seconds",
    "request_budget_seconds",
)


class CombinedBranchTimeoutPolicy:
    """Resolve branch timeouts and branch-scoped request controls."""

    def __init__(
        self,
        branch_timeout_seconds: float | None = DEFAULT_BRANCH_TIMEOUT_SECONDS,
    ) -> None:
        self.default_branch_timeout_seconds = coerce_branch_timeout_seconds(
            branch_timeout_seconds,
            default=DEFAULT_BRANCH_TIMEOUT_SECONDS,
        )

    def resolve_branch_timeout_seconds(self, request: RouteExecutionRequestPort) -> float:
        metadata_timeout_seconds = metadata_branch_timeout_seconds(
            request,
            default=self.default_branch_timeout_seconds,
        )
        return (
            self.default_branch_timeout_seconds
            if metadata_timeout_seconds is None
            else metadata_timeout_seconds
        )

    @staticmethod
    def branch_control(
        route_control: RequestControl | None,
        *,
        timeout_seconds: float,
        scope: str,
    ) -> RequestControl:
        if route_control is not None:
            return route_control.isolated_child(timeout_seconds, scope=scope)
        return RequestControl.for_timeout(timeout_seconds, scope=scope)


def coerce_branch_timeout_seconds(value: object, *, default: float) -> float:
    try:
        seconds = float(cast(Any, value))
    except (TypeError, ValueError):
        seconds = float(default)
    if seconds <= 0:
        seconds = float(default)
    return max(MIN_BRANCH_TIMEOUT_SECONDS, seconds)


def metadata_branch_timeout_seconds(
    request: RouteExecutionRequestPort,
    *,
    default: float,
) -> float | None:
    retrieval_request = getattr(request, "retrieval_request", None)
    metadata = getattr(retrieval_request, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    for key in BRANCH_TIMEOUT_METADATA_KEYS:
        if key in metadata:
            return coerce_branch_timeout_seconds(metadata[key], default=default)
    return None


__all__ = [
    "BRANCH_TIMEOUT_METADATA_KEYS",
    "CombinedBranchTimeoutPolicy",
    "DEFAULT_BRANCH_TIMEOUT_SECONDS",
    "MIN_BRANCH_TIMEOUT_SECONDS",
    "coerce_branch_timeout_seconds",
    "metadata_branch_timeout_seconds",
]
