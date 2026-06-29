"""API configuration section model."""

from __future__ import annotations

from pydantic import Field

from .base import ConfigSection


class ApiSettings(ConfigSection):
    auth_enabled: bool = True
    access_token: str = Field(default="", repr=False)
    docs_enabled: bool = False
    openapi_enabled: bool = False
    docs_public: bool = False
    openapi_public: bool = False
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024)
    max_concurrent_answers: int = Field(default=4, ge=1)
    answer_acquire_timeout_seconds: float = Field(default=0.25, ge=0.0)
    stream_executor_max_workers: int = Field(default=4, ge=1)
    stream_queue_max_size: int = Field(default=64, ge=1)
    build_job_retention_limit: int = Field(default=100, ge=1)
    build_job_list_default_limit: int = Field(default=50, ge=1)
    build_job_list_max_limit: int = Field(default=100, ge=1)
    serving_hot_refresh_enabled: bool = True
    serving_hot_refresh_interval_seconds: float = Field(default=2.0, ge=0.1)


__all__ = ["ApiSettings"]
