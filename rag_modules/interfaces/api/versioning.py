"""Shared API version constants and OpenAPI metadata helpers."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.routing import APIRoute

API_PREFIX = "/v1"
API_VERSION = "1.0.0"
UNVERSIONED_API_ALIAS_REMOVAL_VERSION = "2.0.0"

UNVERSIONED_API_ALIAS_TARGETS = {
    ("/", "get"): f"{API_PREFIX}/health",
    ("/health", "get"): f"{API_PREFIX}/health",
    ("/health/live", "get"): f"{API_PREFIX}/health/live",
    ("/health/ready", "get"): f"{API_PREFIX}/health/ready",
    ("/stats", "get"): f"{API_PREFIX}/stats",
    ("/diagnostics", "get"): f"{API_PREFIX}/diagnostics",
    ("/runtime/serving/initialize", "post"): f"{API_PREFIX}/runtime/serving/initialize",
    ("/runtime/serving/refresh", "post"): f"{API_PREFIX}/runtime/serving/refresh",
    ("/answers", "post"): f"{API_PREFIX}/answers",
    ("/answers/stream", "post"): f"{API_PREFIX}/answers/stream",
    ("/runtime/build/initialize", "post"): f"{API_PREFIX}/runtime/build/initialize",
    ("/jobs", "get"): f"{API_PREFIX}/jobs",
    ("/jobs/{job_id}", "get"): f"{API_PREFIX}/jobs/{{job_id}}",
    ("/jobs/build", "post"): f"{API_PREFIX}/jobs/build",
    ("/jobs/rebuild", "post"): f"{API_PREFIX}/jobs/rebuild",
    ("/artifacts", "get"): f"{API_PREFIX}/artifacts",
    ("/knowledge-base/build", "post"): f"{API_PREFIX}/jobs/build",
    ("/knowledge-base/rebuild", "post"): f"{API_PREFIX}/jobs/rebuild",
}


def unversioned_api_alias_description(
    canonical_path: str,
    description: str | None = None,
) -> str:
    notice = (
        "Deprecated unversioned API alias. This route will be removed in API version "
        f"{UNVERSIONED_API_ALIAS_REMOVAL_VERSION}; use `{canonical_path}` instead."
    )
    if not description:
        return notice
    if notice in description:
        return description
    return f"{description}\n\n{notice}"


def apply_unversioned_api_alias_metadata(route: APIRoute) -> None:
    for method in route.methods or ():
        canonical_path = UNVERSIONED_API_ALIAS_TARGETS.get((route.path, method.lower()))
        if canonical_path is None:
            continue
        route.deprecated = True
        route.description = unversioned_api_alias_description(
            canonical_path,
            getattr(route, "description", None),
        )
        return


def configure_unversioned_api_alias_metadata(app: FastAPI) -> None:
    for route in getattr(app, "routes", ()):
        if isinstance(route, APIRoute):
            apply_unversioned_api_alias_metadata(route)
    app.openapi_schema = None


__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "UNVERSIONED_API_ALIAS_REMOVAL_VERSION",
    "UNVERSIONED_API_ALIAS_TARGETS",
    "apply_unversioned_api_alias_metadata",
    "configure_unversioned_api_alias_metadata",
    "unversioned_api_alias_description",
]
