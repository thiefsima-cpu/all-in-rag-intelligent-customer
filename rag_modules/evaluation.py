"""Deterministic retrieval, grounding, latency, and cost metrics."""

from __future__ import annotations

import math
import re
from typing import Any, Iterable, Mapping, Sequence

_CITATION_PATTERN = re.compile(
    r"(?:菜谱证据|Recipe\s+Evidence|Evidence|证据)\s*[#：:]?\s*(\d+)",
    re.IGNORECASE,
)
_CLAIM_SPLIT_PATTERN = re.compile(r"[。！？!?；;.\n]+")
_WORD_PATTERN = re.compile(r"[A-Za-z0-9_]+|[\u3400-\u9fff]")


def retrieval_metrics(
    retrieved_items: Sequence[str],
    relevant_items: Sequence[str] | Mapping[str, float],
    *,
    k: int,
) -> dict[str, float | None]:
    """Compute Recall@K, reciprocal rank, and nDCG@K for one query."""

    limit = max(0, int(k))
    ranked = []
    if limit:
        for item in retrieved_items:
            label = _normalize_label(item)
            if label and label not in ranked:
                ranked.append(label)
            if len(ranked) >= limit:
                break
    relevance = _relevance_map(relevant_items)
    if not relevance:
        return {
            "recall_at_k": None,
            "reciprocal_rank": None,
            "ndcg_at_k": None,
        }

    relevant_labels = {label for label, grade in relevance.items() if grade > 0}
    retrieved_relevant = relevant_labels.intersection(ranked)
    first_rank = next(
        (index for index, label in enumerate(ranked, start=1) if relevance.get(label, 0.0) > 0),
        None,
    )
    actual_grades = [relevance.get(label, 0.0) for label in ranked]
    ideal_grades = sorted(relevance.values(), reverse=True)[:limit]
    ideal_dcg = _discounted_cumulative_gain(ideal_grades)
    return {
        "recall_at_k": len(retrieved_relevant) / len(relevant_labels),
        "reciprocal_rank": (1.0 / first_rank) if first_rank else 0.0,
        "ndcg_at_k": (
            _discounted_cumulative_gain(actual_grades) / ideal_dcg if ideal_dcg > 0 else 0.0
        ),
    }


def grounding_metrics(
    answer: str,
    evidence_documents: Sequence[Any],
    *,
    support_threshold: float = 0.35,
) -> dict[str, float | int | None]:
    """Estimate claim support and citation correctness without model calls."""

    claims = _answer_claims(answer)
    evidence_texts = [_evidence_text(item) for item in evidence_documents]
    citations = [int(match) for match in _CITATION_PATTERN.findall(answer or "")]
    valid_citations = [citation for citation in citations if 1 <= citation <= len(evidence_texts)]

    supported_claims = 0
    cited_claims = 0
    for claim in claims:
        claim_citations = [int(match) for match in _CITATION_PATTERN.findall(claim)]
        valid_claim_citations = [
            citation for citation in claim_citations if 1 <= citation <= len(evidence_texts)
        ]
        if claim_citations:
            cited_claims += 1
        candidate_evidence = (
            [evidence_texts[index - 1] for index in valid_claim_citations]
            if valid_claim_citations
            else evidence_texts
        )
        if any(
            _support_score(claim, evidence) >= support_threshold for evidence in candidate_evidence
        ):
            supported_claims += 1

    return {
        "claim_count": len(claims),
        "supported_claim_count": supported_claims,
        "faithfulness": (supported_claims / len(claims) if claims else None),
        "citation_count": len(citations),
        "valid_citation_count": len(valid_citations),
        "citation_accuracy": (len(valid_citations) / len(citations) if citations else None),
        "citation_coverage": (cited_claims / len(claims) if claims else None),
    }


def percentile(values: Iterable[float], percentile_rank: float) -> float:
    """Return a nearest-rank percentile for non-empty numeric values."""

    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        return 0.0
    rank = min(1.0, max(0.0, float(percentile_rank)))
    index = max(0, math.ceil(rank * len(sorted_values)) - 1)
    return sorted_values[index]


def estimate_token_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    input_cost_per_million_tokens: float,
    output_cost_per_million_tokens: float,
) -> float:
    return round(
        (
            max(0, int(prompt_tokens or 0)) * max(0.0, float(input_cost_per_million_tokens or 0.0))
            + max(0, int(completion_tokens or 0))
            * max(0.0, float(output_cost_per_million_tokens or 0.0))
        )
        / 1_000_000,
        8,
    )


def _relevance_map(
    relevant_items: Sequence[str] | Mapping[str, float],
) -> dict[str, float]:
    if isinstance(relevant_items, Mapping):
        return {
            _normalize_label(label): max(0.0, float(grade or 0.0))
            for label, grade in relevant_items.items()
            if _normalize_label(label)
        }
    return {_normalize_label(label): 1.0 for label in relevant_items if _normalize_label(label)}


def _discounted_cumulative_gain(grades: Sequence[float]) -> float:
    return sum(
        (2.0 ** float(grade) - 1.0) / math.log2(index + 1)
        for index, grade in enumerate(grades, start=1)
    )


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _answer_claims(answer: str) -> list[str]:
    claims: list[str] = []
    for item in _CLAIM_SPLIT_PATTERN.split(str(answer or "")):
        claim = item.strip()
        claim_without_citation = _CITATION_PATTERN.sub("", claim).strip(" ,，:：[]()")
        if len(_tokens(claim_without_citation)) >= 2:
            claims.append(claim)
        elif _CITATION_PATTERN.search(claim) and claims:
            claims[-1] = f"{claims[-1]} {claim}"
    return claims


def _evidence_text(document: Any) -> str:
    if not isinstance(document, dict):
        to_dict = getattr(document, "to_dict", None)
        document = to_dict() if callable(to_dict) else vars(document)
    payload = dict(document or {})
    metadata = dict(payload.get("metadata") or {})
    pieces = [
        payload.get("content"),
        payload.get("page_content"),
        payload.get("recipe_name"),
        metadata.get("content"),
        metadata.get("page_content"),
        metadata.get("recipe_name"),
    ]
    for unit in payload.get("evidence_units") or metadata.get("evidence_units") or []:
        if isinstance(unit, dict):
            pieces.append(unit.get("claim"))
    graph = payload.get("graph_evidence") or metadata.get("graph_evidence") or {}
    pieces.append(str(graph))
    return " ".join(str(piece) for piece in pieces if piece)


def _support_score(claim: str, evidence: str) -> float:
    claim_tokens = _tokens(_CITATION_PATTERN.sub("", claim))
    if not claim_tokens:
        return 0.0
    evidence_tokens = _tokens(evidence)
    return len(claim_tokens.intersection(evidence_tokens)) / len(claim_tokens)


def _tokens(text: str) -> set[str]:
    normalized = str(text or "").casefold()
    tokens = set(_WORD_PATTERN.findall(normalized))
    compact_cjk = "".join(
        character for character in normalized if "\u3400" <= character <= "\u9fff"
    )
    tokens.update(compact_cjk[index : index + 2] for index in range(max(0, len(compact_cjk) - 1)))
    return {token for token in tokens if token.strip()}


__all__ = [
    "estimate_token_cost",
    "grounding_metrics",
    "percentile",
    "retrieval_metrics",
]
