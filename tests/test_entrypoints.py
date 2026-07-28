from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import main
import main_build_service
import main_build_worker

ROOT = Path(__file__).resolve().parents[1]


class _ReconfigurableStream:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(dict(kwargs))


class EntrypointTests(unittest.TestCase):
    def test_runtime_entrypoints_include_api_and_build_worker(self) -> None:
        self.assertEqual(
            {path.name for path in ROOT.glob("main*.py")},
            {"main.py", "main_build_service.py", "main_build_worker.py"},
        )

    def test_console_runtime_configures_stdout_and_stderr_as_utf8(self) -> None:
        from rag_modules.interfaces.console_runtime import configure_utf8_stdio

        stdout = _ReconfigurableStream()
        stderr = _ReconfigurableStream()

        configure_utf8_stdio(stdout=stdout, stderr=stderr)

        self.assertEqual(stdout.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])
        self.assertEqual(stderr.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])

    def test_serving_entrypoint_returns_nonzero_when_uvicorn_fails(self) -> None:
        with patch("uvicorn.run", side_effect=RuntimeError("boom")):
            exit_code = main.main()

        self.assertEqual(exit_code, 1)

    def test_build_entrypoint_returns_nonzero_when_uvicorn_fails(self) -> None:
        with patch("uvicorn.run", side_effect=RuntimeError("boom")):
            exit_code = main_build_service.main()

        self.assertEqual(exit_code, 1)

    def test_build_worker_entrypoint_returns_nonzero_when_worker_fails(self) -> None:
        with patch("main_build_worker.run_build_job_worker", side_effect=RuntimeError("boom")):
            exit_code = main_build_worker.main()

        self.assertEqual(exit_code, 1)

    def test_build_entrypoint_import_does_not_construct_build_app(self) -> None:
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                with patch("rag_modules.interfaces.api.create_build_api_app") as create_mock:
                    importlib.reload(main_build_service)

                create_mock.assert_not_called()
                self.assertFalse((Path(temp_dir) / "storage").exists())
            finally:
                os.chdir(previous_cwd)
                importlib.reload(main_build_service)

    def test_integration_gate_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-integration-gate"],
            "scripts.integration_gate.cli:main",
        )

    def test_live_quality_gate_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-live-quality-gate"],
            "scripts.live_quality_gate.cli:main",
        )

    def test_release_evidence_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-release-evidence"],
            "scripts.release_evidence.cli:main",
        )

    def test_build_worker_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-build-worker"],
            "main_build_worker:main",
        )

    def test_build_job_database_console_script_is_registered(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        self.assertEqual(
            pyproject["project"]["scripts"]["graph-rag-build-job-db"],
            "scripts.build_job_db:main",
        )

    def test_build_job_database_help_exposes_operator_commands(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.build_job_db", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("status", completed.stdout)
        self.assertIn("migrate", completed.stdout)
        self.assertIn("import-file", completed.stdout)

        import_help = subprocess.run(
            [sys.executable, "-m", "scripts.build_job_db", "import-file", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(import_help.returncode, 0, import_help.stderr)
        self.assertIn("--source", import_help.stdout)
        self.assertIn("--dry-run", import_help.stdout)
        self.assertIn("--json", import_help.stdout)

    def test_build_job_operator_workflow_is_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        release_process = (ROOT / "docs" / "release_process.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        composition = (ROOT / "docs" / "app_composition_maintenance_guide.md").read_text(
            encoding="utf-8"
        )
        combined = "\n".join((readme, release_process, architecture, composition)).lower()

        for command in (
            "graph-rag-build-job-db status",
            "graph-rag-build-job-db migrate",
            "graph-rag-build-job-db import-file --source storage/indexes/build_jobs.json --dry-run",
        ):
            self.assertIn(command, readme)
            self.assertIn(command, release_process)

        for required_contract in (
            "runtime startup never migrates or imports",
            "stop the build api and every build worker before switching the backend",
            "no automatic fallback",
            "90-day audit retention",
            "development-only",
            "exit code `0`",
            "exit code `1`",
        ):
            self.assertIn(required_contract, combined)

    def test_integration_gate_module_help_exposes_command_arguments(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.integration_gate", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--policy", completed.stdout)
        self.assertIn("--output-dir", completed.stdout)
        self.assertIn("--json", completed.stdout)

    def test_live_quality_gate_module_help_exposes_command_arguments(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.live_quality_gate", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--policy", completed.stdout)
        self.assertIn("--output-dir", completed.stdout)
        self.assertIn("--json", completed.stdout)
        self.assertIn("--deterministic-only", completed.stdout)

    def test_release_evidence_module_help_exposes_subcommands(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "scripts.release_evidence", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("capture", completed.stdout)
        self.assertIn("finalize", completed.stdout)
        self.assertIn("verify", completed.stdout)


if __name__ == "__main__":
    unittest.main()
