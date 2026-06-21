"""Generation providers."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...generation.service import GenerationWorkflowService


class DefaultGenerationComponentProvider:
    """Default generation providers."""

    def provide_generation_module(self, config: GraphRAGConfig) -> GenerationWorkflowService:
        return GenerationWorkflowService.from_config(config)
