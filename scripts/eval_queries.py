"""Command-line entry point for curated quality evaluation queries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.eval_cases import (
    DEFAULT_CORPUS_PATH,
    EvalCase,
    EvalExpectation,
    EvalResponseMode,
    OfflineEvalFixture,
    OfflineEvidenceFixture,
    load_eval_cases,
)
from scripts.eval_reporting import (
    AdvancedGraphRAGSystem,
    _write_eval_report,
    build_eval_report,
    evaluate_case,
    evaluate_offline_quality_queries,
    evaluate_queries,
    load_config,
)
from scripts.eval_scoring import (
    EvalObservation,
    build_offline_eval_observation,
    calculate_eval_metrics,
    evaluate_offline_quality_case,
    score_eval_observation,
)


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
    report = evaluate_queries(
        top_k=top_k,
        generate=generate,
        corpus_path=corpus_path,
        profile=profile,
        profile_path=profile_path,
    )
    results = report["results"]
    failures = report["failures"]
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
                f"entities={item['retrieval']['entity_names'][:5]}"
            )
            print(
                f"  latency_ms={item['runtime']['latency_ms']:.1f} "
                f"plan_used_cache={item['runtime']['plan_used_cache']}"
            )
            print(f"  category={item['category']} failures={item['failures']}")
            print(f"  evidence={item['retrieval']['evidence'][:3]}")
            if item["retrieval"]["missing_entity_names"]:
                print(f"  missing={item['retrieval']['missing_entity_names']}")
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
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Also generate answers and check expected answer terms.",
    )
    parser.add_argument(
        "--corpus",
        default=str(DEFAULT_CORPUS_PATH),
        help="Path to the curated eval corpus JSON file.",
    )
    parser.add_argument(
        "--profile", default=None, help="Configuration profile name from the profiles directory."
    )
    parser.add_argument("--profile-path", default=None, help="Explicit TOML profile path.")
    parser.add_argument(
        "--output-dir", default=None, help="Optional directory for report.json and summary.md."
    )
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


__all__ = [
    "AdvancedGraphRAGSystem",
    "DEFAULT_CORPUS_PATH",
    "EvalCase",
    "EvalExpectation",
    "EvalObservation",
    "EvalResponseMode",
    "OfflineEvalFixture",
    "OfflineEvidenceFixture",
    "build_eval_report",
    "build_offline_eval_observation",
    "calculate_eval_metrics",
    "evaluate_case",
    "evaluate_offline_quality_case",
    "evaluate_offline_quality_queries",
    "evaluate_queries",
    "load_config",
    "load_eval_cases",
    "main",
    "run_eval",
    "score_eval_observation",
]


if __name__ == "__main__":
    raise SystemExit(main())
