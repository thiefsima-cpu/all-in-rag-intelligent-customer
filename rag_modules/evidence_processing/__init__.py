"""Canonical evidence normalization and aggregation package."""

from .aggregation import (
    aggregate_recipe_evidence,
    aggregate_recipe_evidence_from_documents,
)
from .extraction import extract_evidence_units
from .helpers import infer_evidence_type
from .models import EvidenceUnit, PageDocumentLike, RecipeEvidence
from .normalization import (
    evidence_from_document,
    normalize_document_evidence,
    normalize_evidence_document,
)
from .ranking import EvidenceUnitRanker

__all__ = [
    "EvidenceUnit",
    "EvidenceUnitRanker",
    "PageDocumentLike",
    "RecipeEvidence",
    "aggregate_recipe_evidence",
    "aggregate_recipe_evidence_from_documents",
    "evidence_from_document",
    "extract_evidence_units",
    "infer_evidence_type",
    "normalize_document_evidence",
    "normalize_evidence_document",
]
