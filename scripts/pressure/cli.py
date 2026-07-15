from __future__ import annotations

import argparse
from collections.abc import Sequence

from .reporter import print_human_report, print_json_report
from .runner import run_pressure_test
from .scenario import DEFAULT_PRESSURE_SCENARIO


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = DEFAULT_PRESSURE_SCENARIO
    parser = argparse.ArgumentParser(
        description=(
            "Local pressure test for GraphRAGServingApiService concurrency and trace backpressure."
        )
    )
    parser.add_argument("--requests", type=int, default=defaults.requests)
    parser.add_argument("--workers", type=int, default=defaults.workers)
    parser.add_argument("--answer-delay-ms", type=float, default=defaults.answer_delay_ms)
    parser.add_argument("--trace-delay-ms", type=float, default=defaults.trace_delay_ms)
    parser.add_argument("--trace-queue-size", type=int, default=defaults.trace_queue_size)
    parser.add_argument("--scenario-name", default=defaults.name)
    parser.add_argument(
        "--max-concurrent-answers",
        type=int,
        default=defaults.max_concurrent_answers,
    )
    parser.add_argument(
        "--answer-acquire-timeout-seconds",
        type=float,
        default=defaults.answer_acquire_timeout_seconds,
    )
    parser.add_argument(
        "--stream-executor-max-workers",
        type=int,
        default=defaults.stream_executor_max_workers,
    )
    parser.add_argument(
        "--stream-executor-max-outstanding",
        type=int,
        default=defaults.stream_executor_max_outstanding,
    )
    parser.add_argument(
        "--stream-event-queue-max-size",
        type=int,
        default=defaults.stream_event_queue_max_size,
    )
    parser.add_argument(
        "--synthetic-model-latency-ms",
        type=float,
        default=defaults.synthetic_model_latency_ms,
    )
    parser.add_argument(
        "--synthetic-input-tokens-per-request",
        type=int,
        default=defaults.synthetic_input_tokens_per_request,
    )
    parser.add_argument(
        "--synthetic-output-tokens-per-request",
        type=int,
        default=defaults.synthetic_output_tokens_per_request,
    )
    parser.add_argument(
        "--input-cost-per-million-tokens",
        type=float,
        default=defaults.input_cost_per_million_tokens,
    )
    parser.add_argument(
        "--output-cost-per-million-tokens",
        type=float,
        default=defaults.output_cost_per_million_tokens,
    )
    parser.add_argument(
        "--retrieval-degraded-every",
        type=int,
        default=defaults.retrieval_degraded_every,
    )
    parser.add_argument(
        "--retrieval-degraded-source",
        default=defaults.retrieval_degraded_source,
    )
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_pressure_test(
        scenario_name=args.scenario_name,
        requests=args.requests,
        workers=args.workers,
        answer_delay_ms=args.answer_delay_ms,
        trace_delay_ms=args.trace_delay_ms,
        trace_queue_size=args.trace_queue_size,
        max_concurrent_answers=args.max_concurrent_answers,
        answer_acquire_timeout_seconds=args.answer_acquire_timeout_seconds,
        stream_executor_max_workers=args.stream_executor_max_workers,
        stream_executor_max_outstanding=args.stream_executor_max_outstanding,
        stream_event_queue_max_size=args.stream_event_queue_max_size,
        synthetic_model_latency_ms=args.synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=args.synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=args.synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=args.input_cost_per_million_tokens,
        output_cost_per_million_tokens=args.output_cost_per_million_tokens,
        retrieval_degraded_every=args.retrieval_degraded_every,
        retrieval_degraded_source=args.retrieval_degraded_source,
    )
    if args.json:
        print_json_report(report)
    else:
        print_human_report(report)
    return report.exit_code
