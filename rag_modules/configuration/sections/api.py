"""API configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ApiSettings
from .common import mapping_defaults


def load_api_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ApiSettings:
    api_defaults = mapping_defaults(defaults)
    access_token = source.get_first("API_ACCESS_TOKEN", "GRAPH_RAG_API_TOKEN") or str(
        api_defaults.get("access_token", "")
    )
    return ApiSettings(
        auth_enabled=source.get_bool(
            "API_AUTH_ENABLED",
            bool(api_defaults.get("auth_enabled", True)),
        ),
        access_token=access_token,
        docs_enabled=source.get_bool(
            "API_DOCS_ENABLED",
            bool(api_defaults.get("docs_enabled", False)),
        ),
        openapi_enabled=source.get_bool(
            "API_OPENAPI_ENABLED",
            bool(api_defaults.get("openapi_enabled", False)),
        ),
        docs_public=source.get_bool(
            "API_DOCS_PUBLIC",
            bool(api_defaults.get("docs_public", False)),
        ),
        openapi_public=source.get_bool(
            "API_OPENAPI_PUBLIC",
            bool(api_defaults.get("openapi_public", False)),
        ),
        max_request_body_bytes=max(
            1024,
            source.get_int(
                "API_MAX_REQUEST_BODY_BYTES",
                int(api_defaults.get("max_request_body_bytes", 16 * 1024)),
            ),
        ),
        max_concurrent_answers=max(
            0,
            source.get_int(
                "API_MAX_CONCURRENT_ANSWERS",
                int(api_defaults.get("max_concurrent_answers", 0)),
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            source.get_float(
                "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",
                float(api_defaults.get("answer_acquire_timeout_seconds", 0.25)),
            ),
        ),
        stream_executor_max_workers=max(
            1,
            source.get_int(
                "API_STREAM_EXECUTOR_MAX_WORKERS",
                int(api_defaults.get("stream_executor_max_workers", 4)),
            ),
        ),
        stream_queue_max_size=max(
            1,
            source.get_int(
                "API_STREAM_QUEUE_MAX_SIZE",
                int(api_defaults.get("stream_queue_max_size", 64)),
            ),
        ),
        serving_hot_refresh_enabled=source.get_bool(
            "SERVING_HOT_REFRESH_ENABLED",
            bool(api_defaults.get("serving_hot_refresh_enabled", True)),
        ),
        serving_hot_refresh_interval_seconds=max(
            0.1,
            source.get_float(
                "SERVING_HOT_REFRESH_INTERVAL_SECONDS",
                float(api_defaults.get("serving_hot_refresh_interval_seconds", 2.0)),
            ),
        ),
    )


__all__ = ["load_api_settings"]
