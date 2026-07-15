from __future__ import annotations

import importlib
import io
import json
import subprocess
import sys
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.pressure.cli import _parse_args, main
from scripts.pressure.scenario import DEFAULT_PRESSURE_SCENARIO


class PressureCliTests(unittest.TestCase):
    def test_cli_parser_reads_defaults_from_canonical_scenario(self) -> None:
        args = _parse_args([])

        self.assertEqual(args.scenario_name, DEFAULT_PRESSURE_SCENARIO.name)
        self.assertEqual(args.requests, DEFAULT_PRESSURE_SCENARIO.requests)
        self.assertEqual(args.workers, DEFAULT_PRESSURE_SCENARIO.workers)
        self.assertEqual(args.answer_delay_ms, DEFAULT_PRESSURE_SCENARIO.answer_delay_ms)
        self.assertEqual(args.trace_delay_ms, DEFAULT_PRESSURE_SCENARIO.trace_delay_ms)
        self.assertEqual(args.trace_queue_size, DEFAULT_PRESSURE_SCENARIO.trace_queue_size)
        self.assertEqual(
            args.max_concurrent_answers,
            DEFAULT_PRESSURE_SCENARIO.max_concurrent_answers,
        )
        self.assertEqual(
            args.answer_acquire_timeout_seconds,
            DEFAULT_PRESSURE_SCENARIO.answer_acquire_timeout_seconds,
        )
        self.assertEqual(
            args.stream_executor_max_workers,
            DEFAULT_PRESSURE_SCENARIO.stream_executor_max_workers,
        )
        self.assertEqual(
            args.stream_executor_max_outstanding,
            DEFAULT_PRESSURE_SCENARIO.stream_executor_max_outstanding,
        )
        self.assertEqual(
            args.stream_event_queue_max_size,
            DEFAULT_PRESSURE_SCENARIO.stream_event_queue_max_size,
        )

    def test_cli_parser_accepts_explicit_stream_capacity(self) -> None:
        args = _parse_args(
            [
                "--stream-executor-max-workers",
                "1",
                "--stream-executor-max-outstanding",
                "2",
                "--stream-event-queue-max-size",
                "4",
            ]
        )

        self.assertEqual(args.stream_executor_max_workers, 1)
        self.assertEqual(args.stream_executor_max_outstanding, 2)
        self.assertEqual(args.stream_event_queue_max_size, 4)

    def test_main_returns_one_and_preserves_json_for_failed_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--json",
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                    "--synthetic-model-latency-ms",
                    "1001",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "fail")

    def test_main_returns_zero_after_human_pass_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: pass", output.getvalue())

    def test_script_process_exits_one_and_emits_failed_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts" / "pressure_api_service.py"),
                "--json",
                "--scenario-name",
                "model_call_budget",
                "--requests",
                "1",
                "--workers",
                "1",
                "--answer-delay-ms",
                "0",
                "--trace-delay-ms",
                "0",
                "--synthetic-model-latency-ms",
                "1001",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "fail")

    def test_console_entrypoint_targets_canonical_cli(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        payload = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(
            payload["project"]["scripts"]["graph-rag-pressure"],
            "scripts.pressure.cli:main",
        )

    def test_legacy_script_does_not_export_pressure_business_symbols(self) -> None:
        module = importlib.import_module("scripts.pressure_api_service")
        retired = {
            "PressureScenario",
            "PressureMetrics",
            "PressureThresholds",
            "PressureReport",
            "build_pressure_report",
            "default_pressure_scenario",
            "default_pressure_thresholds",
            "run_pressure_test",
        }
        self.assertEqual({name for name in retired if hasattr(module, name)}, set())

    def test_pressure_package_root_has_no_aggregate_exports(self) -> None:
        module = importlib.import_module("scripts.pressure")
        self.assertEqual(getattr(module, "__all__", None), None)
        self.assertFalse(hasattr(module, "PressureScenario"))


if __name__ == "__main__":
    unittest.main()
