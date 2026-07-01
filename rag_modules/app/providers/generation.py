"""Default generation provider implementation."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService


class _DefaultGenerationProvider:
    """Default grounded generation workflow provider."""

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService:
        return GenerationWorkflowService.from_config(config)


__all__ = ["_DefaultGenerationProvider"]
