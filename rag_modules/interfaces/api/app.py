"""FastAPI application factories for serving and build surfaces."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from ...configuration.models import ApiSettings
from ...telemetry import get_runtime_telemetry
from .routes import (
    register_api_backpressure_handler,
    register_build_job_handlers,
    register_build_routes,
    register_serving_routes,
    register_system_not_ready_handler,
)
from .security import ApiSecurityMiddleware, configure_openapi_security
from .services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_api_settings(*, system, config) -> ApiSettings:
    resolved_config = config or getattr(system, "config", None)
    settings = getattr(resolved_config, "api", None)
    return settings if isinstance(settings, ApiSettings) else ApiSettings()


def _register_metrics_endpoint(app: FastAPI, *, system, config) -> None:
    resolved_config = config or getattr(system, "config", None)
    observability = getattr(resolved_config, "observability", None)
    if resolved_config is None or not getattr(
        observability,
        "enable_prometheus",
        False,
    ):
        return
    telemetry = get_runtime_telemetry(resolved_config)

    @app.get("/metrics", include_in_schema=False)
    def read_metrics():
        return Response(
            content=telemetry.prometheus_payload(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )


def create_serving_api_app(*, system=None, config=None) -> FastAPI:
    api_service = GraphRAGServingApiService(system=system, config=config)
    auto_initialize_serving = _env_flag("API_AUTO_INITIALIZE_SERVING", default=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        api_service.startup(auto_initialize_serving=auto_initialize_serving)
        app.state.api_service = api_service
        try:
            yield
        finally:
            api_service.shutdown()

    app = FastAPI(
        title="GraphRAG Serving API",
        version="1.0.0",
        summary="FastAPI service for online question answering over prepared artifacts.",
        lifespan=lifespan,
    )
    api_settings = _resolve_api_settings(system=api_service.system, config=config)
    app.add_middleware(
        ApiSecurityMiddleware,
        settings=api_settings,
    )
    if api_settings.auth_enabled:
        configure_openapi_security(app)
    register_api_backpressure_handler(app)
    register_system_not_ready_handler(app)
    register_serving_routes(app, api_service)
    _register_metrics_endpoint(app, system=api_service.system, config=config)

    return app


def create_build_api_app(*, system=None, config=None) -> FastAPI:
    api_service = GraphRAGBuildApiService(system=system, config=config)
    auto_initialize_build = _env_flag("BUILD_API_AUTO_INITIALIZE", default=False)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        api_service.startup(auto_initialize_build=auto_initialize_build)
        app.state.api_service = api_service
        try:
            yield
        finally:
            api_service.shutdown()

    app = FastAPI(
        title="GraphRAG Build API",
        version="1.0.0",
        summary="FastAPI service for offline knowledge-base artifact preparation.",
        lifespan=lifespan,
    )
    api_settings = _resolve_api_settings(system=api_service.system, config=config)
    app.add_middleware(
        ApiSecurityMiddleware,
        settings=api_settings,
    )
    if api_settings.auth_enabled:
        configure_openapi_security(app)
    register_build_job_handlers(app)
    register_build_routes(app, api_service)
    _register_metrics_endpoint(app, system=api_service.system, config=config)

    return app


__all__ = [
    "create_build_api_app",
    "create_serving_api_app",
]
