"""Recipe-level evidence aggregation."""

from __future__ import annotations

from typing import Dict, List

from ..contracts import EvidenceDocument, ensure_evidence_documents
from .models import PageDocumentLike, RecipeEvidence
from .normalization import normalize_evidence_document


def aggregate_recipe_evidence(documents: List[EvidenceDocument]) -> List[RecipeEvidence]:
    grouped: Dict[str, RecipeEvidence] = {}
    order: List[str] = []

    for doc in documents or []:
        evidence = normalize_evidence_document(doc)
        key = evidence.recipe_id or evidence.recipe_name or evidence.doc_id
        if key not in grouped:
            grouped[key] = RecipeEvidence(
                recipe_id=evidence.recipe_id,
                recipe_name=evidence.recipe_name,
                full_recipe_doc=evidence.content,
            )
            order.append(key)

        recipe = grouped[key]
        recipe.documents.append(evidence)
        if len(evidence.content or "") > len(recipe.full_recipe_doc or ""):
            recipe.full_recipe_doc = evidence.content
        recipe.confidence = max(recipe.confidence, evidence.score)

        for term in evidence.matched_terms:
            if term and term not in recipe.matched_terms:
                recipe.matched_terms.append(term)
        if evidence.source and evidence.source not in recipe.retrieval_sources:
            recipe.retrieval_sources.append(evidence.source)

        graph_evidence = evidence.graph_evidence or {}
        if graph_evidence:
            recipe.graph_paths.append(graph_evidence)
        recipe_graph_evidence = evidence.recipe_graph_evidence or {}
        if recipe_graph_evidence:
            recipe.graph_paths.append({"recipe_graph_evidence": recipe_graph_evidence})
        for unit in evidence.evidence_units:
            if unit not in recipe.evidence_units:
                recipe.evidence_units.append(unit)
            if unit.get("is_graph_evidence"):
                recipe.graph_paths.append({"evidence_unit": unit})

        reasons = (
            evidence.constraint_evidence.get("reasons") if evidence.constraint_evidence else []
        )
        for reason in reasons or []:
            if reason and reason not in recipe.constraint_reasons:
                recipe.constraint_reasons.append(reason)

    return [grouped[key] for key in order]


def aggregate_recipe_evidence_from_documents(
    documents: List[PageDocumentLike | EvidenceDocument],
) -> List[RecipeEvidence]:
    return aggregate_recipe_evidence(ensure_evidence_documents(documents))


__all__ = [
    "aggregate_recipe_evidence",
    "aggregate_recipe_evidence_from_documents",
]
