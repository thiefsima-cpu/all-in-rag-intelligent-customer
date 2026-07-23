"""Domain-neutral entity evidence aggregation."""

from __future__ import annotations

from collections.abc import Sequence

from ..contracts import EvidenceDocument
from .models import AggregatedEvidence, RecipeEvidence
from .normalization import normalize_evidence_document


def aggregate_evidence(documents: Sequence[EvidenceDocument]) -> list[AggregatedEvidence]:
    grouped: dict[str, AggregatedEvidence] = {}
    order: list[str] = []

    for doc in documents or []:
        evidence = normalize_evidence_document(doc)
        key = evidence.entity_id or evidence.entity_name or evidence.doc_id
        if key not in grouped:
            grouped[key] = AggregatedEvidence(
                entity_id=evidence.entity_id,
                entity_name=evidence.entity_name,
                full_document=evidence.content,
            )
            order.append(key)

        aggregate = grouped[key]
        aggregate.documents.append(evidence)
        if len(evidence.content or "") > len(aggregate.full_document or ""):
            aggregate.full_document = evidence.content
        aggregate.confidence = max(aggregate.confidence, evidence.score)

        for term in evidence.matched_terms:
            if term and term not in aggregate.matched_terms:
                aggregate.matched_terms.append(term)
        if evidence.source and evidence.source not in aggregate.retrieval_sources:
            aggregate.retrieval_sources.append(evidence.source)

        graph_evidence = evidence.graph_evidence or {}
        if graph_evidence:
            aggregate.graph_paths.append(graph_evidence)
        domain_graph_evidence = evidence.domain_graph_evidence or {}
        if domain_graph_evidence:
            aggregate.graph_paths.append({"domain_graph_evidence": domain_graph_evidence})
        for unit in evidence.evidence_units:
            if unit not in aggregate.evidence_units:
                aggregate.evidence_units.append(unit)
            if unit.get("is_graph_evidence"):
                aggregate.graph_paths.append({"evidence_unit": unit})

        reasons = (
            evidence.constraint_evidence.get("reasons") if evidence.constraint_evidence else []
        )
        for reason in reasons if isinstance(reasons, list) else []:
            if reason and reason not in aggregate.constraint_reasons:
                aggregate.constraint_reasons.append(str(reason))

    return [grouped[key] for key in order]


def aggregate_recipe_evidence(documents: Sequence[EvidenceDocument]) -> list[RecipeEvidence]:
    """Compatibility alias for recipe-domain callers."""

    return aggregate_evidence(documents)


def aggregate_recipe_evidence_from_documents(
    documents: Sequence[EvidenceDocument],
) -> list[RecipeEvidence]:
    return aggregate_recipe_evidence(documents)


def aggregate_evidence_from_documents(
    documents: Sequence[EvidenceDocument],
) -> list[AggregatedEvidence]:
    return aggregate_evidence(documents)


__all__ = [
    "aggregate_evidence",
    "aggregate_evidence_from_documents",
    "aggregate_recipe_evidence",
    "aggregate_recipe_evidence_from_documents",
]
