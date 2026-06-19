"""Verify that GraphRAG runs from its expected isolated conda environment."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT_ONLY_PACKAGES = frozenset(
    {
        "build",
        "pip",
        "pip-tools",
        "pygments",
        "pyproject-hooks",
        "wheel",
    }
)
_REQUIREMENT_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)\s*(?:\[.*\])?\s*(?:==|~=|>=|<=|>|<|$)")


def _normalized_path(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).resolve(strict=False)))


def _requirement_names(lines: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue
        match = _REQUIREMENT_PATTERN.match(line)
        if match:
            names.add(match.group(1).lower().replace("_", "-"))
    return names


def find_runtime_lock_violations(lock_path: Path) -> list[str]:
    names = _requirement_names(lock_path.read_text(encoding="utf-8").splitlines())
    pyproject_path = REPOSITORY_ROOT / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    dev_dependencies = _requirement_names(
        pyproject["project"]["optional-dependencies"]["dev"]
    )
    return sorted(names.intersection(ENVIRONMENT_ONLY_PACKAGES | dev_dependencies))


def validate_environment(
    *,
    prefix: str,
    base_prefix: str,
    executable: str,
    expected_conda_env: str,
    conda_default_env: str | None = None,
) -> list[str]:
    errors: list[str] = []
    active_conda_env = conda_default_env or Path(prefix).name
    expected_conda_env_active = (
        active_conda_env.lower() == expected_conda_env.lower()
        and Path(prefix).name.lower() == expected_conda_env.lower()
    )
    if (
        _normalized_path(prefix) == _normalized_path(base_prefix)
        and not expected_conda_env_active
    ):
        errors.append(
            "Python is not running inside an isolated virtual environment "
            "or expected conda environment."
        )
    if active_conda_env.lower() != expected_conda_env.lower():
        errors.append(
            f"Active conda environment is {active_conda_env!r}; expected {expected_conda_env!r}."
        )
    environment_root = _normalized_path(prefix)
    executable_path = _normalized_path(executable)
    try:
        executable_is_local = os.path.commonpath([executable_path, environment_root]) == environment_root
    except ValueError:
        executable_is_local = False
    if not executable_is_local:
        errors.append(
            f"Python executable {executable!r} is outside the active virtual environment."
        )
    return errors


def _run_pip_check() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        check=False,
    )
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repository_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--expected-conda-env",
        default="graphrag-c9-dev",
    )
    parser.add_argument(
        "--runtime-lock",
        type=Path,
        default=repository_root / "requirements.txt",
    )
    parser.add_argument("--skip-runtime-lock", action="store_true")
    parser.add_argument("--skip-pip-check", action="store_true")
    args = parser.parse_args()

    errors = validate_environment(
        prefix=sys.prefix,
        base_prefix=sys.base_prefix,
        executable=sys.executable,
        expected_conda_env=args.expected_conda_env,
        conda_default_env=os.environ.get("CONDA_DEFAULT_ENV"),
    )
    if not args.skip_runtime_lock:
        violations = find_runtime_lock_violations(args.runtime_lock)
        if violations:
            errors.append(
                "Runtime lock contains development-only packages: "
                + ", ".join(violations)
            )
    if errors:
        for error in errors:
            print(f"[ERROR] {error}")
        return 1
    if not args.skip_pip_check and _run_pip_check() != 0:
        return 1
    print(f"[OK] Isolated conda environment verified: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
