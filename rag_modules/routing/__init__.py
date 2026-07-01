"""Routing support services for query orchestration and tracing."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "RouteExecutionRequest": ".search_orchestrator",
    "RouteSearchOrchestrator": ".search_orchestrator",
    "RouteStatisticsTracker": ".statistics",
    "RouteTraceRecorder": ".trace_recorder",
    "RoutingWorkflowProtocol": ".contracts",
    "RoutingWorkflowService": ".workflow_service",
}

__all__ = [
    "RouteExecutionRequest",
    "RouteSearchOrchestrator",
    "RouteStatisticsTracker",
    "RouteTraceRecorder",
    "RoutingWorkflowProtocol",
    "RoutingWorkflowService",
]


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(list(globals()) + __all__)
