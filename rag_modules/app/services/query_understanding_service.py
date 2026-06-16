"""Compatibility facade for query-understanding service imports."""

from ...query_understanding.service import (
    QueryUnderstandingResult,
    QueryUnderstandingService,
)

__all__ = ["QueryUnderstandingResult", "QueryUnderstandingService"]
