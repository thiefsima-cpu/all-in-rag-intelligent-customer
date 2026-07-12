from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.check_branch_coverage import (
    BranchCoverageResult,
    calculate_branch_coverage,
    load_threshold,
    main,
)


def _payload(files: dict[str, tuple[int, int]]) -> dict[str, object]:
    return {
        "files": {
            name: {
                "summary": {
                    "covered_branches": covered,
                    "num_branches": total,
                }
            }
            for name, (covered, total) in files.items()
        }
    }


def test_calculate_branch_coverage_accepts_windows_and_posix_paths() -> None:
    result = calculate_branch_coverage(
        _payload(
            {
                "rag_modules\\graph\\path_ranker.py": (7, 10),
                "rag_modules/retrieval/parent_doc_enricher.py": (14, 20),
                "scripts/release_gate.py": (100, 100),
            }
        ),
        package="rag_modules",
    )

    assert result == BranchCoverageResult(covered_branches=21, num_branches=30)
    assert result.percent == pytest.approx(70.0)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "files"),
        ({"files": {}}, "matching files"),
        (_payload({"rag_modules/model.py": (0, 0)}), "branch data"),
        (
            {"files": {"rag_modules/model.py": {"summary": {"covered_branches": "1"}}}},
            "num_branches",
        ),
    ],
)
def test_calculate_branch_coverage_rejects_incomplete_reports(
    payload: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        calculate_branch_coverage(payload, package="rag_modules")


def test_load_threshold_reads_project_policy(tmp_path: Path) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text(
        "[tool.graph_rag.coverage]\nrag_modules_branch_fail_under = 70\n",
        encoding="utf-8",
    )

    assert load_threshold(config) == 70.0


def test_main_returns_pass_fail_and_input_error_codes(tmp_path: Path, capsys) -> None:
    config = tmp_path / "pyproject.toml"
    config.write_text(
        "[tool.graph_rag.coverage]\nrag_modules_branch_fail_under = 70\n",
        encoding="utf-8",
    )
    report = tmp_path / "coverage.json"
    report.write_text(
        json.dumps(_payload({"rag_modules/module.py": (7, 10)})),
        encoding="utf-8",
    )

    common = ["--coverage-json", str(report), "--config", str(config)]
    assert main(common) == 0
    assert "70.00%" in capsys.readouterr().out

    report.write_text(
        json.dumps(_payload({"rag_modules/module.py": (6, 10)})),
        encoding="utf-8",
    )
    assert main(common) == 1
    assert "FAIL" in capsys.readouterr().out

    report.write_text("not-json", encoding="utf-8")
    assert main(common) == 2
    assert "ERROR" in capsys.readouterr().err
