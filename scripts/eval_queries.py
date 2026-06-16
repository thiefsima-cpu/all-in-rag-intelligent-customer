"""
Small retrieval regression check for the GraphRAG cooking assistant.

This script keeps evaluation data outside retrieval logic. It initializes the
system, routes representative queries from a curated corpus, and checks
expected strategy and recipe names when provided.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.app.system import AdvancedGraphRAGSystem
from rag_modules.configuration import GraphRAGConfig, load_config
from rag_modules.evaluation import grounding_metrics, percentile, retrieval_metrics
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.retrieval_observability import summarize_documents

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "curated_eval_corpus.json"


@dataclass
class EvalCase:
    query: str
    category: str = "general"
    expected_strategy: Optional[str] = None
    expected_recipe_names: List[str] = field(default_factory=list)
    expected_answer_terms: List[str] = field(default_factory=list)
    expected_recipe_relevance: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict) -> "EvalCase":
        return cls(
            query=str(payload.get("query") or "").strip(),
            category=str(payload.get("category") or "general"),
            expected_strategy=payload.get("expected_strategy"),
            expected_recipe_names=[
                str(item).strip()
                for item in (payload.get("expected_recipe_names") or [])
                if str(item).strip()
            ],
            expected_answer_terms=[
                str(item).strip()
                for item in (payload.get("expected_answer_terms") or [])
                if str(item).strip()
            ],
            expected_recipe_relevance={
                str(name).strip(): float(grade)
                for name, grade in dict(
                    payload.get("expected_recipe_relevance") or {}
                ).items()
                if str(name).strip()
            },
        )


def load_eval_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[EvalCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Eval corpus at {corpus_path} must be a JSON list.")
    return [EvalCase.from_dict(item) for item in payload if isinstance(item, dict)]


def _document_metadata(doc: EvidenceDocument | dict[str, Any]) -> dict[str, Any]:
    if isinstance(doc, dict):
        return dict(doc.get("metadata") or {})
    return dict(doc.metadata or {})


def _document_recipe_name(doc: EvidenceDocument | dict[str, Any]) -> str:
    if isinstance(doc, dict):
        return str(doc.get("recipe_name") or _document_metadata(doc).get("recipe_name") or "")
    return str(doc.recipe_name or _document_metadata(doc).get("recipe_name") or "")


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
    return [
        name
        for name in (_document_recipe_name(doc) for doc in docs)
        if name
    ]


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
                    "evidence_type": str(doc.get("evidence_type") or metadata.get("evidence_type") or ""),
                    "matched_terms": list(doc.get("matched_terms") or metadata.get("matched_terms") or []),
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


def _answer_has_graph_reasoning_marker(answer: str) -> bool:
    return any(marker in answer for marker in ("图关系", "关系", "图谱"))


def _complex_answer_failed(category: str, answer: str, *, checked: bool) -> bool:
    if not checked or category not in {"complex_relation", "semantic_flavor"}:
        return False
    return not (
        _answer_has_citation_marker(answer)
        and _answer_has_graph_reasoning_marker(answer)
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

    answer_missing_terms = []
    if generate:
        answer_missing_terms = [
            term for term in case.expected_answer_terms if term not in answer
        ]

    recipe_names = _doc_recipe_names(docs)
    ranked_recipe_names = _ranked_doc_recipe_names(docs)
    expected_recipe_names = list(case.expected_recipe_names) or [
        name
        for name, grade in case.expected_recipe_relevance.items()
        if float(grade or 0.0) > 0
    ]
    missing_names = [
        expected
        for expected in expected_recipe_names
        if expected not in recipe_names
    ]
    strategy_failed = (
        case.expected_strategy is not None
        and strategy != case.expected_strategy
    )
    answer_failed = bool(generate and case.expected_answer_terms and answer_missing_terms)
    complex_answer_failed = _complex_answer_failed(
        case.category,
        answer,
        checked=generate,
    )

    failures: list[str] = []
    if strategy_failed:
        failures.append(
            f"expected_strategy={case.expected_strategy} actual_strategy={strategy}"
        )
    if missing_names:
        failures.append(f"missing_recipe_names={missing_names}")
    if answer_failed:
        failures.append(f"missing_answer_terms={answer_missing_terms}")
    if complex_answer_failed:
        failures.append("complex_answer_grounding_missing")
    if not docs:
        failures.append("no_evidence")

    relevance = (
        case.expected_recipe_relevance
        or {name: 1.0 for name in case.expected_recipe_names}
    )
    ranking = retrieval_metrics(
        ranked_recipe_names,
        relevance,
        k=top_k,
    )
    grounding = (
        grounding_metrics(answer, docs)
        if generate
        else {
            "claim_count": 0,
            "supported_claim_count": 0,
            "faithfulness": None,
            "citation_count": 0,
            "valid_citation_count": 0,
            "citation_accuracy": None,
            "citation_coverage": None,
        }
    )
    response_payload = contracts["answer_response"]
    summary = dict(response_payload.get("summary") or {})
    generation_trace = dict(
        (response_payload.get("traces") or {}).get("generation_trace") or {}
    )
    prompt_tokens = int(
        summary.get("prompt_tokens", generation_trace.get("prompt_tokens", 0))
        or 0
    )
    completion_tokens = int(
        summary.get(
            "completion_tokens",
            generation_trace.get("completion_tokens", 0),
        )
        or 0
    )
    total_tokens = int(
        summary.get("total_tokens", generation_trace.get("total_tokens", 0))
        or prompt_tokens
        + completion_tokens
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

    return {
        "query": case.query,
        "category": case.category,
        "passed": not failures,
        "failures": failures,
        "evaluation": {
            "strategy": strategy,
            "expected_strategy": case.expected_strategy,
            "expected_recipe_names": expected_recipe_names,
            "expected_recipe_relevance": dict(case.expected_recipe_relevance),
            "expected_answer_terms": list(case.expected_answer_terms),
            "answer_checked": bool(generate),
            "answer_passed": (not answer_failed) if generate else None,
            "complex_answer_passed": (
                not complex_answer_failed
                if generate and case.category in {"complex_relation", "semantic_flavor"}
                else None
            ),
            "answer_missing_terms": answer_missing_terms,
            "answer_preview": answer[:300] if answer else "",
        },
        "retrieval": {
            "recipe_names": recipe_names,
            "ranked_recipe_names": ranked_recipe_names,
            "missing_recipe_names": missing_names,
            "doc_count": len(docs),
            "evidence": _doc_evidence_summary(docs),
            **ranking,
        },
        "grounding": grounding,
        "cost": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "estimated_cost_usd": estimated_cost_usd,
            "token_usage_source": token_usage_source,
        },
        "runtime": {
            "latency_ms": latency_ms,
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
        item
        for item in results
        if item.get("evaluation", {}).get("expected_recipe_names")
    ]
    recipe_passed = sum(
        1
        for item in recipe_cases
        if not item.get("retrieval", {}).get("missing_recipe_names")
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
        for item in results
        if item.get("retrieval", {}).get("recall_at_k") is not None
    ]
    reciprocal_ranks = [
        item.get("retrieval", {}).get("reciprocal_rank")
        for item in results
        if item.get("retrieval", {}).get("reciprocal_rank") is not None
    ]
    ndcg_values = [
        item.get("retrieval", {}).get("ndcg_at_k")
        for item in results
        if item.get("retrieval", {}).get("ndcg_at_k") is not None
    ]
    faithfulness_values = [
        item.get("grounding", {}).get("faithfulness")
        for item in results
        if item.get("grounding", {}).get("faithfulness") is not None
    ]
    citation_accuracy_values = [
        item.get("grounding", {}).get("citation_accuracy")
        for item in results
        if item.get("grounding", {}).get("citation_accuracy") is not None
    ]
    total_prompt_tokens = sum(
        int(item.get("cost", {}).get("prompt_tokens", 0) or 0)
        for item in results
    )
    total_completion_tokens = sum(
        int(item.get("cost", {}).get("completion_tokens", 0) or 0)
        for item in results
    )
    total_tokens = sum(
        int(item.get("cost", {}).get("total_tokens", 0) or 0)
        for item in results
    )
    total_estimated_cost_usd = sum(
        float(item.get("cost", {}).get("estimated_cost_usd", 0.0) or 0.0)
        for item in results
    )
    answer_cases = [
        item for item in results if item.get("evaluation", {}).get("answer_checked")
    ]
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
        if _answer_has_citation_marker(
            item.get("evaluation", {}).get("answer_preview", "")
        )
    )
    grouped = {}
    for item in results:
        grouped.setdefault(item.get("category", "general"), []).append(item)
    category_metrics = {}
    for category, items in grouped.items():
        category_metrics[category] = {
            "case_count": len(items),
            "pass_rate": sum(1 for item in items if item["passed"]) / len(items),
            "avg_latency_ms": (
                sum(item.get("runtime", {}).get("latency_ms", 0.0) for item in items)
                / len(items)
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
        "strategy_accuracy": strategy_passed / len(strategy_cases) if strategy_cases else None,
        "recipe_hit_rate": recipe_passed / len(recipe_cases) if recipe_cases else None,
        "graph_evidence_coverage": graph_covered / total,
        "graph_evidence_unit_coverage": graph_unit_covered / total,
        "avg_evidence_score": sum(scores) / len(scores) if scores else 0.0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "recall_at_k": (
            sum(recall_values) / len(recall_values) if recall_values else None
        ),
        "mrr": (
            sum(reciprocal_ranks) / len(reciprocal_ranks)
            if reciprocal_ranks
            else None
        ),
        "ndcg_at_k": (
            sum(ndcg_values) / len(ndcg_values) if ndcg_values else None
        ),
        "faithfulness": (
            sum(faithfulness_values) / len(faithfulness_values)
            if faithfulness_values
            else None
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
        "avg_cost_usd_per_case": (
            total_estimated_cost_usd / total if total else 0.0
        ),
        "answer_pass_rate": answer_passed / len(answer_cases) if answer_cases else None,
        "answer_citation_rate": citation_passed / len(citation_cases) if citation_cases else None,
        "by_category": category_metrics,
    }


def _config_profile_metadata(config: GraphRAGConfig) -> dict[str, Any]:
    return {
        "name": getattr(config, "profile_name", ""),
        "path": getattr(config, "profile_path", ""),
        "hash": getattr(config, "profile_hash", ""),
    }


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
    summary_lines = [
        "# Eval Summary",
        "",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- profile: {profile.get('name', '') or 'none'}",
        f"- profile_hash: {profile.get('hash', '')}",
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
        f"- p95_latency_ms: {metrics.get('p95_latency_ms', 0.0)}",
        f"- total_tokens: {metrics.get('total_tokens', 0)}",
        f"- estimated_cost_usd: {metrics.get('estimated_cost_usd', 0.0)}",
        f"- failures: {len(report.get('failures') or [])}",
    ]
    summary_path.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return report_path


def run_eval(
    top_k: int,
    as_json: bool,
    generate: bool,
    *,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    profile: str | None = None,
    profile_path: str | None = None,
    output_dir: str | Path | None = None,
) -> int:
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

    report = build_eval_report(
        metrics=calculate_eval_metrics(results),
        results=results,
        failures=failures,
        config=config,
        corpus_path=corpus_path,
        top_k=top_k,
        generate=generate,
    )
    if output_dir is not None:
        report_path = _write_eval_report(report, output_dir)
        if not as_json:
            print(f"report={report_path}")

    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"profile={report['profile']}")
        print(f"metrics={report['metrics']}")
        for item in results:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"[{status}] {item['query']}")
            print(
                f"  strategy={item['evaluation']['strategy']} "
                f"docs={item['retrieval']['doc_count']} "
                f"recipes={item['retrieval']['recipe_names'][:5]}"
            )
            print(
                f"  latency_ms={item['runtime']['latency_ms']:.1f} "
                f"plan_used_cache={item['runtime']['plan_used_cache']}"
            )
            print(f"  category={item['category']} failures={item['failures']}")
            print(f"  evidence={item['retrieval']['evidence'][:3]}")
            if item["retrieval"]["missing_recipe_names"]:
                print(f"  missing={item['retrieval']['missing_recipe_names']}")
            if (
                item["evaluation"]["expected_strategy"]
                and item["evaluation"]["strategy"] != item["evaluation"]["expected_strategy"]
            ):
                print(f"  expected_strategy={item['evaluation']['expected_strategy']}")
            if item["evaluation"]["answer_checked"]:
                print(
                    f"  answer_passed={item['evaluation']['answer_passed']} "
                    f"missing_terms={item['evaluation']['answer_missing_terms']}"
                )
                print(f"  answer_preview={item['evaluation']['answer_preview']}")

    return 1 if failures else 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--generate", action="store_true", help="Also generate answers and check expected answer terms.")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH), help="Path to the curated eval corpus JSON file.")
    parser.add_argument("--profile", default=None, help="Configuration profile name from the profiles directory.")
    parser.add_argument("--profile-path", default=None, help="Explicit TOML profile path.")
    parser.add_argument("--output-dir", default=None, help="Optional directory for report.json and summary.md.")
    args = parser.parse_args()
    return run_eval(
        top_k=args.top_k,
        as_json=args.json,
        generate=args.generate,
        corpus_path=args.corpus,
        profile=args.profile,
        profile_path=args.profile_path,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
