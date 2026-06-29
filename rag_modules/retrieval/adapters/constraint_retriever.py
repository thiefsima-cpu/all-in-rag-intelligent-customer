"""
Constraint-focused retrieval wrapper.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from ...contracts import EvidenceDocument, RetrievalRequest, from_langchain_documents
from ..evidence import RecipeConstraintMatcher

logger = logging.getLogger(__name__)


class ConstraintRetriever:
    """Adapt RecipeConstraintMatcher to the shared retrieval contracts."""

    def __init__(self, matcher_getter: Callable[[], Optional[RecipeConstraintMatcher]]) -> None:
        self._matcher_getter = matcher_getter

    def search(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        constraints = request.effective_constraints
        matcher = self._matcher_getter()
        if not constraints or not constraints.has_constraints() or matcher is None:
            return []

        docs = matcher.filter_and_rank(
            constraints=constraints,
            min_score=0.0,
            limit=request.effective_candidate_k,
        )
        evidence_docs = []
        for evidence in from_langchain_documents(docs):
            metadata = dict(evidence.metadata or {})
            metadata["search_method"] = "constraints"
            metadata["search_type"] = "constraint_recipe"
            evidence_docs.append(
                evidence.copy_with(
                    search_method="constraints",
                    search_type="constraint_recipe",
                    metadata=metadata,
                )
            )
        logger.info("Constraint retrieval complete: %s docs", len(evidence_docs))
        return evidence_docs
