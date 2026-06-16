"""Offline smoke harness for generation planning and evidence packaging."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.answer_evidence_builder import AnswerEvidenceBuilder
from rag_modules.generation import (
    GenerationPlanner,
    GenerationPromptBuilder,
    GenerationSettings,
    decide_generation_mode,
)
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import AnswerContext, QueryAnalysis, RetrievalOutcome


DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "generation_plan_corpus.json"
)


class _OfflineClientAdapter:
    def create_completion(self, **_: object) -> None:
        raise AssertionError("Offline generation smoke should not call external models.")


@dataclass
class GenerationPlanSmokeCase:
    name: str
    question: str
    evidence_documents: List[EvidenceDocument]
    analysis: QueryAnalysis
    expected_mode: str
    expected_answer_type: str
    expected_reasoning_mode: str = ""
    expected_package_items: int = 0
    expected_min_key_points: int = 1
    require_graph_key_point: bool = False
    require_missing_information: bool = False
    required_citations: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "GenerationPlanSmokeCase":
        return cls(
            name=str(payload.get("name") or "").strip(),
            question=str(payload.get("question") or "").strip(),
            evidence_documents=[
                EvidenceDocument.from_dict(item)
                for item in (payload.get("evidence_documents") or [])
                if isinstance(item, dict)
            ],
            analysis=QueryAnalysis.from_dict(payload.get("analysis") or {}),
            expected_mode=str(payload.get("expected_mode") or "").strip(),
            expected_answer_type=str(payload.get("expected_answer_type") or "").strip(),
            expected_reasoning_mode=str(
                payload.get("expected_reasoning_mode") or ""
            ).strip(),
            expected_package_items=max(0, int(payload.get("expected_package_items") or 0)),
            expected_min_key_points=max(
                0,
                int(payload.get("expected_min_key_points") or 0),
            ),
            require_graph_key_point=bool(payload.get("require_graph_key_point")),
            require_missing_information=bool(payload.get("require_missing_information")),
            required_citations=[
                str(item).strip()
                for item in (payload.get("required_citations") or [])
                if str(item).strip()
            ],
        )


def load_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[GenerationPlanSmokeCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Generation smoke corpus at {corpus_path} must be a JSON list.")
    return [GenerationPlanSmokeCase.from_dict(item) for item in payload if isinstance(item, dict)]


def build_generation_stack() -> tuple[GenerationSettings, AnswerEvidenceBuilder, GenerationPromptBuilder, GenerationPlanner]:
    settings = GenerationSettings(planner_mode="rule")
    evidence_builder = AnswerEvidenceBuilder(max_content_chars=700)
    prompt_builder = GenerationPromptBuilder(settings=settings, evidence_max_chars=700)
    planner = GenerationPlanner(
        settings=settings,
        client_adapter=_OfflineClientAdapter(),
        prompt_builder=prompt_builder,
    )
    return settings, evidence_builder, prompt_builder, planner


def evaluate_case(
    settings: GenerationSettings,
    evidence_builder: AnswerEvidenceBuilder,
    prompt_builder: GenerationPromptBuilder,
    planner: GenerationPlanner,
    case: GenerationPlanSmokeCase,
) -> dict:
    package = evidence_builder.build(case.question, case.evidence_documents)
    answer_context = AnswerContext(
        question=case.question,
        retrieval=RetrievalOutcome(
            query=case.question,
            evidence_documents=case.evidence_documents,
        ),
        analysis=case.analysis,
    ).with_evidence_package(package)
    decision = decide_generation_mode(
        package=package,
        settings=settings,
        analysis=case.analysis,
    )
    selected_package = package.limit_items(decision.evidence_limit)
    selected_context = answer_context.with_evidence_package(selected_package)
    plan = planner.build_answer_plan_from_context(selected_context)
    rendered_prompt = prompt_builder.render_compose_prompt_from_context(
        selected_context,
        plan,
    )
    compose_prompt = rendered_prompt.text

    graph_key_points = [
        point for point in plan.key_points if bool(point.get("use_graph_evidence"))
    ]
    citations = sorted(
        {
            citation
            for point in plan.key_points
            for citation in point.get("citations", [])
            if str(citation).strip()
        }
    )

    failures: List[str] = []
    if decision.mode != case.expected_mode:
        failures.append(f"expected_mode={case.expected_mode} actual_mode={decision.mode}")
    if plan.answer_type != case.expected_answer_type:
        failures.append(
            f"expected_answer_type={case.expected_answer_type} actual_answer_type={plan.answer_type}"
        )
    if case.expected_reasoning_mode and plan.reasoning_mode != case.expected_reasoning_mode:
        failures.append(
            "expected_reasoning_mode="
            f"{case.expected_reasoning_mode} actual_reasoning_mode={plan.reasoning_mode}"
        )
    if case.expected_package_items and len(package.items) != case.expected_package_items:
        failures.append(
            f"expected_package_items={case.expected_package_items} actual_package_items={len(package.items)}"
        )
    if len(plan.key_points) < case.expected_min_key_points:
        failures.append(
            f"expected_min_key_points={case.expected_min_key_points} actual_key_points={len(plan.key_points)}"
        )
    if case.require_graph_key_point and not graph_key_points:
        failures.append("expected_graph_key_point=true actual_graph_key_point=false")
    if case.require_missing_information and not plan.missing_information:
        failures.append("expected_missing_information=true actual_missing_information=false")

    missing_citations = [
        citation for citation in case.required_citations if citation not in citations
    ]
    if missing_citations:
        failures.append(f"missing_plan_citations={missing_citations}")

    missing_prompt_citations = [
        citation for citation in case.required_citations if citation not in compose_prompt
    ]
    if missing_prompt_citations:
        failures.append(f"missing_prompt_citations={missing_prompt_citations}")

    return {
        "name": case.name,
        "question": case.question,
        "passed": not failures,
        "failures": failures,
        "decision": {
            "mode": decision.mode,
            "reason": decision.reason,
            "evidence_limit": decision.evidence_limit,
        },
        "package_item_count": len(package.items),
        "selected_item_count": len(selected_package.items),
        "citations": citations,
        "graph_key_point_count": len(graph_key_points),
        "plan": plan.to_dict(),
        "prompt": rendered_prompt.to_dict(),
    }


def run_smoke(corpus_path: str | Path = DEFAULT_CORPUS_PATH) -> dict:
    settings, evidence_builder, prompt_builder, planner = build_generation_stack()
    results = [
        evaluate_case(settings, evidence_builder, prompt_builder, planner, case)
        for case in load_cases(corpus_path)
    ]
    failures = [item for item in results if not item["passed"]]
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
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
        print(f"case_count={report['case_count']} passed_count={report['passed_count']}")
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            decision = item["decision"]
            plan = item["plan"]
            print(f"[{status}] {item['name']}: {item['question']}")
            print(
                "  "
                f"mode={decision['mode']} reason={decision['reason']} "
                f"answer_type={plan['answer_type']} reasoning_mode={plan['reasoning_mode']}"
            )
            if item["failures"]:
                print(f"  failures={item['failures']}")

    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
