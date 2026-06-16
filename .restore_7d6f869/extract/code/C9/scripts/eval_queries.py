"""
Small retrieval regression check for the GraphRAG cooking assistant.

This script keeps evaluation data outside retrieval logic. It is intentionally
lightweight: it initializes the system, routes several representative queries,
and checks expected strategy and recipe names when provided.
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import AdvancedGraphRAGSystem


@dataclass
class EvalCase:
    query: str
    category: str = "general"
    expected_strategy: Optional[str] = None
    expected_recipe_names: List[str] = field(default_factory=list)
    expected_answer_terms: List[str] = field(default_factory=list)


DEFAULT_CASES = [
    EvalCase(
        query="水煮肉片为什么能形成麻辣鲜香的口味？它和豆瓣酱、花椒、辣椒、蔬菜垫底、肉片上浆这些食材和步骤之间有什么关系？",
        category="complex_relation",
        expected_strategy="graph_rag",
        expected_recipe_names=["水煮肉片"],
        expected_answer_terms=["麻辣", "花椒"],
    ),
    EvalCase(
        query="宫保鸡丁怎么做？",
        category="single_recipe",
        expected_recipe_names=["宫保鸡丁"],
    ),
    EvalCase(
        query="如果我只有鸡肉和蔬菜，能做什么菜，最好是不同菜系的？",
        category="recommendation",
        expected_recipe_names=[],
    ),
    EvalCase(
        query="适合控糖饮食的低糖菜有哪些，并且制作时间不超过30分钟？",
        category="constrained_recommendation",
        expected_recipe_names=[],
    ),
    EvalCase(
        query="麻辣口味通常和哪些食材、技法或步骤关系更密切？请用图谱关系解释。",
        category="complex_relation",
        expected_strategy="graph_rag",
        expected_answer_terms=["麻辣"],
    ),
    EvalCase(
        query="鱼香肉丝的主要做法是什么？",
        category="single_recipe",
        expected_recipe_names=["鱼香肉丝"],
    ),
    EvalCase(
        query="推荐几道带豆腐、口味清淡一点的家常菜。",
        category="recommendation",
        expected_recipe_names=[],
    ),
    EvalCase(
        query="少油、30分钟内能完成的鸡肉菜有哪些？",
        category="constrained_recommendation",
        expected_recipe_names=[],
    ),
    EvalCase(
        query="上浆、花椒、辣椒分别会怎样影响水煮类菜的口感和风味？",
        category="semantic_flavor",
        expected_strategy="graph_rag",
        expected_answer_terms=["上浆", "花椒"],
    ),
    EvalCase(
        query="有没有完全不需要任何调味料、同时又是麻辣味的菜？",
        category="weak_or_conflicting",
        expected_recipe_names=[],
    ),
]


def _doc_recipe_names(docs) -> List[str]:
    names = []
    for doc in docs:
        name = doc.metadata.get("recipe_name")
        if name and name not in names:
            names.append(name)
    return names


def _doc_evidence_summary(docs) -> List[dict]:
    return [
        {
            "doc_id": doc.metadata.get("doc_id"),
            "recipe_id": doc.metadata.get("recipe_id"),
            "recipe_name": doc.metadata.get("recipe_name"),
            "source": doc.metadata.get("source"),
            "score": doc.metadata.get("score"),
            "evidence_type": doc.metadata.get("evidence_type"),
            "has_graph_evidence": bool(doc.metadata.get("graph_evidence")),
            "evidence_unit_count": len(doc.metadata.get("evidence_units") or []),
            "graph_evidence_unit_count": sum(
                1
                for unit in (doc.metadata.get("evidence_units") or [])
                if unit.get("is_graph_evidence")
            ),
            "constraint_evidence": doc.metadata.get("constraint_evidence"),
        }
        for doc in docs
    ]


def _metrics(results: List[dict]) -> dict:
    total = len(results)
    if total == 0:
        return {}
    passed = sum(1 for item in results if item["passed"])
    strategy_cases = [item for item in results if item["expected_strategy"]]
    strategy_passed = sum(
        1 for item in strategy_cases
        if item["strategy"] == item["expected_strategy"]
    )
    recipe_cases = [item for item in results if item.get("expected_recipe_names")]
    recipe_passed = sum(
        1 for item in recipe_cases
        if not item.get("missing_recipe_names")
    )
    graph_covered = sum(
        1 for item in results
        if any(evidence.get("has_graph_evidence") for evidence in item.get("evidence", []))
    )
    graph_unit_covered = sum(
        1 for item in results
        if any(evidence.get("graph_evidence_unit_count", 0) > 0 for evidence in item.get("evidence", []))
    )
    scores = [
        evidence.get("score") or 0.0
        for item in results
        for evidence in item.get("evidence", [])
    ]
    latencies = [item.get("latency_ms", 0.0) for item in results]
    answer_cases = [item for item in results if item.get("answer_checked")]
    answer_passed = sum(1 for item in answer_cases if item.get("answer_passed"))
    citation_cases = [item for item in results if item.get("answer_checked") and item.get("answer_preview")]
    citation_passed = sum(
        1 for item in citation_cases
        if "菜谱证据" in item.get("answer_preview", "") or "依据" in item.get("answer_preview", "")
    )
    grouped = {}
    for item in results:
        grouped.setdefault(item.get("category", "general"), []).append(item)
    category_metrics = {}
    for category, items in grouped.items():
        category_metrics[category] = {
            "case_count": len(items),
            "pass_rate": sum(1 for item in items if item["passed"]) / len(items),
            "avg_latency_ms": sum(item.get("latency_ms", 0.0) for item in items) / len(items),
            "graph_evidence_coverage": sum(
                1
                for item in items
                if any(evidence.get("has_graph_evidence") for evidence in item.get("evidence", []))
            ) / len(items),
            "graph_evidence_unit_coverage": sum(
                1
                for item in items
                if any(evidence.get("graph_evidence_unit_count", 0) > 0 for evidence in item.get("evidence", []))
            ) / len(items),
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
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "answer_pass_rate": answer_passed / len(answer_cases) if answer_cases else None,
        "answer_citation_rate": citation_passed / len(citation_cases) if citation_cases else None,
        "by_category": category_metrics,
    }


def run_eval(top_k: int, as_json: bool, generate: bool) -> int:
    system = AdvancedGraphRAGSystem()
    system.initialize_system()
    system.build_knowledge_base()

    failures = []
    results = []
    try:
        for case in DEFAULT_CASES:
            start = time.perf_counter()
            docs, analysis = system.query_router.route_query(case.query, top_k)
            route_trace = getattr(system.query_router, "last_trace", {})
            answer = ""
            answer_missing_terms = []
            if generate:
                answer = system.generation_module.generate_adaptive_answer(case.query, docs, analysis=analysis)
                answer_missing_terms = [
                    term for term in case.expected_answer_terms
                    if term not in answer
                ]
            latency_ms = (time.perf_counter() - start) * 1000
            strategy = analysis.recommended_strategy.value if analysis else None
            recipe_names = _doc_recipe_names(docs)
            plan = docs[0].metadata.get("query_plan", {}) if docs else {}

            missing_names = [
                expected for expected in case.expected_recipe_names
                if expected not in recipe_names
            ]
            strategy_failed = (
                case.expected_strategy is not None
                and strategy != case.expected_strategy
            )
            answer_failed = bool(generate and case.expected_answer_terms and answer_missing_terms)
            complex_answer_failed = False
            if generate and case.category in {"complex_relation", "semantic_flavor"}:
                complex_answer_failed = not (
                    ("菜谱证据" in answer or "依据" in answer)
                    and ("图关系" in answer or "关系" in answer or "图谱" in answer)
                )
            passed = not missing_names and not strategy_failed and not answer_failed and not complex_answer_failed and bool(docs)
            item = {
                "query": case.query,
                "category": case.category,
                "passed": passed,
                "strategy": strategy,
                "expected_strategy": case.expected_strategy,
                "recipe_names": recipe_names,
                "evidence": _doc_evidence_summary(docs),
                "missing_recipe_names": missing_names,
                "doc_count": len(docs),
                "latency_ms": latency_ms,
                "plan_used_cache": plan.get("used_cache"),
                "plan_validation_errors": plan.get("validation_errors"),
                "route_trace": route_trace,
                "generation_trace": getattr(system.generation_module, "last_trace", {}),
                "diagnostics": getattr(system.query_tracer, "last_event", {}).get("diagnostics", {}),
                "answer_checked": bool(generate),
                "answer_passed": not answer_failed if generate else None,
                "complex_answer_passed": (
                    not complex_answer_failed
                    if generate and case.category in {"complex_relation", "semantic_flavor"}
                    else None
                ),
                "answer_missing_terms": answer_missing_terms,
                "answer_preview": answer[:300] if answer else "",
            }
            results.append(item)
            if not passed:
                failures.append(item)
    finally:
        system._cleanup()

    if as_json:
        print(json.dumps({"metrics": _metrics(results), "results": results, "failures": failures}, ensure_ascii=False, indent=2))
    else:
        print(f"metrics={_metrics(results)}")
        for item in results:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"[{status}] {item['query']}")
            print(f"  strategy={item['strategy']} docs={item['doc_count']} recipes={item['recipe_names'][:5]}")
            print(f"  latency_ms={item['latency_ms']:.1f} plan_used_cache={item['plan_used_cache']}")
            print(f"  category={item['category']} route_trace={item['route_trace'].get('stages', {})}")
            print(f"  evidence={item['evidence'][:3]}")
            if item["missing_recipe_names"]:
                print(f"  missing={item['missing_recipe_names']}")
            if item["expected_strategy"] and item["strategy"] != item["expected_strategy"]:
                print(f"  expected_strategy={item['expected_strategy']}")
            if item["answer_checked"]:
                print(f"  answer_passed={item['answer_passed']} missing_terms={item['answer_missing_terms']}")
                print(f"  answer_preview={item['answer_preview']}")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--generate", action="store_true", help="Also generate answers and check expected answer terms.")
    args = parser.parse_args()
    return run_eval(top_k=args.top_k, as_json=args.json, generate=args.generate)


if __name__ == "__main__":
    sys.exit(main())
