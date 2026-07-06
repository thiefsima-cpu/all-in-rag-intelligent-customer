"""HTTP API version constants independent of the Python package version."""

from __future__ import annotations

API_PREFIX = "/v1"
# OpenAPI/FastAPI contract version for serving and build apps, not the package version.
API_VERSION = "1.0.0"


__all__ = [
    "API_PREFIX",
    "API_VERSION",
]
