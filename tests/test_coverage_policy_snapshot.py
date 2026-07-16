from pathlib import Path

import pytest

from scripts.coverage_policy.evaluator import evaluate_policy
from scripts.coverage_policy.models import (
    CoverageCounts,
    CoveragePolicy,
    PackageCoverageRule,
    RiskModuleCoverageRule,
)
from scripts.coverage_policy.snapshot import CoverageSnapshot


def _payload(files: dict[str, tuple[int, int, int, int]]) -> dict[str, object]:
    return {
        "files": {
            name: {
                "summary": {
                    "covered_lines": covered_lines,
                    "num_statements": statements,
                    "covered_branches": covered_branches,
                    "num_branches": branches,
                }
            }
            for name, (covered_lines, statements, covered_branches, branches) in files.items()
        }
    }


def _policy() -> CoveragePolicy:
    return CoveragePolicy(
        package=PackageCoverageRule(path="rag_modules", branch_fail_under=70),
        risk_modules=(
            RiskModuleCoverageRule(
                path="rag_modules/retrieval/fusion.py",
                combined_fail_under=85,
                branch_fail_under=80,
            ),
        ),
    )


def test_snapshot_normalizes_report_paths_and_aggregates_package_counts() -> None:
    snapshot = CoverageSnapshot.from_payload(
        _payload(
            {
                ".\\rag_modules\\retrieval\\fusion.py": (39, 40, 8, 10),
                "rag_modules/graph/path_ranker.py": (20, 20, 6, 10),
                "scripts/release_gate.py": (10, 10, 2, 2),
            }
        )
    )

    assert snapshot.file_counts("rag_modules/retrieval/fusion.py").covered_lines == 39
    package = snapshot.package_counts("rag_modules")
    assert (package.covered_branches, package.num_branches) == (14, 20)


def test_evaluation_reports_package_and_both_file_metrics_in_order() -> None:
    snapshot = CoverageSnapshot.from_payload(
        _payload({"rag_modules/retrieval/fusion.py": (39, 40, 8, 10)})
    )

    evaluation = evaluate_policy(_policy(), snapshot)

    assert [result.kind for result in evaluation.results] == ["package", "risk_module"]
    assert evaluation.results[0].passed is True
    assert evaluation.results[1].combined_percent == pytest.approx(94.0)
    assert evaluation.results[1].branch_percent == pytest.approx(80.0)
    assert evaluation.passed is True


def test_evaluation_keeps_all_threshold_failures() -> None:
    snapshot = CoverageSnapshot.from_payload(
        _payload({"rag_modules/retrieval/fusion.py": (10, 40, 2, 10)})
    )

    evaluation = evaluate_policy(_policy(), snapshot)

    assert evaluation.passed is False
    assert [result.passed for result in evaluation.results] == [False, False]


def test_coverage_percentages_handle_arbitrary_precision_counts() -> None:
    huge_count = 10**400
    counts = CoverageCounts(
        covered_lines=huge_count,
        num_statements=huge_count,
        covered_branches=huge_count,
        num_branches=huge_count,
    )

    assert counts.combined_percent == pytest.approx(100.0)
    assert counts.branch_percent == pytest.approx(100.0)


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "files mapping"),
        (
            _payload({"rag_modules/retrieval/fusion.py": (-1, 40, 2, 10)}),
            "non-negative integer",
        ),
        (
            _payload({"rag_modules/retrieval/fusion.py": (41, 40, 2, 10)}),
            "cannot exceed",
        ),
        (
            _payload({"rag_modules/retrieval/fusion.py": (10, 40, 11, 10)}),
            "cannot exceed",
        ),
    ],
)
def test_snapshot_rejects_invalid_reports(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        CoverageSnapshot.from_payload(payload)


def test_snapshot_rejects_duplicate_normalized_report_paths() -> None:
    payload = _payload(
        {
            "./rag_modules/retrieval/fusion.py": (10, 10, 2, 2),
            "rag_modules\\retrieval\\fusion.py": (10, 10, 2, 2),
        }
    )
    with pytest.raises(ValueError, match="duplicate normalized coverage path"):
        CoverageSnapshot.from_payload(payload)


def test_evaluation_rejects_missing_file() -> None:
    snapshot = CoverageSnapshot.from_payload(_payload({"rag_modules/x.py": (1, 1, 1, 1)}))

    with pytest.raises(ValueError, match="missing configured risk file"):
        evaluate_policy(_policy(), snapshot)


def test_evaluation_rejects_absent_branch_data() -> None:
    snapshot = CoverageSnapshot.from_payload(
        _payload(
            {
                "rag_modules/retrieval/fusion.py": (40, 40, 0, 0),
                "rag_modules/covered.py": (1, 1, 1, 1),
            }
        )
    )

    with pytest.raises(ValueError, match="no branch data"):
        evaluate_policy(_policy(), snapshot)


def test_snapshot_loads_from_json(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        '{"files":{"rag_modules/x.py":{"summary":'
        '{"covered_lines":1,"num_statements":1,"covered_branches":1,"num_branches":1}}}}',
        encoding="utf-8",
    )

    snapshot = CoverageSnapshot.from_json(report)

    assert snapshot.file_counts("rag_modules/x.py").covered_lines == 1


def test_snapshot_classifies_recursive_json_parse_failure_as_invalid_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report = tmp_path / "coverage.json"
    report.write_text('{"files": {}}', encoding="utf-8")

    def _raise_recursion(_text: str, **_kwargs: object) -> None:
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr("scripts.coverage_policy.snapshot.json.loads", _raise_recursion)

    with pytest.raises(ValueError, match="coverage report JSON nesting is too deep"):
        CoverageSnapshot.from_json(report)


def test_snapshot_does_not_classify_recursive_file_read_as_invalid_input(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def _raise_recursion(
        _path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        del encoding, errors
        raise RecursionError("unexpected file read recursion")

    monkeypatch.setattr(Path, "read_text", _raise_recursion)

    with pytest.raises(RecursionError, match="unexpected file read recursion"):
        CoverageSnapshot.from_json(tmp_path / "coverage.json")


def test_snapshot_load_rejects_exact_duplicate_json_object_keys(tmp_path: Path) -> None:
    report = tmp_path / "coverage.json"
    report.write_text(
        """
{
  "files": {
    "rag_modules/x.py": {
      "summary": {
        "covered_lines": 1,
        "num_statements": 1,
        "covered_branches": 1,
        "num_branches": 1
      }
    },
    "rag_modules/x.py": {
      "summary": {
        "covered_lines": 0,
        "num_statements": 1,
        "covered_branches": 0,
        "num_branches": 1
      }
    }
  }
}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON object key"):
        CoverageSnapshot.from_json(report)
