"""Run the final local engineering and release gate sequence."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TextIO

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STEP_NAMES = ("pre_commit", "encoding_audit", "pytest", "release_gate")


@dataclass(frozen=True)
class GateStep:
    name: str
    command: tuple[str, ...]
    display_command: tuple[str, ...]


@dataclass(frozen=True)
class StepResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float

    @property
    def passed(self) -> bool:
        return self.returncode == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "command": format_command(self.command),
            "returncode": self.returncode,
            "passed": self.passed,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass(frozen=True)
class GateReport:
    results: list[StepResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def failed_step_name(self) -> str | None:
        for result in self.results:
            if not result.passed:
                return result.name
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "failed_step": self.failed_step_name,
            "results": [result.to_dict() for result in self.results],
        }


Runner = Callable[..., Any]


def run_subprocess(
    command: list[str],
    *,
    cwd: Path,
    output_stream: TextIO | None = None,
) -> subprocess.CompletedProcess[Any]:
    if output_stream is None:
        return subprocess.run(command, cwd=cwd)
    return subprocess.run(command, cwd=cwd, stdout=output_stream, stderr=output_stream)


def default_steps(
    *,
    python_executable: str = sys.executable,
    root: Path = ROOT_DIR,
) -> tuple[GateStep, ...]:
    scripts_dir = root / "scripts"
    return (
        GateStep(
            name="pre_commit",
            command=(python_executable, "-m", "pre_commit", "run", "--all-files"),
            display_command=("pre-commit", "run", "--all-files"),
        ),
        GateStep(
            name="encoding_audit",
            command=(python_executable, str(scripts_dir / "check_encoding.py")),
            display_command=("python", "scripts/check_encoding.py"),
        ),
        GateStep(
            name="pytest",
            command=(python_executable, "-m", "pytest", "-q"),
            display_command=("python", "-m", "pytest", "-q"),
        ),
        GateStep(
            name="release_gate",
            command=(python_executable, str(scripts_dir / "release_gate.py")),
            display_command=("python", "scripts/release_gate.py"),
        ),
    )


def format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def _print_progress(stream: TextIO | None, message: str) -> None:
    if stream is not None:
        print(message, file=stream, flush=True)


def run_local_gate(
    *,
    steps: Sequence[GateStep] | None = None,
    runner: Runner = run_subprocess,
    stream: TextIO | None = sys.stdout,
    root: Path = ROOT_DIR,
) -> GateReport:
    active_steps = tuple(default_steps(root=root) if steps is None else steps)
    results: list[StepResult] = []

    for step in active_steps:
        _print_progress(stream, f"[RUN] {step.name}: {format_command(step.display_command)}")
        started = time.perf_counter()
        completed = runner(list(step.command), cwd=root)
        duration = time.perf_counter() - started
        returncode = int(completed.returncode)
        result = StepResult(
            name=step.name,
            command=step.display_command,
            returncode=returncode,
            duration_seconds=duration,
        )
        results.append(result)

        status = "PASS" if result.passed else "FAIL"
        _print_progress(
            stream,
            f"[{status}] {step.name} exit_code={returncode} duration={duration:.2f}s",
        )
        if not result.passed:
            break

    return GateReport(results=results)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Run the final local gate: pre-commit, encoding audit, pytest, release gate."
    )
    parser.add_argument("--json", action="store_true", help="Emit a machine-readable summary.")
    args = parser.parse_args()

    progress_stream = sys.stderr if args.json else sys.stdout
    if args.json:

        def runner(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[Any]:
            return run_subprocess(command, cwd=cwd, output_stream=progress_stream)

    else:
        runner = run_subprocess

    report = run_local_gate(stream=progress_stream, runner=runner)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif report.passed:
        print("[PASS] final local gate")
    else:
        print(f"[FAIL] final local gate stopped at {report.failed_step_name}")

    if report.passed:
        return 0
    failed = next((result for result in report.results if not result.passed), None)
    return failed.returncode if failed is not None and failed.returncode else 1


if __name__ == "__main__":
    raise SystemExit(main())
