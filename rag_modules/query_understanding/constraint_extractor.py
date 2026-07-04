"""Query constraint extraction using the canonical semantic-profile inference."""

from __future__ import annotations

import logging
from typing import Any

from ..contracts.query_constraints import QueryConstraints
from .graph_intent import infer_query_semantic_profile

logger = logging.getLogger(__name__)


class QueryConstraintExtractor:
    def __init__(
        self,
        llm_client: Any,
        model_name: str,
        semantic_settings: Any | None = None,
    ):
        self.llm_client = llm_client
        self.model_name = model_name
        self.semantic_settings = semantic_settings

    def extract(self, query: str) -> QueryConstraints:
        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        constraints = QueryConstraints.from_dict(profile.constraints)
        logger.info("Query constraints parsed: present=%s", constraints.has_constraints())
        return constraints


__all__ = ["QueryConstraintExtractor"]
