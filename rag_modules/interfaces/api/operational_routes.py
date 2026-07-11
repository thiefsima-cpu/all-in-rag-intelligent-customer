"""Operational route registration helpers for API surfaces."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .diagnostics_models import (
    DiagnosticsMode,
    DiagnosticsResponseModel,
    HealthResponseModel,
    OperationResponseModel,
    StatsResponseModel,
)
from .response_builder import (
    build_diagnostics_response,
    build_operation_response,
    build_stats_response,
)
from .route_handlers import build_readiness_response
from .services import GraphRAGBuildApiService, GraphRAGServingApiService
from .versioning import API_PREFIX


def register_serving_operational_routes(
    app: FastAPI,
    api_service: GraphRAGServingApiService,
) -> None:
    @app.get(f"{API_PREFIX}/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @app.get(f"{API_PREFIX}/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @app.get(
        f"{API_PREFIX}/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Serving runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        return build_readiness_response(api_service.readiness())

    @app.get(f"{API_PREFIX}/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @app.get(
        f"{API_PREFIX}/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.serve.value)
        )

    @app.post(
        f"{API_PREFIX}/runtime/serving/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_serving_runtime())

    @app.post(
        f"{API_PREFIX}/runtime/serving/refresh",
        response_model=OperationResponseModel,
    )
    def refresh_serving_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.refresh_serving_runtime())


def register_build_operational_routes(
    app: FastAPI,
    api_service: GraphRAGBuildApiService,
) -> None:
    @app.get(f"{API_PREFIX}/health", response_model=HealthResponseModel)
    def read_health() -> dict[str, Any]:
        return api_service.health()

    @app.get(f"{API_PREFIX}/health/live", response_model=HealthResponseModel)
    def read_liveness() -> dict[str, Any]:
        return api_service.health()

    @app.get(
        f"{API_PREFIX}/health/ready",
        response_model=HealthResponseModel,
        responses={503: {"description": "Build runtime is not ready."}},
    )
    def read_readiness() -> JSONResponse:
        return build_readiness_response(api_service.readiness())

    @app.get(f"{API_PREFIX}/stats", response_model=StatsResponseModel)
    def read_stats() -> StatsResponseModel:
        return build_stats_response(api_service.collect_stats())

    @app.get(
        f"{API_PREFIX}/diagnostics",
        response_model=DiagnosticsResponseModel,
    )
    def read_diagnostics() -> DiagnosticsResponseModel:
        return build_diagnostics_response(
            api_service.collect_startup_diagnostics(DiagnosticsMode.build.value)
        )

    @app.post(
        f"{API_PREFIX}/runtime/build/initialize",
        response_model=OperationResponseModel,
    )
    def initialize_build_runtime() -> OperationResponseModel:
        return build_operation_response(api_service.initialize_build_runtime())


__all__ = [
    "register_build_operational_routes",
    "register_serving_operational_routes",
]
