"""Query-understanding and retrieval-profile providers."""

from __future__ import annotations

from typing import Any

from ...configuration.models import GraphRAGConfig
from ...query_understanding.service import QueryUnderstandingService
from ...retrieval.runtime_profile import RetrievalRuntimeProfile, RetrievalRuntimeProfileFactory


class DefaultQueryUnderstandingComponentProvider:
    """Default query-understanding and retrieval-profile providers."""

    def __init__(
        self,
        *,
        profile_factory: RetrievalRuntimeProfileFactory | None = None,
    ) -> None:
        self.profile_factory = profile_factory or RetrievalRuntimeProfileFactory()

    def provide_retrieval_runtime_profile(
        self,
        config: GraphRAGConfig,
    ) -> RetrievalRuntimeProfile:
        return self.profile_factory.build(config)

    def provide_query_understanding_service(
        self,
        *,
        config: GraphRAGConfig,
        llm_client: Any,
        retrieval_profile: RetrievalRuntimeProfile,
    ) -> QueryUnderstandingService:
        return QueryUnderstandingService(
            llm_client=llm_client,
            config=config,
            retrieval_profile=retrieval_profile,
        )


__all__ = ["DefaultQueryUnderstandingComponentProvider"]
