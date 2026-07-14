from __future__ import annotations

import tempfile
import tomllib
import unittest
from pathlib import Path


def _requirement_names(entries: list[str]) -> set[str]:
    names: set[str] = set()
    for entry in entries:
        name = entry.split(";", 1)[0].strip()
        name = name.split("[", 1)[0]
        for separator in ("==", "~=", ">=", "<=", "!=", ">", "<"):
            if separator in name:
                name = name.split(separator, 1)[0]
                break
        names.add(name.strip().lower().replace("_", "-"))
    return names


def _pinned_requirement_version(entries: list[str], package_name: str) -> str:
    expected_name = package_name.lower().replace("_", "-")
    for entry in entries:
        requirement = entry.split(";", 1)[0].strip()
        if "==" not in requirement:
            continue
        name, version = requirement.split("==", 1)
        normalized_name = name.split("[", 1)[0].strip().lower().replace("_", "-")
        if normalized_name == expected_name:
            return version.strip()
    raise AssertionError(f"{package_name} must be declared with an exact == pin")


class DependencyIsolationTests(unittest.TestCase):
    def test_runtime_lock_rejects_development_only_packages(self) -> None:
        from scripts.verify_environment import find_runtime_lock_violations

        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "requirements.txt"
            lock_path.write_text(
                "fastapi==1.0\npytest==9.0\nruff==0.15\nmypy==2.1\npre-commit==4.6\n"
                "pip-tools==7.5\npip==26.1\nsetuptools==80.9\nwheel==0.47\n"
                "build==1.5\npyproject-hooks==1.2\npygments==2.20\n",
                encoding="utf-8",
            )

            violations = find_runtime_lock_violations(lock_path)

        self.assertEqual(
            violations,
            [
                "build",
                "mypy",
                "pip",
                "pip-tools",
                "pre-commit",
                "pygments",
                "pyproject-hooks",
                "pytest",
                "ruff",
                "wheel",
            ],
        )

    def test_pyproject_is_dependency_source_of_truth(self) -> None:
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]

        runtime_names = _requirement_names(project["dependencies"])
        dev_names = _requirement_names(project["optional-dependencies"]["dev"])

        self.assertTrue(
            {
                "fastapi",
                "jieba-py",
                "langchain-core",
                "neo4j",
                "numpy",
                "openai",
                "opentelemetry-exporter-otlp-proto-http",
                "opentelemetry-sdk",
                "prometheus-client",
                "pydantic",
                "pymilvus",
                "python-dotenv",
                "rank-bm25",
                "requests",
                "uvicorn",
            }.issubset(runtime_names)
        )
        self.assertTrue({"mypy", "pip-tools", "pre-commit", "pytest", "ruff"}.issubset(dev_names))
        self.assertTrue(
            runtime_names.isdisjoint({"mypy", "pip-tools", "pre-commit", "pytest", "ruff"})
        )

    def test_development_lock_includes_httpx2_for_starlette_testclient(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        dev_names = _requirement_names(pyproject["project"]["optional-dependencies"]["dev"])

        runtime_lock = (root / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (root / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertIn("httpx2", dev_names)
        self.assertNotIn("httpx2==", runtime_lock)
        self.assertIn("httpx2==2.5.0", dev_lock)

    def test_runtime_lock_uses_maintained_jieba_distribution(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_names = _requirement_names(pyproject["project"]["dependencies"])
        runtime_lock = (root / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (root / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertIn("jieba-py", runtime_names)
        self.assertNotIn("jieba", runtime_names)
        self.assertIn("jieba-py==0.46.12", runtime_lock)
        self.assertIn("jieba-py==0.46.12", dev_lock)
        self.assertNotIn("jieba==0.42.1", runtime_lock)
        self.assertNotIn("jieba==0.42.1", dev_lock)

    def test_langchain_core_uses_patched_version_in_source_and_locks(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = pyproject["project"]["dependencies"]
        runtime_lock = (root / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (root / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertEqual(
            _pinned_requirement_version(runtime_dependencies, "langchain-core"),
            "1.3.3",
        )
        self.assertIn("langchain-core==1.3.3", runtime_lock)
        self.assertIn("langchain-core==1.3.3", dev_lock)

    def test_setuptools_uses_patched_version_across_build_and_install_paths(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        build_requirements = pyproject["build-system"]["requires"]
        bootstrap = (root / "scripts" / "bootstrap_env.ps1").read_text(encoding="utf-8")
        runtime_lock = (root / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (root / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertIn("setuptools>=83.0.0", build_requirements)
        self.assertIn('"setuptools==83.0.0"', bootstrap)
        self.assertIn("setuptools==83.0.0", runtime_lock)
        self.assertIn("setuptools==83.0.0", dev_lock)

    def test_current_runtime_lock_contains_no_development_only_packages(self) -> None:
        from scripts.verify_environment import find_runtime_lock_violations

        lock_path = Path(__file__).resolve().parents[1] / "requirements.txt"

        self.assertEqual(find_runtime_lock_violations(lock_path), [])

    def test_lock_compiler_script_regenerates_runtime_and_development_locks(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "compile_locks.ps1"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn("pyproject.toml", script)
        self.assertIn("requirements.txt", script)
        self.assertIn("requirements-dev.txt", script)
        self.assertIn("piptools", script)
        self.assertIn("--extra=dev", script)
        self.assertIn("--strip-extras", script)
        self.assertIn("--allow-unsafe", script)
        self.assertIn("--pip-args", script)
        self.assertIn("UpgradePackage", script)
        self.assertIn("--upgrade-package", script)
        self.assertIn("3.11", script)

        try:
            script_path.read_bytes().decode("ascii")
        except UnicodeDecodeError as exc:
            self.fail(f"compile_locks.ps1 should stay ASCII-only for Windows PowerShell: {exc}")

    def test_installer_pip_pins_match_pyproject_development_tool_pin(self) -> None:
        root = Path(__file__).resolve().parents[1]
        pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        pip_version = _pinned_requirement_version(
            pyproject["project"]["optional-dependencies"]["dev"],
            "pip",
        )

        for relative_path in ("Dockerfile.api", "scripts/bootstrap_env.ps1"):
            with self.subTest(path=relative_path):
                content = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn(f"pip=={pip_version}", content)

    def test_dependency_docs_point_to_lock_compiler_script(self) -> None:
        root = Path(__file__).resolve().parents[1]

        for relative_path in (
            "README.md",
            "AGENTS.md",
            "docs/dependency_management.md",
            "docs/release_process.md",
        ):
            with self.subTest(path=relative_path):
                content = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn(".\\scripts\\compile_locks.ps1", content)

    def test_environment_verifier_rejects_global_interpreter(self) -> None:
        from scripts.verify_environment import validate_environment

        errors = validate_environment(
            prefix="C:/Python311",
            base_prefix="C:/Python311",
            executable="C:/Python311/python.exe",
            expected_conda_env="graphrag-c9-dev",
            conda_default_env="base",
        )

        self.assertTrue(any("virtual environment" in error for error in errors))

    def test_environment_verifier_accepts_expected_conda_environment(self) -> None:
        from scripts.verify_environment import validate_environment

        expected = Path("C:/Users/dev/miniconda3/envs/graphrag-c9-dev")
        errors = validate_environment(
            prefix=str(expected),
            base_prefix="C:/Users/dev/miniconda3",
            executable=str(expected / "python.exe"),
            expected_conda_env="graphrag-c9-dev",
            conda_default_env="graphrag-c9-dev",
        )

        self.assertEqual(errors, [])

    def test_environment_verifier_accepts_conda_environment_with_matching_base_prefix(
        self,
    ) -> None:
        from scripts.verify_environment import validate_environment

        expected = Path("C:/Users/dev/miniconda3/envs/graphrag-c9-dev")
        errors = validate_environment(
            prefix=str(expected),
            base_prefix=str(expected),
            executable=str(expected / "python.exe"),
            expected_conda_env="graphrag-c9-dev",
            conda_default_env="graphrag-c9-dev",
        )

        self.assertEqual(errors, [])

    def test_environment_verifier_rejects_wrong_conda_environment(self) -> None:
        from scripts.verify_environment import validate_environment

        active = Path("C:/Users/dev/miniconda3/envs/other-project")
        errors = validate_environment(
            prefix=str(active),
            base_prefix="C:/Users/dev/miniconda3",
            executable=str(active / "python.exe"),
            expected_conda_env="graphrag-c9-dev",
            conda_default_env="other-project",
        )

        self.assertTrue(
            any("graphrag-c9-dev" in error and "other-project" in error for error in errors)
        )

    def test_bootstrap_uses_named_conda_environments(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_env.ps1"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn("graphrag-c9-dev", script)
        self.assertIn("graphrag-c9-runtime", script)
        self.assertIn("graphrag-c9-agent", script)
        self.assertIn('"create" "--yes" "--name"', script)
        self.assertIn('"run" "--name"', script)
        self.assertIn("--expected-conda-env", script)
        self.assertNotIn('"-m" "venv"', script)

    def test_bootstrap_removes_obsolete_jieba_distribution(self) -> None:
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_env.ps1"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('if ($Profile -ne "agent")', script)
        self.assertIn('"uninstall" "--yes" "jieba"', script)

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
