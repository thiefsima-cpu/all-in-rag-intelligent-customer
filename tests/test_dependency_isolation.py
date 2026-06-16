from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class DependencyIsolationTests(unittest.TestCase):
    def test_runtime_lock_rejects_development_only_packages(self) -> None:
        from scripts.verify_environment import find_runtime_lock_violations

        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "requirements.txt"
            lock_path.write_text(
                "fastapi==1.0\npytest==9.0\npip-tools==7.5\n",
                encoding="utf-8",
            )

            violations = find_runtime_lock_violations(lock_path)

        self.assertEqual(violations, ["pip-tools", "pytest"])

    def test_environment_verifier_rejects_global_interpreter(self) -> None:
        from scripts.verify_environment import validate_environment

        errors = validate_environment(
            prefix="C:/Python311",
            base_prefix="C:/Python311",
            executable="C:/Python311/python.exe",
            expected_venv=Path("E:/repo/.venv"),
        )

        self.assertTrue(any("virtual environment" in error for error in errors))

    def test_environment_verifier_accepts_repository_venv(self) -> None:
        from scripts.verify_environment import validate_environment

        expected = Path("E:/repo/.venv")
        errors = validate_environment(
            prefix=str(expected),
            base_prefix="C:/Python311",
            executable=str(expected / "Scripts" / "python.exe"),
            expected_venv=expected,
        )

        self.assertEqual(errors, [])

    def test_bootstrap_agent_path_is_windows_powershell_safe(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_env.ps1"

        try:
            script_path.read_bytes().decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(
                "bootstrap_env.ps1 should keep path logic ASCII-only so Windows "
                "PowerShell 5.1 cannot mojibake the legacy agent directory name: "
                f"{exc}"
            )


if __name__ == "__main__":
    unittest.main()
