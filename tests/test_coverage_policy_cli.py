import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.coverage_policy.cli import main

ROOT_DIR = Path(__file__).resolve().parents[1]


def _config(path: Path) -> Path:
    path.write_text(
        """
[tool.graph_rag.coverage.package]
path = "rag_modules"
branch_fail_under = 70

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80
""",
        encoding="utf-8",
    )
    return path


def _report(path: Path, values: tuple[int, int, int, int]) -> Path:
    covered_lines, statements, covered_branches, branches = values
    path.write_text(
        json.dumps(
            {
                "files": {
                    "rag_modules/retrieval/fusion.py": {
                        "summary": {
                            "covered_lines": covered_lines,
                            "num_statements": statements,
                            "covered_branches": covered_branches,
                            "num_branches": branches,
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_main_returns_zero_and_prints_both_layers(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--config",
            str(_config(tmp_path / "pyproject.toml")),
            "--coverage-json",
            str(_report(tmp_path / "coverage.json", (39, 40, 8, 10))),
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "[PASS] package rag_modules branch 80.00%" in output
    assert "[PASS] risk_module rag_modules/retrieval/fusion.py" in output
    assert "combined 94.00%" in output


def test_main_returns_one_and_prints_every_threshold_failure(tmp_path: Path, capsys) -> None:
    code = main(
        [
            "--config",
            str(_config(tmp_path / "pyproject.toml")),
            "--coverage-json",
            str(_report(tmp_path / "coverage.json", (10, 40, 2, 10))),
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert output.count("[FAIL]") == 2


@pytest.mark.parametrize("missing_path", [False, True])
def test_main_returns_two_for_invalid_or_unreadable_input(
    tmp_path: Path,
    capsys,
    *,
    missing_path: bool,
) -> None:
    config = _config(tmp_path / "pyproject.toml")
    report = tmp_path / "coverage.json"
    if not missing_path:
        report.write_text("not-json", encoding="utf-8")

    assert main(["--config", str(config), "--coverage-json", str(report)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("[ERROR] coverage policy:")


def test_direct_script_entry_point_loads_package_outside_repository(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT_DIR / "scripts" / "check_coverage_policy.py"), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Enforce repository coverage policy." in result.stdout
