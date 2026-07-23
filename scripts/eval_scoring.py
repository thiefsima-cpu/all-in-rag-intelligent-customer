"""Scoring and aggregate metrics for curated quality evaluation runs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, List

from rag_modules.contracts import EvidenceDocument
from rag_modules.evaluation import grounding_metrics, percentile, retrieval_metrics
from rag_modules.observability.retrieval_snapshots import summarize_documents
from scripts.eval_cases import EvalCase, EvalResponseMode


@dataclass(frozen=True)
class EvalObservation:
    strategy: str | None
    answer: str
    documents: tuple[EvidenceDocument | dict[str, Any], ...]
    latency_ms: float
    plan: dict[str, Any]
    contracts: dict[str, Any]
    resilience: dict[str, Any]
    cost: dict[str, Any]


def _document_metadata(doc: EvidenceDocument | dict[str, Any]) -> dict[str, Any]:
    if isinstance(doc, dict):
        return dict(doc.get("metadata") or {})
    return dict(doc.metadata or {})


def _document_recipe_name(doc: EvidenceDocument | dict[str, Any]) -> str:
    if isinstance(doc, dict):
        return str(doc.get("recipe_name") or _document_metadata(doc).get("recipe_name") or "")
    return str(doc.entity_name or _document_metadata(doc).get("recipe_name") or "")


def _document_evidence_units(doc: EvidenceDocument | dict[str, Any]) -> List[dict]:
    if isinstance(doc, dict):
        units = doc.get("evidence_units") or _document_metadata(doc).get("evidence_units") or []
        return [dict(unit) for unit in units if isinstance(unit, dict)]
    return [dict(unit) for unit in (doc.evidence_units or []) if isinstance(unit, dict)]


def _document_graph_evidence(doc: EvidenceDocument | dict[str, Any]) -> dict[str, Any]:
    if isinstance(doc, dict):
        payload = doc.get("graph_evidence") or _document_metadata(doc).get("graph_evidence") or {}
        return dict(payload)
    return dict(doc.graph_evidence or {})


def _doc_recipe_names(docs: List[EvidenceDocument | dict[str, Any]]) -> List[str]:
    names = []
    for doc in docs:
        name = _document_recipe_name(doc)
        if name and name not in names:
            names.append(name)
    return names


def _ranked_doc_recipe_names(
    docs: List[EvidenceDocument | dict[str, Any]],
) -> List[str]:
    return [name for name in (_document_recipe_name(doc) for doc in docs) if name]


def _doc_evidence_summary(docs: List[EvidenceDocument | dict[str, Any]]) -> List[dict]:
    if docs and isinstance(docs[0], dict):
        summaries = []
        for doc in docs[:10]:
            units = _document_evidence_units(doc)
            graph_evidence = _document_graph_evidence(doc)
            metadata = _document_metadata(doc)
            summaries.append(
                {
                    "doc_id": str(doc.get("doc_id") or ""),
                    "recipe_id": str(doc.get("recipe_id") or doc.get("node_id") or ""),
                    "recipe_name": _document_recipe_name(doc),
                    "source": str(
                        doc.get("source")
                        or doc.get("search_method")
                        or doc.get("search_type")
                        or metadata.get("source")
                        or ""
                    ),
                    "score": doc.get("score", metadata.get("score", 0.0)),
                    "evidence_type": str(
                        doc.get("evidence_type") or metadata.get("evidence_type") or ""
                    ),
                    "matched_terms": list(
                        doc.get("matched_terms") or metadata.get("matched_terms") or []
                    ),
                    "has_graph_evidence": bool(graph_evidence),
                    "graph_relationships": len(graph_evidence.get("relationships") or []),
                    "constraint_evidence": dict(
                        doc.get("constraint_evidence") or metadata.get("constraint_evidence") or {}
                    ),
                    "evidence_unit_count": len(units),
                    "graph_evidence_unit_count": sum(
                        1 for unit in units if unit.get("is_graph_evidence")
                    ),
                }
            )
        return summaries

    summaries = summarize_documents(docs, limit=10)
    for summary, doc in zip(summaries, docs[:10]):
        units = _document_evidence_units(doc)
        summary["evidence_unit_count"] = len(units)
        summary["graph_evidence_unit_count"] = sum(
            1 for unit in units if unit.get("is_graph_evidence")
        )
    return summaries


def _answer_has_citation_marker(answer: str) -> bool:
    return any(marker in answer for marker in ("菜谱证据", "依据"))


def _expected_recipe_names(case: EvalCase) -> list[str]:
    names = list(case.expectation.recipe_names)
    for name, grade in case.expectation.recipe_relevance.items():
        if grade > 0 and name not in names:
            names.append(name)
    return names


def _ranking_not_applicable() -> dict[str, None]:
    return {
        "recall_at_k": None,
        "reciprocal_rank": None,
        "ndcg_at_k": None,
    }


def _grounding_not_applicable() -> dict[str, int | None]:
    return {
        "claim_count": 0,
        "supported_claim_count": 0,
        "faithfulness": None,
        "citation_count": 0,
        "valid_citation_count": 0,
        "citation_accuracy": None,
        "citation_coverage": None,
    }


def _default_eval_cost(cost: dict[str, Any]) -> dict[str, Any]:
    return {
        "prompt_tokens": int(cost.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(cost.get("completion_tokens", 0) or 0),
        "total_tokens": int(cost.get("total_tokens", 0) or 0),
        "estimated_cost_usd": float(cost.get("estimated_cost_usd", 0.0) or 0.0),
        "token_usage_source": str(cost.get("token_usage_source", "") or ""),
    }


def _default_eval_resilience(resilience: dict[str, Any]) -> dict[str, Any]:
    return {
        "fallback_used": bool(resilience.get("fallback_used")),
        "fallback_reasons": list(resilience.get("fallback_reasons") or []),
        "retrieval_degraded": bool(resilience.get("retrieval_degraded")),
        "degraded_sources": list(resilience.get("degraded_sources") or []),
        "degraded_candidates": list(resilience.get("degraded_candidates") or []),
    }


def _actual_response_mode(
    expected_response_mode: EvalResponseMode,
    *,
    documents: tuple[EvidenceDocument | dict[str, Any], ...],
    recipe_names: list[str],
    answer: str,
) -> EvalResponseMode:
    if documents or recipe_names or _answer_has_citation_marker(answer):
        return EvalResponseMode.GROUNDED_ANSWER
    if expected_response_mode.is_abstention:
        return expected_response_mode
    return EvalResponseMode.NO_EVIDENCE


def score_eval_observation(
    case: EvalCase,
    observation: EvalObservation,
    *,
    top_k: int,
    generate: bool,
) -> dict[str, Any]:
    documents = tuple(observation.documents or ())
    answer = str(observation.answer or "")
    expected = case.expectation
    expected_recipe_names = _expected_recipe_names(case)
    recipe_names = _doc_recipe_names(list(documents))
    ranked_recipe_names = _ranked_doc_recipe_names(list(documents))
    missing_names = [
        expected_name
        for expected_name in expected_recipe_names
        if expected_name not in recipe_names
    ]
    answer_missing_terms = (
        [term for term in expected.answer_terms if term not in answer] if generate else []
    )
    strategy_failed = expected.strategy is not None and observation.strategy != expected.strategy
    answer_failed = bool(generate and expected.answer_terms and answer_missing_terms)
    actual_response_mode = _actual_response_mode(
        expected.response_mode,
        documents=documents,
        recipe_names=recipe_names,
        answer=answer,
    )

    failures: list[str] = []
    if strategy_failed:
        failures.append(
            f"expected_strategy={expected.strategy} actual_strategy={observation.strategy}"
        )
    if missing_names:
        failures.append(f"missing_recipe_names={missing_names}")
    if answer_failed:
        failures.append(f"missing_answer_terms={answer_missing_terms}")

    response_mode_failures: list[str] = []
    if expected.response_mode is EvalResponseMode.GROUNDED_ANSWER:
        if not documents:
            response_mode_failures.append("missing_evidence")
    else:
        if documents:
            response_mode_failures.append("unexpected_evidence")
        if recipe_names:
            response_mode_failures.append(f"unexpected_recipe_names={recipe_names}")
        if _answer_has_citation_marker(answer):
            response_mode_failures.append("unexpected_citation")
    failures.extend(response_mode_failures)

    response_mode_passed = (
        actual_response_mode is expected.response_mode
        and not response_mode_failures
        and not missing_names
        and not answer_failed
    )
    if not response_mode_passed:
        failures.append("response_mode_mismatch")

    if expected.response_mode is EvalResponseMode.GROUNDED_ANSWER:
        relevance = expected.recipe_relevance or {name: 1.0 for name in expected_recipe_names}
        ranking = retrieval_metrics(ranked_recipe_names, relevance, k=top_k)
        grounding = (
            grounding_metrics(answer, documents) if generate else _grounding_not_applicable()
        )
    else:
        ranking = _ranking_not_applicable()
        grounding = _grounding_not_applicable()

    plan = dict(observation.plan or {})
    contracts = dict(observation.contracts or {})
    contracts.setdefault("answer_response", {})
    contracts.setdefault("route_resolution", {})

    return {
        "id": case.case_id,
        "query": case.query,
        "category": case.category,
        "dimensions": list(case.dimensions),
        "passed": not failures,
        "failures": failures,
        "evaluation": {
            "strategy": observation.strategy,
            "expected_strategy": expected.strategy,
            "expected_recipe_names": expected_recipe_names,
            "expected_recipe_relevance": dict(expected.recipe_relevance),
            "expected_answer_terms": list(expected.answer_terms),
            "expected_response_mode": expected.response_mode.value,
            "actual_response_mode": actual_response_mode.value,
            "response_mode_passed": response_mode_passed,
            "answer_checked": bool(generate),
            "answer_passed": (not answer_failed) if generate else None,
            "answer_missing_terms": answer_missing_terms,
            "answer_preview": answer[:300] if answer else "",
        },
        "retrieval": {
            "recipe_names": recipe_names,
            "ranked_recipe_names": ranked_recipe_names,
            "missing_recipe_names": missing_names,
            "doc_count": len(documents),
            "evidence": _doc_evidence_summary(list(documents)),
            **ranking,
        },
        "grounding": grounding,
        "cost": _default_eval_cost(dict(observation.cost or {})),
        "resilience": _default_eval_resilience(dict(observation.resilience or {})),
        "runtime": {
            "latency_ms": float(observation.latency_ms or 0.0),
            "plan_used_cache": plan.get("used_cache"),
            "plan_validation_errors": plan.get("validation_errors"),
        },
        "contracts": contracts,
    }


def calculate_eval_metrics(results: List[dict]) -> dict:
    total = len(results)
    if total == 0:
        return {}
    passed = sum(1 for item in results if item["passed"])
    response_mode_cases = [
        item for item in results if item.get("evaluation", {}).get("expected_response_mode")
    ]
    abstention_cases = [
        item
        for item in response_mode_cases
        if item.get("evaluation", {}).get("expected_response_mode")
        != EvalResponseMode.GROUNDED_ANSWER.value
    ]
    grounded_response_mode_cases = [
        item
        for item in response_mode_cases
        if item.get("evaluation", {}).get("expected_response_mode")
        == EvalResponseMode.GROUNDED_ANSWER.value
    ]
    response_mode_counts = Counter(
        item["evaluation"]["expected_response_mode"] for item in response_mode_cases
    )
    dimension_counts = Counter(
        dimension for item in results for dimension in item.get("dimensions", [])
    )
    strategy_cases = [
        item for item in results if item.get("evaluation", {}).get("expected_strategy")
    ]
    strategy_passed = sum(
        1
        for item in strategy_cases
        if item.get("evaluation", {}).get("strategy")
        == item.get("evaluation", {}).get("expected_strategy")
    )
    recipe_cases = [
        item for item in results if item.get("evaluation", {}).get("expected_recipe_names")
    ]
    recipe_passed = sum(
        1 for item in recipe_cases if not item.get("retrieval", {}).get("missing_recipe_names")
    )
    graph_covered = sum(
        1
        for item in results
        if any(
            evidence.get("has_graph_evidence")
            for evidence in item.get("retrieval", {}).get("evidence", [])
        )
    )
    graph_unit_covered = sum(
        1
        for item in results
        if any(
            evidence.get("graph_evidence_unit_count", 0) > 0
            for evidence in item.get("retrieval", {}).get("evidence", [])
        )
    )
    scores = [
        evidence.get("score") or 0.0
        for item in results
        for evidence in item.get("retrieval", {}).get("evidence", [])
    ]
    latencies = [item.get("runtime", {}).get("latency_ms", 0.0) for item in results]
    recall_values = [
        item.get("retrieval", {}).get("recall_at_k")
        for item in grounded_response_mode_cases
        if item.get("retrieval", {}).get("recall_at_k") is not None
    ]
    reciprocal_ranks = [
        item.get("retrieval", {}).get("reciprocal_rank")
        for item in grounded_response_mode_cases
        if item.get("retrieval", {}).get("reciprocal_rank") is not None
    ]
    ndcg_values = [
        item.get("retrieval", {}).get("ndcg_at_k")
        for item in grounded_response_mode_cases
        if item.get("retrieval", {}).get("ndcg_at_k") is not None
    ]
    faithfulness_values = [
        item.get("grounding", {}).get("faithfulness")
        for item in grounded_response_mode_cases
        if item.get("grounding", {}).get("faithfulness") is not None
    ]
    citation_accuracy_values = [
        item.get("grounding", {}).get("citation_accuracy")
        for item in grounded_response_mode_cases
        if item.get("grounding", {}).get("citation_accuracy") is not None
    ]
    total_prompt_tokens = sum(
        int(item.get("cost", {}).get("prompt_tokens", 0) or 0) for item in results
    )
    total_completion_tokens = sum(
        int(item.get("cost", {}).get("completion_tokens", 0) or 0) for item in results
    )
    total_tokens = sum(int(item.get("cost", {}).get("total_tokens", 0) or 0) for item in results)
    total_estimated_cost_usd = sum(
        float(item.get("cost", {}).get("estimated_cost_usd", 0.0) or 0.0) for item in results
    )
    answer_cases = [item for item in results if item.get("evaluation", {}).get("answer_checked")]
    answer_passed = sum(
        1 for item in answer_cases if item.get("evaluation", {}).get("answer_passed")
    )
    citation_cases = [
        item
        for item in results
        if item.get("evaluation", {}).get("answer_checked")
        and item.get("evaluation", {}).get("answer_preview")
    ]
    citation_passed = sum(
        1
        for item in citation_cases
        if _answer_has_citation_marker(item.get("evaluation", {}).get("answer_preview", ""))
    )
    fallback_cases = [item for item in results if item.get("resilience", {}).get("fallback_used")]
    fallback_reasons: dict[str, int] = {}
    for item in results:
        for reason in item.get("resilience", {}).get("fallback_reasons", []) or []:
            text = str(reason or "").strip()
            if text:
                fallback_reasons[text] = fallback_reasons.get(text, 0) + 1
    degraded_cases = [
        item for item in results if item.get("resilience", {}).get("retrieval_degraded")
    ]
    degraded_source_counts: dict[str, int] = {}
    for item in results:
        for source in item.get("resilience", {}).get("degraded_sources", []) or []:
            text = str(source or "").strip()
            if text:
                degraded_source_counts[text] = degraded_source_counts.get(text, 0) + 1
    grouped = {}
    for item in results:
        grouped.setdefault(item.get("category", "general"), []).append(item)
    category_metrics = {}
    for category, items in grouped.items():
        category_metrics[category] = {
            "case_count": len(items),
            "pass_rate": sum(1 for item in items if item["passed"]) / len(items),
            "avg_latency_ms": (
                sum(item.get("runtime", {}).get("latency_ms", 0.0) for item in items) / len(items)
            ),
            "graph_evidence_coverage": sum(
                1
                for item in items
                if any(
                    evidence.get("has_graph_evidence")
                    for evidence in item.get("retrieval", {}).get("evidence", [])
                )
            )
            / len(items),
            "graph_evidence_unit_coverage": sum(
                1
                for item in items
                if any(
                    evidence.get("graph_evidence_unit_count", 0) > 0
                    for evidence in item.get("retrieval", {}).get("evidence", [])
                )
            )
            / len(items),
        }

    return {
        "case_count": total,
        "pass_rate": passed / total,
        "response_mode_accuracy": (
            sum(
                bool(item.get("evaluation", {}).get("response_mode_passed"))
                for item in response_mode_cases
            )
            / len(response_mode_cases)
            if response_mode_cases
            else None
        ),
        "abstention_accuracy": (
            sum(
                bool(item.get("evaluation", {}).get("response_mode_passed"))
                for item in abstention_cases
            )
            / len(abstention_cases)
            if abstention_cases
            else None
        ),
        "response_mode_counts": dict(sorted(response_mode_counts.items())),
        "dimension_counts": dict(sorted(dimension_counts.items())),
        "strategy_accuracy": strategy_passed / len(strategy_cases) if strategy_cases else None,
        "recipe_hit_rate": recipe_passed / len(recipe_cases) if recipe_cases else None,
        "graph_evidence_coverage": graph_covered / total,
        "graph_evidence_unit_coverage": graph_unit_covered / total,
        "avg_evidence_score": sum(scores) / len(scores) if scores else 0.0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "recall_at_k": (sum(recall_values) / len(recall_values) if recall_values else None),
        "mrr": (sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else None),
        "ndcg_at_k": (sum(ndcg_values) / len(ndcg_values) if ndcg_values else None),
        "faithfulness": (
            sum(faithfulness_values) / len(faithfulness_values) if faithfulness_values else None
        ),
        "citation_accuracy": (
            sum(citation_accuracy_values) / len(citation_accuracy_values)
            if citation_accuracy_values
            else None
        ),
        "prompt_tokens": total_prompt_tokens,
        "completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(total_estimated_cost_usd, 8),
        "avg_tokens_per_case": total_tokens / total if total else 0.0,
        "avg_cost_usd_per_case": (total_estimated_cost_usd / total if total else 0.0),
        "answer_pass_rate": answer_passed / len(answer_cases) if answer_cases else None,
        "answer_citation_rate": citation_passed / len(citation_cases) if citation_cases else None,
        "fallback_case_count": len(fallback_cases),
        "fallback_rate": len(fallback_cases) / total,
        "fallback_reasons": dict(sorted(fallback_reasons.items())),
        "retrieval_degraded_case_count": len(degraded_cases),
        "retrieval_degradation_rate": len(degraded_cases) / total,
        "degraded_sources": sorted(degraded_source_counts),
        "degraded_source_counts": dict(sorted(degraded_source_counts.items())),
        "by_category": category_metrics,
    }


def build_offline_eval_observation(
    case: EvalCase,
    *,
    index: int,
    generate: bool,
) -> EvalObservation:
    documents = tuple(
        EvidenceDocument(
            content=fixture.content,
            entity_name=fixture.recipe_name,
            node_id=f"offline-quality-{case.case_id}-{rank}",
            doc_id=f"offline-quality-{case.case_id}-{rank}",
            score=fixture.score,
            source="offline_quality",
            evidence_type=fixture.evidence_type,
            matched_terms=list(case.expectation.answer_terms),
            graph_evidence=(
                {"relationships": [{"type": "OFFLINE_SUPPORTS", "target": fixture.recipe_name}]}
                if fixture.evidence_type == "graph"
                else {}
            ),
            evidence_units=[
                {
                    "claim": fixture.content,
                    "is_graph_evidence": fixture.evidence_type == "graph",
                }
            ],
            route_strategy=case.offline_fixture.strategy,
        )
        for rank, fixture in enumerate(case.offline_fixture.evidence, start=1)
    )
    latency_ms = 10.0 + float(index)
    plan = {
        "query": case.query,
        "strategy": case.offline_fixture.strategy,
        "used_cache": False,
        "validation_errors": [],
    }
    answer = case.offline_fixture.answer if generate else ""
    response_payload = {
        "summary": {
            "answer": answer,
            "strategy": case.offline_fixture.strategy,
            "latency_ms": latency_ms,
            "doc_count": len(documents),
            "has_evidence": bool(documents),
            "fallback_used": False,
            "error": "",
            "estimated_cost_usd": 0.0,
        },
        "grounding": {
            "retrieval_outcome": {
                "query": case.query,
                "strategy": case.offline_fixture.strategy,
                "doc_count": len(documents),
                "evidence_documents": [document.to_dict() for document in documents],
                "degradation_summary": {
                    "retrieval_degraded": False,
                    "degraded_sources": [],
                    "degraded_candidates": [],
                },
            },
            "route_resolution": {},
            "evidence_documents": [document.to_dict() for document in documents],
        },
        "diagnostics": {
            "analysis": {
                "recommended_strategy": case.offline_fixture.strategy,
            },
            "diagnostics": {
                "retrieval_degraded": False,
                "degraded_sources": [],
                "degraded_candidates": [],
            },
        },
        "traces": {
            "route_trace": {
                "strategy": case.offline_fixture.strategy,
                "fallbacks": [],
                "diagnostics": {
                    "used_fallback": False,
                    "retrieval_degraded": False,
                    "degraded_sources": [],
                    "degraded_candidates": [],
                },
            },
            "graph_trace": {},
            "generation_trace": {
                "mode": "offline_quality",
                "fallback_used": False,
                "estimated_cost_usd": 0.0,
                "token_usage_source": "offline_quality",
            },
            "trace_event": {"strategy": case.offline_fixture.strategy},
        },
    }
    return EvalObservation(
        strategy=case.offline_fixture.strategy,
        answer=answer,
        documents=documents,
        latency_ms=latency_ms,
        plan=plan,
        contracts={
            "answer_response": response_payload if generate else {},
            "route_resolution": {},
        },
        resilience={
            "fallback_used": False,
            "fallback_reasons": [],
            "retrieval_degraded": False,
            "degraded_sources": [],
            "degraded_candidates": [],
        },
        cost={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "token_usage_source": "offline_quality",
        },
    )


def evaluate_offline_quality_case(
    case: EvalCase,
    *,
    index: int,
    top_k: int,
    generate: bool,
) -> dict[str, Any]:
    observation = build_offline_eval_observation(case, index=index, generate=generate)
    return score_eval_observation(case, observation, top_k=top_k, generate=generate)


__all__ = [
    "EvalObservation",
    "build_offline_eval_observation",
    "calculate_eval_metrics",
    "evaluate_offline_quality_case",
    "score_eval_observation",
]
