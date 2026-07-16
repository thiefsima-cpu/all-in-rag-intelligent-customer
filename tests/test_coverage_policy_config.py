from pathlib import Path

import pytest

from scripts.coverage_policy.models import PackageCoverageRule, RiskModuleCoverageRule
from scripts.coverage_policy.policy import load_policy

VALID_POLICY = """
[tool.graph_rag.coverage.package]
path = "rag_modules"
branch_fail_under = 70

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_policy_returns_explicit_package_and_risk_rules(tmp_path: Path) -> None:
    policy = load_policy(_write(tmp_path, VALID_POLICY))

    assert policy.package == PackageCoverageRule(path="rag_modules", branch_fail_under=70.0)
    assert policy.risk_modules == (
        RiskModuleCoverageRule(
            path="rag_modules/retrieval/fusion.py",
            combined_fail_under=85.0,
            branch_fail_under=80.0,
        ),
    )


@pytest.mark.parametrize(
    "text, message",
    [
        (
            VALID_POLICY.replace('path = "rag_modules"', 'path = "C:/repo/rag_modules"'),
            "relative POSIX",
        ),
        (
            VALID_POLICY.replace('path = "rag_modules"', "path = 'rag_modules\\\\retrieval'"),
            "relative POSIX",
        ),
        (VALID_POLICY.replace("fusion.py", "*.py"), "globs"),
        (VALID_POLICY.replace("fusion.py", "../fusion.py"), "relative POSIX"),
        (VALID_POLICY.replace("branch_fail_under = 70", "branch_fail_under = true"), "numeric"),
        (
            VALID_POLICY.replace("combined_fail_under = 85", "combined_fail_under = 101"),
            "between 0 and 100",
        ),
    ],
)
def test_load_policy_rejects_invalid_paths_and_thresholds(
    tmp_path: Path,
    text: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        load_policy(_write(tmp_path, text))


def test_load_policy_rejects_duplicate_normalized_risk_paths(tmp_path: Path) -> None:
    duplicated = (
        VALID_POLICY
        + """
[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80
"""
    )

    with pytest.raises(ValueError, match="duplicate risk module"):
        load_policy(_write(tmp_path, duplicated))


def test_load_policy_requires_every_section_and_threshold(tmp_path: Path) -> None:
    with pytest.raises((KeyError, ValueError), match="risk_modules"):
        load_policy(
            _write(
                tmp_path,
                "[tool.graph_rag.coverage.package]\npath='rag_modules'\nbranch_fail_under=70\n",
            )
        )
