"""Section-scoped environment override specs."""

from __future__ import annotations

from .api import API_ENV_FIELD_SPECS
from .base import EnvFieldSpec
from .generation import GENERATION_ENV_FIELD_SPECS
from .graph import GRAPH_ENV_FIELD_SPECS
from .models import MODELS_ENV_FIELD_SPECS
from .observability import OBSERVABILITY_ENV_FIELD_SPECS
from .query_understanding import QUERY_UNDERSTANDING_ENV_FIELD_SPECS
from .retrieval import RETRIEVAL_ENV_FIELD_SPECS
from .storage import STORAGE_ENV_FIELD_SPECS

ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    *API_ENV_FIELD_SPECS,
    *GENERATION_ENV_FIELD_SPECS,
    *GRAPH_ENV_FIELD_SPECS,
    *MODELS_ENV_FIELD_SPECS,
    *OBSERVABILITY_ENV_FIELD_SPECS,
    *RETRIEVAL_ENV_FIELD_SPECS,
    *STORAGE_ENV_FIELD_SPECS,
    *QUERY_UNDERSTANDING_ENV_FIELD_SPECS,
)


__all__ = [
    "API_ENV_FIELD_SPECS",
    "ENV_FIELD_SPECS",
    "GENERATION_ENV_FIELD_SPECS",
    "GRAPH_ENV_FIELD_SPECS",
    "MODELS_ENV_FIELD_SPECS",
    "OBSERVABILITY_ENV_FIELD_SPECS",
    "QUERY_UNDERSTANDING_ENV_FIELD_SPECS",
    "RETRIEVAL_ENV_FIELD_SPECS",
    "STORAGE_ENV_FIELD_SPECS",
]
