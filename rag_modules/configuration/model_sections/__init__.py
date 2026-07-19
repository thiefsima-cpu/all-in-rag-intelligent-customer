"""Section-scoped configuration model exports."""

from __future__ import annotations

from pydantic import field_validator

from ...domains import get_domain_pack
from .api import ApiSettings
from .base import ConfigSection
from .generation import GenerationSettings
from .graph import GraphSettings
from .models import ModelSettings
from .observability import ObservabilitySettings
from .query_understanding import (
    QueryPlannerSettings,
    QueryPolicySelectorSettings,
    QuerySemanticAdaptiveTraversalSettings,
    QuerySemanticExtractionSettings,
    QuerySemanticRoutingSettings,
    QuerySemanticScoringSettings,
    QuerySemanticSettings,
    QuerySemanticTraversalSettings,
    QueryUnderstandingSettings,
)
from .retrieval import RetrievalSettings
from .storage import StorageSettings


class DomainSettings(ConfigSection):
    """Select the versioned business-domain behavior pack."""

    name: str = "recipe"

    @field_validator("name")
    @classmethod
    def validate_domain_pack_name(cls, value: str) -> str:
        return get_domain_pack(value).name


__all__ = [
    "ApiSettings",
    "ConfigSection",
    "DomainSettings",
    "GenerationSettings",
    "GraphSettings",
    "ModelSettings",
    "ObservabilitySettings",
    "QueryPolicySelectorSettings",
    "QueryPlannerSettings",
    "QuerySemanticAdaptiveTraversalSettings",
    "QuerySemanticExtractionSettings",
    "QuerySemanticRoutingSettings",
    "QuerySemanticScoringSettings",
    "QuerySemanticSettings",
    "QuerySemanticTraversalSettings",
    "QueryUnderstandingSettings",
    "RetrievalSettings",
    "StorageSettings",
]
