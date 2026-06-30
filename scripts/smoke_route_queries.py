"""Offline route smoke harness for query semantics and planner behavior."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.contracts import (
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
)
from rag_modules.query_understanding import QueryPlanner

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "route_smoke_corpus.json"
)


class _DummyCompletions:
    def create(self, **_: object) -> None:
        raise AssertionError("Offline smoke mode should not call the LLM planner.")


class _DummyChat:
    def __init__(self) -> None:
        self.completions = _DummyCompletions()


class _DummyLLM:
    def __init__(self) -> None:
        self.chat = _DummyChat()


@dataclass
class RouteSmokeCase:
    query: str
    expected_strategy: str
    name: str = ""
    category: str = "general"
    expected_graph_query_type: str = ""
    expected_intent: str = ""
    expected_reasoning_required: Optional[bool] = None
    expected_needs_recipe_recommendation: Optional[bool] = None
    required_relation_types: List[str] = field(default_factory=list)
    expected_constraints: dict[str, Any] = field(default_factory=dict)
    min_complexity: float = 0.0
    min_relationship_intensity: float = 0.0

    @classmethod
    def from_dict(cls, payload: dict) -> "RouteSmokeCase":
        return cls(
            query=str(payload.get("query") or "").strip(),
            expected_strategy=str(payload.get("expected_strategy") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            category=str(payload.get("category") or "general").strip() or "general",
            expected_graph_query_type=str(payload.get("expected_graph_query_type") or "").strip(),
            expected_intent=str(payload.get("expected_intent") or "").strip(),
            expected_reasoning_required=(
                bool(payload.get("expected_reasoning_required"))
                if "expected_reasoning_required" in payload
                else None
            ),
            expected_needs_recipe_recommendation=(
                bool(payload.get("expected_needs_recipe_recommendation"))
                if "expected_needs_recipe_recommendation" in payload
                else None
            ),
            required_relation_types=[
                str(item).strip()
                for item in (payload.get("required_relation_types") or [])
                if str(item).strip()
            ],
            expected_constraints=dict(payload.get("expected_constraints") or {}),
            min_complexity=float(payload.get("min_complexity") or 0.0),
            min_relationship_intensity=float(payload.get("min_relationship_intensity") or 0.0),
        )


def load_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[RouteSmokeCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Route smoke corpus at {corpus_path} must be a JSON list.")
    return [RouteSmokeCase.from_dict(item) for item in payload if isinstance(item, dict)]


def build_planner() -> QueryPlanner:
    return QueryPlanner(
        _DummyLLM(),
        settings=QueryPlannerRuntimeSettings(fast_rule_planning=True),
        semantic_settings=QuerySemanticRuntimeSettings(),
    )


def _subset_failures(
    expected: Any,
    actual: Any,
    *,
    path: str,
) -> List[str]:
    failures: List[str] = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [f"{path}:expected_object actual={actual!r}"]
        for key, value in expected.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key not in actual:
                failures.append(f"{child_path}:missing")
                continue
            failures.extend(_subset_failures(value, actual[key], path=child_path))
        return failures
    if isinstance(expected, list):
        actual_items = list(actual or []) if isinstance(actual, (list, tuple, set)) else []
        missing = [item for item in expected if item not in actual_items]
        if missing:
            failures.append(f"{path}:missing_items={missing}")
        return failures
    if actual != expected:
        failures.append(f"{path}:expected={expected!r} actual={actual!r}")
    return failures


def evaluate_case(planner: QueryPlanner, case: RouteSmokeCase) -> dict:
    plan = planner.rule_based_plan(case.query)
    failures: List[str] = []
    graph_query_type = plan.graph_query_type_value
    if plan.strategy != case.expected_strategy:
        failures.append(
            f"expected_strategy={case.expected_strategy} actual_strategy={plan.strategy}"
        )
    if case.expected_graph_query_type and graph_query_type != case.expected_graph_query_type:
        failures.append(
            "expected_graph_query_type="
            f"{case.expected_graph_query_type} actual_graph_query_type={graph_query_type}"
        )
    if case.expected_intent and plan.intent != case.expected_intent:
        failures.append(f"expected_intent={case.expected_intent} actual_intent={plan.intent}")
    if (
        case.expected_reasoning_required is not None
        and plan.reasoning_required != case.expected_reasoning_required
    ):
        failures.append(
            "expected_reasoning_required="
            f"{case.expected_reasoning_required} actual_reasoning_required={plan.reasoning_required}"
        )
    if (
        case.expected_needs_recipe_recommendation is not None
        and plan.needs_recipe_recommendation != case.expected_needs_recipe_recommendation
    ):
        failures.append(
            "expected_needs_recipe_recommendation="
            f"{case.expected_needs_recipe_recommendation} "
            f"actual_needs_recipe_recommendation={plan.needs_recipe_recommendation}"
        )
    missing_relation_types = [
        relation_type
        for relation_type in case.required_relation_types
        if relation_type not in plan.relation_types
    ]
    if missing_relation_types:
        failures.append(f"missing_relation_types={missing_relation_types}")
    if plan.complexity < case.min_complexity:
        failures.append(f"min_complexity={case.min_complexity} actual_complexity={plan.complexity}")
    if plan.relationship_intensity < case.min_relationship_intensity:
        failures.append(
            "min_relationship_intensity="
            f"{case.min_relationship_intensity} "
            f"actual_relationship_intensity={plan.relationship_intensity}"
        )
    constraints = plan.constraints.to_dict()
    failures.extend(
        _subset_failures(
            case.expected_constraints,
            constraints,
            path="constraints",
        )
    )
    return {
        "name": case.name or case.query,
        "category": case.category,
        "query": case.query,
        "passed": not failures,
        "failures": failures,
        "expected_strategy": case.expected_strategy,
        "strategy": plan.strategy,
        "expected_graph_query_type": case.expected_graph_query_type,
        "graph_query_type": graph_query_type,
        "intent": plan.intent,
        "reasoning_required": plan.reasoning_required,
        "needs_recipe_recommendation": plan.needs_recipe_recommendation,
        "complexity": plan.complexity,
        "relationship_intensity": plan.relationship_intensity,
        "source_entities": list(plan.source_entities),
        "target_entities": list(plan.target_entities),
        "entity_keywords": list(plan.entity_keywords),
        "relation_types": list(plan.relation_types),
        "constraints": constraints,
        "validation_errors": list(plan.validation_errors),
    }


def run_smoke(corpus_path: str | Path = DEFAULT_CORPUS_PATH) -> dict:
    planner = build_planner()
    results = [evaluate_case(planner, case) for case in load_cases(corpus_path)]
    failures = [item for item in results if not item["passed"]]
    category_counts = Counter(item["category"] for item in results)
    strategy_counts = Counter(item["strategy"] for item in results)
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
        "pass_rate": ((len(results) - len(failures)) / len(results) if results else 0.0),
        "category_count": len(category_counts),
        "category_counts": dict(sorted(category_counts.items())),
        "strategy_counts": dict(sorted(strategy_counts.items())),
        "results": results,
        "failures": failures,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_smoke(args.corpus)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"case_count={report['case_count']} "
            f"passed_count={report['passed_count']} "
            f"category_count={report['category_count']}"
        )
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(f"[{status}] {item['name']}: {item['query']}")
            print(
                f"  strategy={item['strategy']} graph_query_type={item['graph_query_type']} "
                f"complexity={item['complexity']:.2f} relationship_intensity={item['relationship_intensity']:.2f}"
            )
            print(f"  source_entities={item['source_entities']}")
            if item["failures"]:
                print(f"  failures={item['failures']}")
            if item["validation_errors"]:
                print(f"  validation_errors={item['validation_errors']}")

    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
