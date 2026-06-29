"""FastAPI application factories for serving and build surfaces."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from ...configuration.models import ApiSettings, ObservabilitySettings
from ...telemetry import get_runtime_telemetry
from .error_handlers import register_api_error_handlers
from .error_models import error_response_openapi
from .request_context import RequestContextMiddleware
from .routes import (
    register_build_routes,
    register_serving_routes,
)
from .security import ApiSecurityMiddleware, configure_openapi_security
from .services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from .versioning import API_VERSION, configure_unversioned_api_alias_metadata


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_api_settings(*, system, config) -> ApiSettings:
    resolved_config = config or getattr(system, "config", None)
    settings = getattr(resolved_config, "api", None)
    return settings if isinstance(settings, ApiSettings) else ApiSettings()


def _resolve_observability_settings(*, system, config) -> ObservabilitySettings | None:
    resolved_config = config or getattr(system, "config", None)
    settings = getattr(resolved_config, "observability", None)
    return settings if isinstance(settings, ObservabilitySettings) else None


def _docs_url(api_settings: ApiSettings) -> str | None:
    return "/docs" if api_settings.docs_enabled and api_settings.openapi_enabled else None


def _redoc_url(api_settings: ApiSettings) -> str | None:
    return "/redoc" if api_settings.docs_enabled and api_settings.openapi_enabled else None


def _openapi_url(api_settings: ApiSettings) -> str | None:
    return "/openapi.json" if api_settings.openapi_enabled else None


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
    api_settings = _resolve_api_settings(system=api_service.system, config=config)
    observability_settings = _resolve_observability_settings(
        system=api_service.system,
        config=config,
    )
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
        version=API_VERSION,
        summary="FastAPI service for online question answering over prepared artifacts.",
        lifespan=lifespan,
        docs_url=_docs_url(api_settings),
        redoc_url=_redoc_url(api_settings),
        openapi_url=_openapi_url(api_settings),
        responses=error_response_openapi(),
    )
    app.add_middleware(
        ApiSecurityMiddleware,
        settings=api_settings,
        observability_settings=observability_settings,
    )
    app.add_middleware(RequestContextMiddleware)
    if api_settings.auth_enabled:
        configure_openapi_security(
            app,
            api_settings=api_settings,
            observability_settings=observability_settings,
        )
    register_api_error_handlers(app)
    register_serving_routes(app, api_service)
    _register_metrics_endpoint(app, system=api_service.system, config=config)
    configure_unversioned_api_alias_metadata(app)

    return app


def create_build_api_app(*, system=None, config=None) -> FastAPI:
    api_service = GraphRAGBuildApiService(system=system, config=config)
    api_settings = _resolve_api_settings(system=api_service.system, config=config)
    observability_settings = _resolve_observability_settings(
        system=api_service.system,
        config=config,
    )
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
        version=API_VERSION,
        summary="FastAPI service for offline knowledge-base artifact preparation.",
        lifespan=lifespan,
        docs_url=_docs_url(api_settings),
        redoc_url=_redoc_url(api_settings),
        openapi_url=_openapi_url(api_settings),
        responses=error_response_openapi(),
    )
    app.add_middleware(
        ApiSecurityMiddleware,
        settings=api_settings,
        observability_settings=observability_settings,
    )
    app.add_middleware(RequestContextMiddleware)
    if api_settings.auth_enabled:
        configure_openapi_security(
            app,
            api_settings=api_settings,
            observability_settings=observability_settings,
        )
    register_api_error_handlers(app)
    register_build_routes(app, api_service)
    _register_metrics_endpoint(app, system=api_service.system, config=config)
    configure_unversioned_api_alias_metadata(app)

    return app


__all__ = [
    "create_build_api_app",
    "create_serving_api_app",
]
