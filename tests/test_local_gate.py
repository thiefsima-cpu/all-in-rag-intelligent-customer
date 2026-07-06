from __future__ import annotations

import io
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.local_gate import (
    DEFAULT_STEP_NAMES,
    StepResult,
    default_steps,
    main,
    run_local_gate,
    run_subprocess,
)

ROOT = Path(__file__).resolve().parents[1]


class LocalGateTests(unittest.TestCase):
    def test_default_steps_chain_engineering_checks_before_release_gate(self) -> None:
        steps = default_steps(python_executable="python")

        self.assertEqual(tuple(step.name for step in steps), DEFAULT_STEP_NAMES)
        self.assertEqual(
            [step.display_command for step in steps],
            [
                ("pre-commit", "run", "--all-files"),
                ("python", "scripts/check_encoding.py"),
                ("python", "-m", "pytest", "-q"),
                ("python", "scripts/release_gate.py"),
            ],
        )

    def test_run_local_gate_stops_at_first_failed_step(self) -> None:
        calls: list[tuple[str, ...]] = []

        def runner(command: list[str], *, cwd: Path) -> SimpleNamespace:
            calls.append(tuple(command))
            return SimpleNamespace(returncode=1 if len(calls) == 2 else 0)

        report = run_local_gate(
            steps=default_steps(python_executable="python"),
            runner=runner,
            stream=io.StringIO(),
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            [result.name for result in report.results], ["pre_commit", "encoding_audit"]
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(report.failed_step_name, "encoding_audit")

    def test_report_dict_is_stable_for_json_output(self) -> None:
        report = run_local_gate(
            steps=default_steps(python_executable="python")[:1],
            runner=lambda command, *, cwd: SimpleNamespace(returncode=0),
            stream=io.StringIO(),
        )

        payload = report.to_dict()

        self.assertEqual(payload["passed"], True)
        self.assertEqual(payload["failed_step"], None)
        self.assertEqual(payload["results"][0]["name"], "pre_commit")
        self.assertEqual(payload["results"][0]["returncode"], 0)
        self.assertEqual(payload["results"][0]["command"], "pre-commit run --all-files")

    def test_main_emits_json_and_returns_failed_step_code(self) -> None:
        report = SimpleNamespace(
            passed=False,
            results=[
                StepResult(
                    name="pre_commit",
                    command=("pre-commit", "run", "--all-files"),
                    returncode=7,
                    duration_seconds=0.01,
                )
            ],
            failed_step_name="pre_commit",
            to_dict=lambda: {
                "passed": False,
                "failed_step": "pre_commit",
                "results": [
                    {
                        "name": "pre_commit",
                        "command": "pre-commit run --all-files",
                        "returncode": 7,
                        "passed": False,
                        "duration_seconds": 0.01,
                    }
                ],
            },
        )

        output = io.StringIO()
        with (
            patch.object(sys, "argv", ["local_gate.py", "--json"]),
            patch("scripts.local_gate.run_local_gate", return_value=report),
            patch("sys.stdout", output),
        ):
            exit_code = main()

        self.assertEqual(exit_code, 7)
        self.assertEqual(json.loads(output.getvalue())["failed_step"], "pre_commit")

    def test_run_subprocess_redirects_child_output_when_stream_is_provided(self) -> None:
        stream = io.StringIO()

        with patch(
            "scripts.local_gate.subprocess.run",
            return_value=SimpleNamespace(returncode=0),
        ) as run:
            run_subprocess(["python", "--version"], cwd=ROOT, output_stream=stream)

        self.assertIs(run.call_args.kwargs["stdout"], stream)
        self.assertIs(run.call_args.kwargs["stderr"], stream)

    def test_console_entrypoint_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-local-gate"],
            "scripts.local_gate:main",
        )

    def test_default_steps_keep_release_gate_display_command_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            steps = default_steps(python_executable="python", root=root)

        self.assertEqual(steps[-1].display_command, ("python", "scripts/release_gate.py"))


if __name__ == "__main__":
    unittest.main()
