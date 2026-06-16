"""FastAPI application factories for serving and build surfaces."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .service import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from .routes import (
    register_build_routes,
    register_build_job_handlers,
    register_serving_routes,
    register_system_not_ready_handler,
)


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    register_system_not_ready_handler(app)
    register_serving_routes(app, api_service)

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
    register_build_job_handlers(app)
    register_build_routes(app, api_service)

    return app


__all__ = [
    "create_build_api_app",
    "create_serving_api_app",
]
