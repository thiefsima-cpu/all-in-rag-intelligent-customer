"""Offline snapshot smoke for direct and compose generation prompts."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.generation import RenderedPrompt, decide_generation_mode
from rag_modules.runtime import AnswerContext, RetrievalOutcome
from scripts.smoke_generation_plans import (
    DEFAULT_CORPUS_PATH as DEFAULT_PLAN_CORPUS_PATH,
)
from scripts.smoke_generation_plans import (
    build_generation_stack,
)
from scripts.smoke_generation_plans import (
    load_cases as load_plan_cases,
)

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "generation_prompt_snapshot_corpus.json"
)


@dataclass
class PromptSnapshotCase:
    name: str
    plan_case: str
    prompt_type: str
    snapshot_path: Path
    required_substrings: List[str] = field(default_factory=list)
    forbidden_substrings: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict, *, root_dir: Path) -> "PromptSnapshotCase":
        return cls(
            name=str(payload.get("name") or "").strip(),
            plan_case=str(payload.get("plan_case") or "").strip(),
            prompt_type=str(payload.get("prompt_type") or "").strip(),
            snapshot_path=(root_dir / str(payload.get("snapshot_path") or "").strip()).resolve(),
            required_substrings=[
                str(item).strip()
                for item in (payload.get("required_substrings") or [])
                if str(item).strip()
            ],
            forbidden_substrings=[
                str(item).strip()
                for item in (payload.get("forbidden_substrings") or [])
                if str(item).strip()
            ],
        )


def load_snapshot_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[PromptSnapshotCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Generation prompt corpus at {corpus_path} must be a JSON list.")
    root_dir = corpus_path.parents[2]
    return [
        PromptSnapshotCase.from_dict(item, root_dir=root_dir)
        for item in payload
        if isinstance(item, dict)
    ]


def normalize_prompt_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized_lines = [line.rstrip() for line in normalized.split("\n")]
    return "\n".join(normalized_lines).strip("\n") + "\n"


def build_rendered_prompt(
    case: PromptSnapshotCase, plan_case_index: Dict[str, object]
) -> RenderedPrompt:
    plan_case = plan_case_index.get(case.plan_case)
    if plan_case is None:
        raise KeyError(f"Missing plan case '{case.plan_case}' for prompt snapshot '{case.name}'.")

    settings, evidence_builder, prompt_builder, planner = build_generation_stack()
    package = evidence_builder.build(plan_case.question, plan_case.evidence_documents)
    answer_context = AnswerContext(
        question=plan_case.question,
        retrieval=RetrievalOutcome(
            query=plan_case.question,
            evidence_documents=plan_case.evidence_documents,
        ),
        analysis=plan_case.analysis,
    ).with_evidence_package(package)
    decision = decide_generation_mode(
        package=package,
        settings=settings,
        analysis=plan_case.analysis,
    )
    selected_package = package.limit_items(decision.evidence_limit)
    selected_context = answer_context.with_evidence_package(selected_package)

    if case.prompt_type == "direct":
        return prompt_builder.render_direct_answer_prompt_from_context(selected_context)
    if case.prompt_type == "compose":
        plan = planner.build_answer_plan_from_context(selected_context)
        return prompt_builder.render_compose_prompt_from_context(selected_context, plan)
    raise ValueError(
        f"Unsupported prompt_type '{case.prompt_type}' in snapshot case '{case.name}'."
    )


def build_prompt_text(case: PromptSnapshotCase, plan_case_index: Dict[str, object]) -> str:
    return build_rendered_prompt(case, plan_case_index).text


def _snapshot_diff(expected: str, actual: str, *, snapshot_path: Path) -> List[str]:
    diff_lines = list(
        difflib.unified_diff(
            expected.splitlines(),
            actual.splitlines(),
            fromfile=f"{snapshot_path.name}:expected",
            tofile=f"{snapshot_path.name}:actual",
            lineterm="",
            n=2,
        )
    )
    return diff_lines[:40]


def evaluate_case(
    case: PromptSnapshotCase,
    plan_case_index: Dict[str, object],
    *,
    write_snapshots: bool = False,
) -> dict:
    prompt_text = normalize_prompt_text(build_prompt_text(case, plan_case_index))
    failures: List[str] = []

    for substring in case.required_substrings:
        if substring not in prompt_text:
            failures.append(f"missing_required_substring={substring}")
    for substring in case.forbidden_substrings:
        if substring in prompt_text:
            failures.append(f"forbidden_substring_present={substring}")

    snapshot_exists = case.snapshot_path.exists()
    diff_preview: List[str] = []
    if write_snapshots:
        case.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        case.snapshot_path.write_text(prompt_text, encoding="utf-8")
    elif not snapshot_exists:
        failures.append(f"missing_snapshot={case.snapshot_path}")
    else:
        expected_prompt = normalize_prompt_text(case.snapshot_path.read_text(encoding="utf-8"))
        if expected_prompt != prompt_text:
            failures.append(f"snapshot_mismatch={case.snapshot_path}")
            diff_preview = _snapshot_diff(
                expected_prompt,
                prompt_text,
                snapshot_path=case.snapshot_path,
            )

    return {
        "name": case.name,
        "plan_case": case.plan_case,
        "prompt_type": case.prompt_type,
        "snapshot_path": str(case.snapshot_path),
        "passed": not failures,
        "failures": failures,
        "diff_preview": diff_preview,
        "prompt_length": len(prompt_text),
    }


def run_smoke(
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    *,
    plan_corpus_path: str | Path = DEFAULT_PLAN_CORPUS_PATH,
    write_snapshots: bool = False,
) -> dict:
    plan_case_index = {case.name: case for case in load_plan_cases(plan_corpus_path)}
    results = [
        evaluate_case(case, plan_case_index, write_snapshots=write_snapshots)
        for case in load_snapshot_cases(corpus_path)
    ]
    failures = [item for item in results if not item["passed"]]
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
        "results": results,
        "failures": failures,
        "write_snapshots": write_snapshots,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--plan-corpus", default=str(DEFAULT_PLAN_CORPUS_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write-snapshots", action="store_true")
    args = parser.parse_args()

    report = run_smoke(
        args.corpus,
        plan_corpus_path=args.plan_corpus,
        write_snapshots=args.write_snapshots,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"case_count={report['case_count']} "
            f"passed_count={report['passed_count']} "
            f"write_snapshots={report['write_snapshots']}"
        )
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(
                f"[{status}] {item['name']} "
                f"prompt_type={item['prompt_type']} "
                f"snapshot={item['snapshot_path']}"
            )
            if item["failures"]:
                print(f"  failures={item['failures']}")
            if item["diff_preview"]:
                print("  diff_preview:")
                for line in item["diff_preview"]:
                    print(f"    {line}")

    return 1 if report["failures"] and not report["write_snapshots"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
