"""Default generation provider implementation."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ...generation.ports import GenerationWorkflowPort
from ...generation.service import GenerationWorkflowService
from ...query_policy.models import QueryPolicyBundle


class _DefaultGenerationProvider:
    """Default grounded generation workflow provider."""

    def provide_generation_module(
        self,
        config: GraphRAGConfig,
        *,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> GenerationWorkflowPort:
        return GenerationWorkflowService.from_config(config, prompt_policy=policy_bundle)


__all__ = ["_DefaultGenerationProvider"]
