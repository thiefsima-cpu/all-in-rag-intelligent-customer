from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class DockerApiBuildContextTests(unittest.TestCase):
    def test_dockerfile_copy_sources_exist_in_build_context(self) -> None:
        dockerfile = ROOT / "Dockerfile.api"
        missing_sources: list[str] = []

        for raw_line in dockerfile.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("COPY "):
                continue
            parts = line.split()
            if len(parts) < 3 or parts[1].startswith("--"):
                continue
            for source in parts[1:-1]:
                if not (ROOT / source).exists():
                    missing_sources.append(source)

        self.assertEqual([], missing_sources)

    def test_setuptools_root_modules_exist(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        modules = pyproject["tool"]["setuptools"]["py-modules"]
        missing_modules = [
            module_name for module_name in modules if not (ROOT / f"{module_name}.py").exists()
        ]

        self.assertEqual([], missing_modules)

    def test_dockerignore_root_includes_exist(self) -> None:
        missing_includes: list[str] = []

        for raw_line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line.startswith("!") or any(token in line for token in "*?["):
                continue
            include = line.removeprefix("!").rstrip("/")
            if "/" in include or "\\" in include:
                continue
            if re.fullmatch(r"[A-Za-z0-9_.-]+", include) and not (ROOT / include).exists():
                missing_includes.append(include)

        self.assertEqual([], missing_includes)

    def test_api_service_forwards_model_provider_keys_from_compose_environment(self) -> None:
        compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        api_environment = compose["services"]["api"]["environment"]

        for key_name in ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"):
            with self.subTest(key_name=key_name):
                self.assertIn(key_name, api_environment)
                self.assertEqual(f"${{{key_name}:-}}", api_environment[key_name])


if __name__ == "__main__":
    unittest.main()
