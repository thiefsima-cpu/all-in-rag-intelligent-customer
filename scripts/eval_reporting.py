"""Runtime evaluation, offline quality reports, and report serialization."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

from rag_modules.app.system import AdvancedGraphRAGSystem
from rag_modules.configuration import GraphRAGConfig, load_config
from rag_modules.query_policy import get_query_policy
from scripts.eval_cases import DEFAULT_CORPUS_PATH, EvalCase, load_eval_cases
from scripts.eval_scoring import (
    EvalObservation,
    calculate_eval_metrics,
    evaluate_offline_quality_case,
    score_eval_observation,
)


def _response_query_plan(response) -> dict[str, Any]:
    route_resolution = response.route_resolution if hasattr(response, "route_resolution") else {}
    if not isinstance(route_resolution, dict):
        return {}
    understanding = route_resolution.get("understanding") or {}
    if not isinstance(understanding, dict):
        return {}
    query_plan = understanding.get("query_plan") or {}
    return dict(query_plan) if isinstance(query_plan, dict) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _add_unique(target: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text and text not in target:
        target.append(text)


def _extend_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        _add_unique(target, value)


def _extend_unique_dicts(target: list[dict[str, Any]], values: list[dict[str, Any]]) -> None:
    for value in values:
        if value and value not in target:
            target.append(dict(value))


def _answer_resilience_signals(
    response_payload: dict[str, Any],
    route_resolution_payload: dict[str, Any],
) -> dict[str, Any]:
    summary = _mapping(response_payload.get("summary"))
    traces = _mapping(response_payload.get("traces"))
    generation_trace = _mapping(traces.get("generation_trace"))
    route_trace = _mapping(traces.get("route_trace"))
    grounding = _mapping(response_payload.get("grounding"))
    retrieval_outcome = _mapping(grounding.get("retrieval_outcome"))
    degradation_summary = _mapping(retrieval_outcome.get("degradation_summary"))

    if not route_trace:
        route_trace = _mapping(retrieval_outcome.get("route_trace"))
    if not route_trace and route_resolution_payload:
        route_retrieval = _mapping(route_resolution_payload.get("retrieval"))
        route_trace = _mapping(route_retrieval.get("route_trace"))
        if not degradation_summary:
            degradation_summary = _mapping(route_retrieval.get("degradation_summary"))

    response_diagnostics = _mapping(
        _mapping(response_payload.get("diagnostics")).get("diagnostics")
    )
    route_diagnostics = _mapping(route_trace.get("diagnostics"))

    fallback_reasons: list[str] = []
    generation_fallback = bool(summary.get("fallback_used")) or bool(
        generation_trace.get("fallback_used")
    )
    if generation_fallback:
        _add_unique(
            fallback_reasons,
            generation_trace.get("fallback_reason")
            or generation_trace.get("failure_code")
            or summary.get("failure_code")
            or "generation_fallback",
        )
    route_fallbacks = _string_items(route_trace.get("fallbacks"))
    _extend_unique(fallback_reasons, route_fallbacks)
    if route_diagnostics.get("used_fallback") and not route_fallbacks:
        _add_unique(fallback_reasons, "route_fallback")

    degraded_sources: list[str] = []
    degraded_candidates: list[dict[str, Any]] = []
    for payload in (degradation_summary, route_diagnostics, response_diagnostics):
        _extend_unique(degraded_sources, _string_items(payload.get("degraded_sources")))
        candidates = _dict_items(payload.get("degraded_candidates"))
        _extend_unique_dicts(degraded_candidates, candidates)
        _extend_unique(
            degraded_sources,
            [
                str(candidate.get("source") or "").strip()
                for candidate in candidates
                if str(candidate.get("source") or "").strip()
            ],
        )

    retrieval_degraded = any(
        bool(payload.get("retrieval_degraded"))
        for payload in (degradation_summary, route_diagnostics, response_diagnostics)
    ) or bool(degraded_sources or degraded_candidates)

    return {
        "fallback_used": bool(generation_fallback or fallback_reasons),
        "fallback_reasons": fallback_reasons,
        "retrieval_degraded": bool(retrieval_degraded),
        "degraded_sources": degraded_sources,
        "degraded_candidates": degraded_candidates,
    }


def evaluate_case(
    system: AdvancedGraphRAGSystem,
    case: EvalCase,
    *,
    top_k: int,
    generate: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    contracts: dict[str, Any] = {
        "answer_response": {},
        "route_resolution": {},
    }
    if generate:
        response = system.answer_question_response(
            case.query,
            stream=False,
            explain_routing=False,
        )
        docs = response.evidence_documents
        answer = response.answer
        strategy = response.strategy or None
        latency_ms = float(response.latency_ms or 0.0)
        plan = _response_query_plan(response)
        contracts["answer_response"] = response.to_dict()
    else:
        routing_workflow = system.retrieval.routing_workflow
        route_resolution = routing_workflow.route(case.query, top_k)
        docs = route_resolution.retrieval.evidence_documents
        analysis = route_resolution.analysis
        answer = ""
        strategy = analysis.recommended_strategy.value if analysis else None
        latency_ms = (time.perf_counter() - start) * 1000
        plan = (
            route_resolution.understanding.query_plan.to_dict()
            if route_resolution.understanding is not None
            else {}
        )
        contracts["route_resolution"] = route_resolution.to_dict()

    response_payload = contracts["answer_response"]
    summary = dict(response_payload.get("summary") or {})
    generation_trace = dict((response_payload.get("traces") or {}).get("generation_trace") or {})
    prompt_tokens = int(summary.get("prompt_tokens", generation_trace.get("prompt_tokens", 0)) or 0)
    completion_tokens = int(
        summary.get(
            "completion_tokens",
            generation_trace.get("completion_tokens", 0),
        )
        or 0
    )
    total_tokens = int(
        summary.get("total_tokens", generation_trace.get("total_tokens", 0))
        or prompt_tokens + completion_tokens
    )
    estimated_cost_usd = float(
        summary.get(
            "estimated_cost_usd",
            generation_trace.get("estimated_cost_usd", 0.0),
        )
        or 0.0
    )
    token_usage_source = str(
        summary.get(
            "token_usage_source",
            generation_trace.get("token_usage_source", ""),
        )
        or ""
    )
    resilience = _answer_resilience_signals(
        contracts["answer_response"],
        contracts["route_resolution"],
    )

    observation = EvalObservation(
        strategy=strategy,
        answer=answer,
        documents=tuple(docs or ()),
        latency_ms=latency_ms,
        plan=plan,
        contracts=contracts,
        resilience=resilience,
        cost={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "token_usage_source": token_usage_source,
        },
    )
    return score_eval_observation(case, observation, top_k=top_k, generate=generate)


def evaluate_offline_quality_queries(
    *,
    top_k: int,
    generate: bool,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    profile: str | None = None,
    profile_path: str | None = None,
) -> dict[str, Any]:
    cases = load_eval_cases(corpus_path)
    config = load_config(profile=profile, profile_path=profile_path)
    results = [
        evaluate_offline_quality_case(
            case,
            index=index,
            top_k=top_k,
            generate=generate,
        )
        for index, case in enumerate(cases)
    ]
    failures = [item for item in results if not item["passed"]]
    return build_eval_report(
        metrics=calculate_eval_metrics(results),
        results=results,
        failures=failures,
        config=config,
        corpus_path=corpus_path,
        top_k=top_k,
        generate=generate,
    )


def _config_profile_metadata(config: GraphRAGConfig) -> dict[str, Any]:
    return {
        "name": getattr(config, "profile_name", ""),
        "path": getattr(config, "profile_path", ""),
        "hash": getattr(config, "profile_hash", ""),
    }


def _query_policy_metadata() -> dict[str, str]:
    return get_query_policy().metadata.to_dict()


def build_eval_report(
    *,
    metrics: dict,
    results: List[dict],
    failures: List[dict],
    config: GraphRAGConfig,
    corpus_path: str | Path,
    top_k: int,
    generate: bool,
    generated_at: str | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "profile": _config_profile_metadata(config),
        "policy": _query_policy_metadata(),
        "corpus": str(Path(corpus_path).resolve()),
        "top_k": int(top_k),
        "generate": bool(generate),
        "metrics": dict(metrics),
        "results": list(results),
        "failures": list(failures),
    }


def _write_eval_report(report: dict[str, Any], output_dir: str | Path) -> Path:
    resolved_output_dir = Path(output_dir).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "report.json"
    summary_path = resolved_output_dir / "summary.md"

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metrics = report.get("metrics") or {}
    profile = report.get("profile") or {}
    policy = report.get("policy") or {}
    summary_lines = [
        "# Eval Summary",
        "",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- profile: {profile.get('name', '') or 'none'}",
        f"- profile_hash: {profile.get('hash', '')}",
        f"- policy_version: {policy.get('policy_version', '')}",
        f"- prompt_version: {policy.get('prompt_version', '')}",
        f"- corpus: {report.get('corpus', '')}",
        f"- top_k: {report.get('top_k', '')}",
        f"- generate: {report.get('generate', False)}",
        f"- case_count: {metrics.get('case_count', 0)}",
        f"- pass_rate: {metrics.get('pass_rate', 0.0)}",
        f"- recall_at_k: {metrics.get('recall_at_k')}",
        f"- mrr: {metrics.get('mrr')}",
        f"- ndcg_at_k: {metrics.get('ndcg_at_k')}",
        f"- faithfulness: {metrics.get('faithfulness')}",
        f"- citation_accuracy: {metrics.get('citation_accuracy')}",
        f"- fallback_rate: {metrics.get('fallback_rate', 0.0)}",
        f"- retrieval_degradation_rate: {metrics.get('retrieval_degradation_rate', 0.0)}",
        f"- degraded_sources: {metrics.get('degraded_sources', [])}",
        f"- p95_latency_ms: {metrics.get('p95_latency_ms', 0.0)}",
        f"- total_tokens: {metrics.get('total_tokens', 0)}",
        f"- estimated_cost_usd: {metrics.get('estimated_cost_usd', 0.0)}",
        f"- failures: {len(report.get('failures') or [])}",
    ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_path


def evaluate_queries(
    *,
    top_k: int,
    generate: bool,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    profile: str | None = None,
    profile_path: str | None = None,
) -> dict[str, Any]:
    cases = load_eval_cases(corpus_path)
    config = load_config(profile=profile, profile_path=profile_path)
    system = AdvancedGraphRAGSystem(config=config)
    system.initialize_system()
    system.build_knowledge_base()

    failures = []
    results = []
    try:
        for case in cases:
            item = evaluate_case(
                system,
                case,
                top_k=top_k,
                generate=generate,
            )
            results.append(item)
            if not item["passed"]:
                failures.append(item)
    finally:
        system.close()

    return build_eval_report(
        metrics=calculate_eval_metrics(results),
        results=results,
        failures=failures,
        config=config,
        corpus_path=corpus_path,
        top_k=top_k,
        generate=generate,
    )


__all__ = [
    "AdvancedGraphRAGSystem",
    "build_eval_report",
    "calculate_eval_metrics",
    "evaluate_case",
    "evaluate_offline_quality_queries",
    "evaluate_queries",
    "load_config",
]
