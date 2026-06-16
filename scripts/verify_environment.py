"""Verify that GraphRAG runs from its repository-local virtual environment."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

DEVELOPMENT_ONLY_PACKAGES = frozenset(
    {
        "build",
        "pip-tools",
        "pytest",
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
    return sorted(names.intersection(DEVELOPMENT_ONLY_PACKAGES))


def validate_environment(
    *,
    prefix: str,
    base_prefix: str,
    executable: str,
    expected_venv: Path,
) -> list[str]:
    errors: list[str] = []
    if _normalized_path(prefix) == _normalized_path(base_prefix):
        errors.append("Python is not running inside a virtual environment.")
    expected = _normalized_path(expected_venv)
    if _normalized_path(prefix) != expected:
        errors.append(
            f"Active virtual environment is {prefix!r}; expected repository environment {str(expected_venv)!r}."
        )
    executable_path = _normalized_path(executable)
    try:
        executable_is_local = os.path.commonpath([executable_path, expected]) == expected
    except ValueError:
        executable_is_local = False
    if not executable_is_local:
        errors.append(
            f"Python executable {executable!r} is outside the repository virtual environment."
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
        "--expected-venv",
        type=Path,
        default=repository_root / ".venv",
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
        expected_venv=args.expected_venv,
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
    print(f"[OK] Isolated environment verified: {sys.executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
