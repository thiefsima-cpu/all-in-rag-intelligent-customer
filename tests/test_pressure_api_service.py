from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts.pressure_api_service import DEFAULT_PRESSURE_SCENARIO, _parse_args, main


class PressureApiServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
