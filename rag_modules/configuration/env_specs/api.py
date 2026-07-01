"""Api environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

API_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec(("API_ACCESS_TOKEN", "GRAPH_RAG_API_TOKEN"), ("api", "access_token"), "str"),
    _spec("API_AUTH_ENABLED", ("api", "auth_enabled"), "bool"),
    _spec("API_DOCS_ENABLED", ("api", "docs_enabled"), "bool"),
    _spec("API_OPENAPI_ENABLED", ("api", "openapi_enabled"), "bool"),
    _spec("API_DOCS_PUBLIC", ("api", "docs_public"), "bool"),
    _spec("API_OPENAPI_PUBLIC", ("api", "openapi_public"), "bool"),
    _spec("API_MAX_REQUEST_BODY_BYTES", ("api", "max_request_body_bytes"), "int"),
    _spec("API_MAX_CONCURRENT_ANSWERS", ("api", "max_concurrent_answers"), "int"),
    _spec(
        "API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",
        ("api", "answer_acquire_timeout_seconds"),
        "float",
    ),
    _spec("API_STREAM_EXECUTOR_MAX_WORKERS", ("api", "stream_executor_max_workers"), "int"),
    _spec("API_STREAM_QUEUE_MAX_SIZE", ("api", "stream_queue_max_size"), "int"),
    _spec("API_BUILD_JOB_RETENTION_LIMIT", ("api", "build_job_retention_limit"), "int"),
    _spec("API_BUILD_JOB_LIST_DEFAULT_LIMIT", ("api", "build_job_list_default_limit"), "int"),
    _spec("API_BUILD_JOB_LIST_MAX_LIMIT", ("api", "build_job_list_max_limit"), "int"),
    _spec("SERVING_HOT_REFRESH_ENABLED", ("api", "serving_hot_refresh_enabled"), "bool"),
    _spec(
        "SERVING_HOT_REFRESH_INTERVAL_SECONDS",
        ("api", "serving_hot_refresh_interval_seconds"),
        "float",
    ),
)


__all__ = ["API_ENV_FIELD_SPECS"]
