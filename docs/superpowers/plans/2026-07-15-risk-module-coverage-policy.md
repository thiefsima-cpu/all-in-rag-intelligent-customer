# Risk-Module Coverage Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the package-only branch checker with a strict coverage-policy engine and raise nine critical files to at least 85% combined coverage and 80% branch coverage through meaningful risk-path tests.

**Architecture:** Add a focused `scripts.coverage_policy` package that strictly parses TOML, normalizes coverage.py JSON, evaluates package and exact-file rules, and exposes a thin CLI. Keep the new engine dormant while risk tests are added, then atomically replace the old checker and configuration after a fresh full-suite report proves every rule passes.

**Tech Stack:** Python 3.11, pytest 9, pytest-cov/coverage.py JSON, standard-library `dataclasses`, `json`, `tomllib`, `pathlib`, `argparse`, Ruff, mypy, GitHub Actions.

## Global Constraints

- Python remains `>=3.11,<3.12`.
- Do not add runtime or development dependencies or edit generated requirements lock files.
- Keep coverage.py's repository-wide combined threshold at exactly 75%.
- Keep `rag_modules` package branch coverage at exactly 70%.
- Every configured risk file must enforce combined coverage at exactly 85% and branch coverage at exactly 80%.
- Risk-file rules use exact repository-relative POSIX paths; globs, absolute paths, `..`, duplicate normalized paths, missing files, and files without branch data are invalid.
- Exit code `0` means all rules pass, `1` means valid inputs with threshold failures, and `2` means invalid or unreadable policy/report input.
- Do not retain the old checker name, old scalar configuration key, or old `branch_coverage` local-gate step after activation.
- Do not connect to live Milvus or Neo4j services or start Docker.
- Preserve public RAG APIs; the file-lock refactor may change private internals only.
- Do not commit `coverage.json`, `.coverage`, pytest temporary directories, or evaluation reports.

---

## File Structure

- Create `scripts/coverage_policy/__init__.py`: package exports used by tests and the CLI.
- Create `scripts/coverage_policy/models.py`: immutable policy, count, result, and report types.
- Create `scripts/coverage_policy/policy.py`: strict TOML policy parsing and path validation.
- Create `scripts/coverage_policy/snapshot.py`: coverage.py JSON parsing, normalization, and aggregation.
- Create `scripts/coverage_policy/evaluator.py`: ordered package and exact-file rule evaluation.
- Create `scripts/coverage_policy/cli.py`: CLI arguments, diagnostics, and exit-code mapping.
- Create `scripts/check_coverage_policy.py`: thin executable entry point.
- Create `tests/test_coverage_policy_config.py`: policy model/parser contract.
- Create `tests/test_coverage_policy_snapshot.py`: coverage report and evaluation contract.
- Create `tests/test_coverage_policy_cli.py`: output and exit-code contract.
- Create `tests/test_retrieval_fusion.py`: RRF empty, duplicate, tie, metadata, and truncation behavior.
- Create `tests/test_constraint_retriever.py`: constraint no-op, conversion, and exception behavior.
- Create `tests/test_keyword_service.py`: semantic keyword, fallback, dedupe, relation, and cap behavior.
- Create `tests/test_bm25_retriever.py`: dictionary, tokenization, build/search, and cache behavior.
- Create `tests/test_hybrid_driver_service.py`: driver ownership and degradation behavior.
- Create `tests/test_build_runtime_executor.py`: build/rebuild delegation and missing-service behavior.
- Create `tests/test_milvus_schema_client.py`: schema/client success, alias, absence, and failure behavior.
- Create `tests/test_build_job_locks.py`: process contention, backend flags, and cleanup behavior.
- Modify `rag_modules/runtime/build_jobs/locks.py`: isolate Windows/POSIX system calls from lock state.
- Modify `pyproject.toml`: activate structured package and nine exact-file rules.
- Modify `scripts/local_gate.py` and `tests/test_local_gate.py`: replace the local-gate step.
- Modify `.github/workflows/ci.yml` and `tests/test_enterprise_governance.py`: replace the CI check.
- Modify `README.md` and `docs/release_process.md`: document the three-layer policy.
- Delete `scripts/check_branch_coverage.py` and `tests/test_branch_coverage_gate.py` during activation.

---

### Task 1: Coverage Policy Models and Strict TOML Parser

**Files:**
- Create: `scripts/coverage_policy/__init__.py`
- Create: `scripts/coverage_policy/models.py`
- Create: `scripts/coverage_policy/policy.py`
- Create: `tests/test_coverage_policy_config.py`

**Interfaces:**
- Consumes: `Path.read_text(encoding="utf-8")` and `tomllib.loads`.
- Produces: `load_policy(path: Path) -> CoveragePolicy`, `normalize_policy_path(value: object, field_name: str) -> str`, `PackageCoverageRule`, `RiskModuleCoverageRule`, and `CoveragePolicy`.

- [ ] **Step 1: Write parser tests that describe the complete configuration contract**

```python
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
        (VALID_POLICY.replace('path = "rag_modules"', 'path = "C:/repo/rag_modules"'), "relative POSIX"),
        (VALID_POLICY.replace('path = "rag_modules"', "path = 'rag_modules\\\\retrieval'"), "relative POSIX"),
        (VALID_POLICY.replace('fusion.py', '*.py'), "globs"),
        (VALID_POLICY.replace('fusion.py', '../fusion.py'), "relative POSIX"),
        (VALID_POLICY.replace('branch_fail_under = 70', 'branch_fail_under = true'), "numeric"),
        (VALID_POLICY.replace('combined_fail_under = 85', 'combined_fail_under = 101'), "between 0 and 100"),
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
    duplicated = VALID_POLICY + """
[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80
"""

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
```

- [ ] **Step 2: Run the parser tests and confirm RED**

Run: `python -m pytest tests/test_coverage_policy_config.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.coverage_policy'`.

- [ ] **Step 3: Implement immutable policy types and strict parsing**

```python
# scripts/coverage_policy/models.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PackageCoverageRule:
    path: str
    branch_fail_under: float


@dataclass(frozen=True)
class RiskModuleCoverageRule:
    path: str
    combined_fail_under: float
    branch_fail_under: float


@dataclass(frozen=True)
class CoveragePolicy:
    package: PackageCoverageRule
    risk_modules: tuple[RiskModuleCoverageRule, ...]
```

```python
# scripts/coverage_policy/policy.py
from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from pathlib import Path

from .models import CoveragePolicy, PackageCoverageRule, RiskModuleCoverageRule


def normalize_policy_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty relative POSIX path")
    path = value
    segments = path.split("/")
    if (
        "\\" in path
        or path.startswith("/")
        or re.match(r"^[A-Za-z]:", path)
        or any(token in path for token in ("*", "?", "[", "]"))
    ):
        raise ValueError(f"{field_name} must be a relative POSIX path without globs")
    if any(not segment or segment in {".", ".."} for segment in segments):
        raise ValueError(f"{field_name} must be a relative POSIX path without empty or dot segments")
    return path


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be a mapping")
    return value


def _threshold(mapping: Mapping[str, object], field_name: str) -> float:
    value = mapping.get(field_name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError(f"{field_name} must be between 0 and 100")
    return threshold


def load_policy(path: Path) -> CoveragePolicy:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    coverage = _mapping(payload["tool"]["graph_rag"]["coverage"], "coverage")
    package_payload = _mapping(coverage.get("package"), "package")
    package = PackageCoverageRule(
        path=normalize_policy_path(package_payload.get("path"), "package.path"),
        branch_fail_under=_threshold(package_payload, "branch_fail_under"),
    )
    raw_risk_modules = coverage.get("risk_modules")
    if not isinstance(raw_risk_modules, list) or not raw_risk_modules:
        raise ValueError("risk_modules must be a non-empty array")
    risk_modules: list[RiskModuleCoverageRule] = []
    seen: set[str] = set()
    for index, raw_rule in enumerate(raw_risk_modules):
        rule = _mapping(raw_rule, f"risk_modules[{index}]")
        risk_path = normalize_policy_path(rule.get("path"), f"risk_modules[{index}].path")
        if risk_path in seen:
            raise ValueError(f"duplicate risk module path: {risk_path}")
        seen.add(risk_path)
        risk_modules.append(
            RiskModuleCoverageRule(
                path=risk_path,
                combined_fail_under=_threshold(rule, "combined_fail_under"),
                branch_fail_under=_threshold(rule, "branch_fail_under"),
            )
        )
    return CoveragePolicy(package=package, risk_modules=tuple(risk_modules))
```

Create this explicit package export surface:

```python
from .models import CoveragePolicy, PackageCoverageRule, RiskModuleCoverageRule
from .policy import load_policy, normalize_policy_path

__all__ = [
    "CoveragePolicy",
    "PackageCoverageRule",
    "RiskModuleCoverageRule",
    "load_policy",
    "normalize_policy_path",
]
```

- [ ] **Step 4: Run parser tests and static checks**

Run: `python -m pytest tests/test_coverage_policy_config.py -q`

Expected: all parser tests pass.

Run: `python -m ruff check scripts/coverage_policy tests/test_coverage_policy_config.py`

Expected: PASS with no changes required.

- [ ] **Step 5: Commit the parser unit**

```powershell
git add scripts/coverage_policy tests/test_coverage_policy_config.py
git commit -m "feat: define strict coverage policy"
```

---

### Task 2: Coverage Snapshot and Ordered Rule Evaluation

**Files:**
- Modify: `scripts/coverage_policy/models.py`
- Create: `scripts/coverage_policy/snapshot.py`
- Create: `scripts/coverage_policy/evaluator.py`
- Modify: `scripts/coverage_policy/__init__.py`
- Create: `tests/test_coverage_policy_snapshot.py`

**Interfaces:**
- Consumes: `CoveragePolicy` from Task 1 and coverage.py JSON `files[*].summary` counts.
- Produces: `CoverageSnapshot.from_json(path: Path)`, `CoverageSnapshot.from_payload(payload: object)`, `evaluate_policy(policy: CoveragePolicy, snapshot: CoverageSnapshot) -> CoverageEvaluation`.

- [ ] **Step 1: Write snapshot normalization and evaluation tests**

```python
from pathlib import Path

import pytest

from scripts.coverage_policy.evaluator import evaluate_policy
from scripts.coverage_policy.models import (
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


@pytest.mark.parametrize(
    "payload, message",
    [
        ({}, "files mapping"),
        (_payload({"rag_modules/retrieval/fusion.py": (-1, 40, 2, 10)}), "non-negative integer"),
        (_payload({"rag_modules/retrieval/fusion.py": (41, 40, 2, 10)}), "cannot exceed"),
        (_payload({"rag_modules/retrieval/fusion.py": (10, 40, 11, 10)}), "cannot exceed"),
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


def test_evaluation_rejects_missing_file_and_absent_branch_data() -> None:
    with pytest.raises(ValueError, match="missing configured risk file"):
        evaluate_policy(_policy(), CoverageSnapshot.from_payload(_payload({"rag_modules/x.py": (1, 1, 1, 1)})))

    with pytest.raises(ValueError, match="no branch data"):
        evaluate_policy(
            _policy(),
            CoverageSnapshot.from_payload(
                _payload(
                    {
                        "rag_modules/retrieval/fusion.py": (40, 40, 0, 0),
                        "rag_modules/covered.py": (1, 1, 1, 1),
                    }
                )
            ),
        )
```

- [ ] **Step 2: Run snapshot tests and confirm RED**

Run: `python -m pytest tests/test_coverage_policy_snapshot.py -q`

Expected: import fails because `snapshot.py` and `evaluator.py` do not exist.

- [ ] **Step 3: Add count/result models and the snapshot implementation**

Add these immutable models to `models.py`:

```python
@dataclass(frozen=True)
class CoverageCounts:
    covered_lines: int
    num_statements: int
    covered_branches: int
    num_branches: int

    @property
    def combined_percent(self) -> float:
        total = self.num_statements + self.num_branches
        if total == 0:
            raise ValueError("coverage counts contain no statements or branches")
        return 100.0 * (self.covered_lines + self.covered_branches) / total

    @property
    def branch_percent(self) -> float:
        if self.num_branches == 0:
            raise ValueError("coverage counts contain no branch data")
        return 100.0 * self.covered_branches / self.num_branches


@dataclass(frozen=True)
class CoverageRuleResult:
    kind: str
    path: str
    counts: CoverageCounts
    branch_fail_under: float
    combined_fail_under: float | None = None

    @property
    def branch_percent(self) -> float:
        return self.counts.branch_percent

    @property
    def combined_percent(self) -> float:
        return self.counts.combined_percent

    @property
    def passed(self) -> bool:
        combined_passed = (
            self.combined_fail_under is None
            or self.combined_percent >= self.combined_fail_under
        )
        return combined_passed and self.branch_percent >= self.branch_fail_under


@dataclass(frozen=True)
class CoverageEvaluation:
    results: tuple[CoverageRuleResult, ...]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)
```

Implement `CoverageSnapshot` with these exact public methods:

```python
import json
from collections.abc import Mapping
from pathlib import Path

from .models import CoverageCounts


class CoverageSnapshot:
    def __init__(self, files: Mapping[str, CoverageCounts]) -> None:
        self._files = dict(files)

    @classmethod
    def from_json(cls, path: Path) -> "CoverageSnapshot":
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_payload(cls, payload: object) -> "CoverageSnapshot":
        if not isinstance(payload, Mapping):
            raise ValueError("coverage report must contain a files mapping")
        raw_files = payload.get("files")
        if not isinstance(raw_files, Mapping):
            raise ValueError("coverage report must contain a files mapping")
        files: dict[str, CoverageCounts] = {}
        for filename, file_payload in raw_files.items():
            normalized = str(filename).replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized in files:
                raise ValueError(f"duplicate normalized coverage path: {normalized}")
            summary = _required_summary(file_payload, normalized)
            files[normalized] = _counts_from_summary(summary, normalized)
        return cls(files)

    def file_counts(self, path: str) -> CoverageCounts:
        try:
            return self._files[path]
        except KeyError as exc:
            raise ValueError(f"missing configured risk file in coverage report: {path}") from exc

    def package_counts(self, path: str) -> CoverageCounts:
        prefix = path.rstrip("/") + "/"
        matching = [counts for name, counts in self._files.items() if name.startswith(prefix)]
        if not matching:
            raise ValueError(f"coverage report contains no matching files for package: {path}")
        return CoverageCounts(
            covered_lines=sum(item.covered_lines for item in matching),
            num_statements=sum(item.num_statements for item in matching),
            covered_branches=sum(item.covered_branches for item in matching),
            num_branches=sum(item.num_branches for item in matching),
        )
```

Use these helpers to validate all four counts before constructing `CoverageCounts`:

```python
def _required_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _required_summary(file_payload: object, filename: str) -> Mapping[str, object]:
    if not isinstance(file_payload, Mapping):
        raise ValueError(f"coverage file is missing a summary mapping: {filename}")
    summary = file_payload.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError(f"coverage file is missing a summary mapping: {filename}")
    return summary


def _counts_from_summary(summary: Mapping[str, object], filename: str) -> CoverageCounts:
    covered_lines = _required_non_negative_int(
        summary.get("covered_lines"), f"{filename}.covered_lines"
    )
    num_statements = _required_non_negative_int(
        summary.get("num_statements"), f"{filename}.num_statements"
    )
    covered_branches = _required_non_negative_int(
        summary.get("covered_branches"), f"{filename}.covered_branches"
    )
    num_branches = _required_non_negative_int(
        summary.get("num_branches"), f"{filename}.num_branches"
    )
    if covered_lines > num_statements:
        raise ValueError(f"{filename}.covered_lines cannot exceed num_statements")
    if covered_branches > num_branches:
        raise ValueError(f"{filename}.covered_branches cannot exceed num_branches")
    return CoverageCounts(
        covered_lines=covered_lines,
        num_statements=num_statements,
        covered_branches=covered_branches,
        num_branches=num_branches,
    )
```

- [ ] **Step 4: Implement ordered evaluation**

```python
from .models import CoverageEvaluation, CoveragePolicy, CoverageRuleResult
from .snapshot import CoverageSnapshot


def evaluate_policy(
    policy: CoveragePolicy,
    snapshot: CoverageSnapshot,
) -> CoverageEvaluation:
    package_counts = snapshot.package_counts(policy.package.path)
    if package_counts.num_branches == 0:
        raise ValueError(f"package has no branch data: {policy.package.path}")
    results = [
        CoverageRuleResult(
            kind="package",
            path=policy.package.path,
            counts=package_counts,
            branch_fail_under=policy.package.branch_fail_under,
        )
    ]
    for rule in policy.risk_modules:
        counts = snapshot.file_counts(rule.path)
        if counts.num_branches == 0:
            raise ValueError(f"configured risk file has no branch data: {rule.path}")
        results.append(
            CoverageRuleResult(
                kind="risk_module",
                path=rule.path,
                counts=counts,
                combined_fail_under=rule.combined_fail_under,
                branch_fail_under=rule.branch_fail_under,
            )
        )
    return CoverageEvaluation(results=tuple(results))
```

Replace `scripts/coverage_policy/__init__.py` with:

```python
from .evaluator import evaluate_policy
from .models import (
    CoverageCounts,
    CoverageEvaluation,
    CoveragePolicy,
    CoverageRuleResult,
    PackageCoverageRule,
    RiskModuleCoverageRule,
)
from .policy import load_policy, normalize_policy_path
from .snapshot import CoverageSnapshot

__all__ = [
    "CoverageCounts",
    "CoverageEvaluation",
    "CoveragePolicy",
    "CoverageRuleResult",
    "CoverageSnapshot",
    "PackageCoverageRule",
    "RiskModuleCoverageRule",
    "evaluate_policy",
    "load_policy",
    "normalize_policy_path",
]
```

- [ ] **Step 5: Run the policy model, snapshot, and evaluator tests**

Run: `python -m pytest tests/test_coverage_policy_config.py tests/test_coverage_policy_snapshot.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit the evaluation unit**

```powershell
git add scripts/coverage_policy tests/test_coverage_policy_snapshot.py
git commit -m "feat: evaluate package and risk coverage"
```

---

### Task 3: Coverage Policy CLI

**Files:**
- Create: `scripts/coverage_policy/cli.py`
- Create: `scripts/check_coverage_policy.py`
- Create: `tests/test_coverage_policy_cli.py`

**Interfaces:**
- Consumes: `load_policy`, `CoverageSnapshot.from_json`, and `evaluate_policy`.
- Produces: `main(argv: Sequence[str] | None = None) -> int` with stable stdout/stderr and exit codes 0/1/2.

- [ ] **Step 1: Write CLI pass, multi-failure, and malformed-input tests**

```python
import json
from pathlib import Path

from scripts.coverage_policy.cli import main


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


def test_main_returns_two_for_invalid_input(tmp_path: Path, capsys) -> None:
    config = _config(tmp_path / "pyproject.toml")
    report = tmp_path / "coverage.json"
    report.write_text("not-json", encoding="utf-8")

    assert main(["--config", str(config), "--coverage-json", str(report)]) == 2
    assert "[ERROR] coverage policy:" in capsys.readouterr().err
```

- [ ] **Step 2: Run the CLI tests and confirm RED**

Run: `python -m pytest tests/test_coverage_policy_cli.py -q`

Expected: import fails because `scripts.coverage_policy.cli` does not exist.

- [ ] **Step 3: Implement the CLI and thin entry point**

```python
# scripts/coverage_policy/cli.py
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

from .evaluator import evaluate_policy
from .models import CoverageRuleResult
from .policy import load_policy
from .snapshot import CoverageSnapshot

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_PATH = ROOT_DIR / "coverage.json"
DEFAULT_CONFIG_PATH = ROOT_DIR / "pyproject.toml"


def _format_result(result: CoverageRuleResult) -> str:
    status = "PASS" if result.passed else "FAIL"
    branch = (
        f"branch {result.branch_percent:.2f}% "
        f"({result.counts.covered_branches}/{result.counts.num_branches}); "
        f"required {result.branch_fail_under:.2f}%"
    )
    if result.combined_fail_under is None:
        return f"[{status}] {result.kind} {result.path} {branch}"
    combined = (
        f"combined {result.combined_percent:.2f}% "
        f"({result.counts.covered_lines + result.counts.covered_branches}/"
        f"{result.counts.num_statements + result.counts.num_branches}); "
        f"required {result.combined_fail_under:.2f}%"
    )
    return f"[{status}] {result.kind} {result.path} {combined}; {branch}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce repository coverage policy.")
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.config)
        snapshot = CoverageSnapshot.from_json(args.coverage_json)
        evaluation = evaluate_policy(policy, snapshot)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"[ERROR] coverage policy: {exc}", file=sys.stderr)
        return 2
    for result in evaluation.results:
        print(_format_result(result))
    return 0 if evaluation.passed else 1
```

```python
# scripts/check_coverage_policy.py
"""Enforce package and risk-module coverage policy."""

from scripts.coverage_policy.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run all policy-engine tests**

Run: `python -m pytest tests/test_coverage_policy_config.py tests/test_coverage_policy_snapshot.py tests/test_coverage_policy_cli.py -q`

Expected: all tests pass while the repository still uses the old production gate.

- [ ] **Step 5: Commit the dormant CLI**

```powershell
git add scripts/check_coverage_policy.py scripts/coverage_policy tests/test_coverage_policy_cli.py
git commit -m "feat: add coverage policy cli"
```

---

### Task 4: Fusion and Constraint Retrieval Risk Tests

**Files:**
- Create: `tests/test_retrieval_fusion.py`
- Create: `tests/test_constraint_retriever.py`

**Interfaces:**
- Consumes: `FusionRanker.rrf_merge`, `ConstraintRetriever.search`, `EvidenceDocument`, `RetrievalRequest`, and `QueryConstraints`.
- Produces: regression contracts for empty results, duplicates, source priority, exact annotations, and downstream failure propagation.

- [ ] **Step 1: Record the current coverage RED for the two files**

Run this command before adding tests, then inspect the two entries in `coverage.json`:

`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`

Expected baseline: `fusion.py` is 15.69% combined/0.00% branch and
`constraint_retriever.py` is 34.48% combined/0.00% branch, both below policy.

- [ ] **Step 2: Add fusion behavior tests**

```python
import pytest

from rag_modules.contracts import EvidenceDocument
from rag_modules.retrieval.fusion import FusionRanker


def _doc(node_id: str, content: str, *, score: float = 0.0) -> EvidenceDocument:
    return EvidenceDocument(
        content=content,
        node_id=node_id,
        score=score,
        metadata={"original": content},
    )


def test_rrf_merge_returns_empty_for_empty_sources_and_non_positive_limit() -> None:
    ranker = FusionRanker()
    assert ranker.rrf_merge([], top_k=5) == []
    assert ranker.rrf_merge([("vector", [_doc("a", "a")])], top_k=0) == []


def test_rrf_merge_deduplicates_per_source_and_preserves_best_source_document() -> None:
    vector_a = _doc("a", "vector-a")
    graph_a = _doc("a", "graph-a")
    vector_b = _doc("b", "vector-b")
    graph_b = _doc("b", "graph-b")

    merged = FusionRanker(rrf_k=0).rrf_merge(
        [
            ("vector", [vector_a, vector_b, _doc("a", "late-duplicate")]),
            ("graph", [graph_b, graph_a]),
        ],
        top_k=2,
    )

    assert [doc.node_id for doc in merged] == ["a", "b"]
    assert merged[0].content == "vector-a"
    assert merged[0].metadata["rrf_ranks"] == {"vector": 1, "graph": 2}
    assert merged[0].metadata["rrf_chunk_hits"] == {"vector": 2, "graph": 1}
    assert merged[0].metadata["rrf_sources"] == ["vector", "graph"]
    assert merged[0].score == pytest.approx(1.5)
    assert merged[0].metadata["original"] == "vector-a"


def test_rrf_merge_uses_existing_score_only_when_computed_score_is_zero() -> None:
    document = _doc("a", "a", score=0.7)
    merged = FusionRanker(rrf_k=-1.5).rrf_merge(
        [("vector", [document]), ("graph", [_doc("b", "b"), document])],
        top_k=1,
    )
    assert merged[0].score == pytest.approx(0.7)
```

- [ ] **Step 3: Add constraint behavior tests**

```python
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.contracts import QueryConstraints, RetrievalRequest
from rag_modules.retrieval.adapters.constraint_retriever import ConstraintRetriever


def test_constraint_search_returns_empty_without_active_constraints_or_matcher() -> None:
    matcher = Mock()
    assert ConstraintRetriever(lambda: matcher).search(RetrievalRequest(query="tofu")) == []
    matcher.filter_and_rank.assert_not_called()

    request = RetrievalRequest(
        query="tofu",
        constraints=QueryConstraints(include_terms=["tofu"]),
    )
    assert ConstraintRetriever(lambda: None).search(request) == []


def test_constraint_search_converts_and_annotates_ranked_pages() -> None:
    matcher = Mock()
    matcher.filter_and_rank.return_value = [
        SimpleNamespace(
            page_content="recipe",
            metadata={"node_id": "r1", "constraint_score": 0.9, "source": "fixture"},
        )
    ]
    request = RetrievalRequest(
        query="tofu",
        candidate_k=7,
        constraints=QueryConstraints(include_terms=["tofu"]),
    )

    documents = ConstraintRetriever(lambda: matcher).search(request)

    matcher.filter_and_rank.assert_called_once_with(
        constraints=request.constraints,
        min_score=0.0,
        limit=7,
    )
    assert documents[0].node_id == "r1"
    assert documents[0].score == 0.9
    assert documents[0].search_method == "constraints"
    assert documents[0].search_type == "constraint_recipe"
    assert documents[0].metadata["source"] == "fixture"


def test_constraint_search_propagates_matcher_failure() -> None:
    matcher = Mock()
    matcher.filter_and_rank.side_effect = RuntimeError("constraint index unavailable")
    request = RetrievalRequest(
        query="tofu",
        constraints=QueryConstraints(include_terms=["tofu"]),
    )
    with pytest.raises(RuntimeError, match="constraint index unavailable"):
        ConstraintRetriever(lambda: matcher).search(request)
```

- [ ] **Step 4: Run focused tests and the two-file coverage check**

Run: `python -m pytest tests/test_retrieval_fusion.py tests/test_constraint_retriever.py -q`

Expected: all tests pass.

Regenerate the report with
`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`,
then run this exact focused audit:

```powershell
@'
import json
from pathlib import Path

report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
targets = [
    "rag_modules/retrieval/fusion.py",
    "rag_modules/retrieval/adapters/constraint_retriever.py",
]
for path in targets:
    summary = report["files"][path]["summary"]
    combined = 100 * (summary["covered_lines"] + summary["covered_branches"]) / (
        summary["num_statements"] + summary["num_branches"]
    )
    branch = 100 * summary["covered_branches"] / summary["num_branches"]
    print(f"{path}: combined={combined:.2f}% branch={branch:.2f}%")
    assert combined >= 85 and branch >= 80
'@ | python -
```

Expected: both assertions pass.

- [ ] **Step 5: Commit the retrieval contracts**

```powershell
git add tests/test_retrieval_fusion.py tests/test_constraint_retriever.py
git commit -m "test: cover fusion and constraint retrieval risks"
```

---

### Task 5: Keyword and BM25 Risk Tests

**Files:**
- Create: `tests/test_keyword_service.py`
- Create: `tests/test_bm25_retriever.py`

**Interfaces:**
- Consumes: `QueryKeywordExtractor`, `QuerySemanticProfile`, `BM25Retriever`, `load_custom_dict`, `tokenize_chinese`, and `TextDocument`.
- Produces: contracts for semantic fallback, term filtering, index readiness, scoring, metadata, and cache degradation.

- [ ] **Step 1: Record the keyword/BM25 coverage RED**

Run `python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`.

Expected baseline: `keyword_service.py` is 26.00% combined/0.00% branch and
`bm25_retriever.py` is 58.88% combined/40.91% branch.

- [ ] **Step 2: Add keyword extraction tests**

```python
from unittest.mock import patch

from rag_modules.configuration.testing import build_test_config, semantic_runtime_settings
from rag_modules.contracts import QuerySemanticProfile
from rag_modules.retrieval.keyword_service import QueryKeywordExtractor


def _extractor() -> QueryKeywordExtractor:
    return QueryKeywordExtractor(semantic_runtime_settings(build_test_config()))


def test_extract_combines_entities_constraints_relations_and_deduplicates() -> None:
    profile = QuerySemanticProfile(
        source_entities=["tofu", "tofu"],
        target_entities=["soup"],
        entity_keywords=["tofu", "ginger"],
        topic_keywords=["quick", "quick"],
        recommendation_hits=["healthy"],
        relation_types=["USES"],
        constraints={"preference_terms": ["light"], "include_terms": ["ginger"]},
    )
    with (
        patch("rag_modules.retrieval.keyword_service.infer_query_semantic_profile", return_value=profile),
        patch("rag_modules.retrieval.keyword_service.relation_index_terms", return_value=["ingredient", "quick"]),
    ):
        entities, topics = _extractor().extract("query")

    assert entities == ["tofu", "soup", "ginger"]
    assert topics == ["quick", "healthy", "light", "ginger", "ingredient"]


def test_extract_handles_empty_profile_and_caps_outputs_at_eight() -> None:
    empty = QuerySemanticProfile()
    with patch("rag_modules.retrieval.keyword_service.infer_query_semantic_profile", return_value=empty):
        assert _extractor().extract("") == ([], [])

    profile = QuerySemanticProfile(topic_keywords=[f"topic-{index}" for index in range(10)])
    with patch("rag_modules.retrieval.keyword_service.infer_query_semantic_profile", return_value=profile):
        _, topics = _extractor().extract("many topics")
    assert topics == [f"topic-{index}" for index in range(8)]


def test_dedupe_terms_removes_blank_and_duplicate_values() -> None:
    assert QueryKeywordExtractor.dedupe_terms([" tofu ", "", "tofu", "soup"]) == [
        "tofu",
        "soup",
    ]
```

- [ ] **Step 3: Add BM25 lifecycle, search, and cache tests**

```python
from unittest.mock import Mock, patch

from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.adapters import bm25_retriever as module
from rag_modules.retrieval.adapters.bm25_retriever import BM25Retriever


class _FakeBM25:
    def __init__(self, corpus: list[list[str]]) -> None:
        self.corpus = corpus

    def get_scores(self, query: list[str]) -> list[float]:
        assert query == ["tofu"]
        return [0.2, 0.0, 0.9]


def test_custom_dictionary_is_optional_and_loaded_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(module, "_CUSTOM_DICT_LOADED", False)
    load = Mock()
    monkeypatch.setattr(module.jieba, "load_userdict", load)
    missing = tmp_path / "missing.txt"
    module.load_custom_dict(str(missing))
    module.load_custom_dict(str(missing))
    load.assert_not_called()

    dictionary = tmp_path / "dict.txt"
    dictionary.write_text("tofu 10", encoding="utf-8")
    monkeypatch.setattr(module, "_CUSTOM_DICT_LOADED", False)
    module.load_custom_dict(str(dictionary))
    module.load_custom_dict(str(dictionary))
    load.assert_called_once_with(str(dictionary))


def test_tokenize_filters_blank_stopword_and_space_tokens() -> None:
    with patch.object(module.jieba, "lcut", return_value=["tofu", " ", "", "soup"]):
        assert module.tokenize_chinese("query") == ["tofu", "soup"]
    assert module.tokenize_chinese("") == []


def test_build_and_search_order_positive_scores_and_normalize_metadata(monkeypatch) -> None:
    monkeypatch.setattr(module, "BM25Okapi", _FakeBM25)
    monkeypatch.setattr(module, "load_custom_dict", lambda: None)
    monkeypatch.setattr(module, "tokenize_chinese", lambda text: ["tofu"] if text else [])
    retriever = BM25Retriever()
    chunks = [
        TextDocument(content="a", metadata={"name": "A", "node_id": "a"}),
        TextDocument(content="b", metadata={"recipe_name": "B", "recipe_id": "b"}),
        TextDocument(content="c", metadata={"recipe_name": "C", "parent_id": "c"}),
    ]

    assert retriever.search("tofu") == []
    retriever.build(chunks)
    documents = retriever.search("tofu", top_k=3)

    assert retriever.ready is True
    assert [doc.recipe_name for doc in documents] == ["C", "A"]
    assert [doc.score for doc in documents] == [0.9, 0.2]
    assert documents[0].search_method == "bm25"
    assert documents[0].metadata["source"] == "bm25"
    assert retriever.search("") == []


def test_cache_round_trip_and_invalid_payloads(monkeypatch) -> None:
    monkeypatch.setattr(module, "BM25Okapi", _FakeBM25)
    monkeypatch.setattr(module, "tokenize_chinese", lambda text: text.split())
    retriever = BM25Retriever()
    retriever.corpus_docs = [TextDocument(content="tofu soup", metadata={"node_id": "r1"})]
    payload = retriever.to_cache_dict()

    restored = BM25Retriever()
    assert restored.from_cache_dict(payload) is True
    assert restored.corpus_docs == retriever.corpus_docs
    assert restored.from_cache_dict({"tokenized_corpus": "bad", "corpus_docs": []}) is False
    assert restored.from_cache_dict({"tokenized_corpus": [[]], "corpus_docs": []}) is False
    assert restored.from_cache_dict({"tokenized_corpus": ["bad"], "corpus_docs": [{"page_content": "x"}]}) is False
    assert restored.from_cache_dict({"tokenized_corpus": [[]], "corpus_docs": [{}]}) is False
```

- [ ] **Step 4: Run focused tests and confirm the two thresholds**

Run: `python -m pytest tests/test_keyword_service.py tests/test_bm25_retriever.py -q`

Expected: all tests pass.

Regenerate full coverage with
`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`,
then run:

```powershell
@'
import json
from pathlib import Path

report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
targets = [
    "rag_modules/retrieval/keyword_service.py",
    "rag_modules/retrieval/adapters/bm25_retriever.py",
]
for path in targets:
    summary = report["files"][path]["summary"]
    combined = 100 * (summary["covered_lines"] + summary["covered_branches"]) / (
        summary["num_statements"] + summary["num_branches"]
    )
    branch = 100 * summary["covered_branches"] / summary["num_branches"]
    print(f"{path}: combined={combined:.2f}% branch={branch:.2f}%")
    assert combined >= 85 and branch >= 80
'@ | python -
```

Expected: both assertions pass.

- [ ] **Step 5: Commit keyword/BM25 contracts**

```powershell
git add tests/test_keyword_service.py tests/test_bm25_retriever.py
git commit -m "test: cover keyword and bm25 degradation"
```

---

### Task 6: Hybrid Driver and Build Executor Risk Tests

**Files:**
- Create: `tests/test_hybrid_driver_service.py`
- Create: `tests/test_build_runtime_executor.py`

**Interfaces:**
- Consumes: `HybridDriverService`, `BuildRuntimeExecutor`, `BuildRuntime`, `ArtifactManifest`, and `build_test_config`.
- Produces: contracts for dependency reuse, ownership, cleanup, delegation, manifest refresh, and missing-service errors.

- [ ] **Step 1: Record the current RED metrics**

Run `python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`.

Expected baseline: `hybrid_driver_service.py` is 33.33% combined/0.00% branch and
`build_runtime_executor.py` is 30.43% combined/0.00% branch.

- [ ] **Step 2: Add hybrid driver ownership tests**

```python
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.retrieval.hybrid_driver_service import HybridDriverService


def test_ensure_driver_reuses_existing_or_injected_manager_driver() -> None:
    existing = object()
    state = SimpleNamespace(driver=existing, owns_driver=True)
    assert HybridDriverService(storage=object()).ensure_driver(state) is existing

    injected = object()
    state = SimpleNamespace(driver=None, owns_driver=True)
    service = HybridDriverService(
        storage=object(),
        neo4j_manager=SimpleNamespace(driver=injected),
    )
    assert service.ensure_driver(state) is injected
    assert state.owns_driver is False


def test_ensure_driver_requires_injected_manager() -> None:
    with pytest.raises(RuntimeError, match="injected Neo4j manager"):
        HybridDriverService(storage=object()).ensure_driver(
            SimpleNamespace(driver=None, owns_driver=False)
        )


def test_close_only_closes_owned_non_empty_driver() -> None:
    driver = Mock()
    HybridDriverService.close(SimpleNamespace(driver=driver, owns_driver=True))
    driver.close.assert_called_once_with()

    driver.reset_mock()
    HybridDriverService.close(SimpleNamespace(driver=driver, owns_driver=False))
    HybridDriverService.close(SimpleNamespace(driver=None, owns_driver=True))
    driver.close.assert_not_called()
```

- [ ] **Step 3: Add build/rebuild executor tests**

```python
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.app.composition.build_runtime_executor import BuildRuntimeExecutor
from rag_modules.app.runtime_state import BuildRuntime
from rag_modules.configuration.testing import build_test_config
from rag_modules.kernel.artifacts import ArtifactManifest


def _runtime(service: object | None) -> BuildRuntime:
    return BuildRuntime(
        config=build_test_config(),
        neo4j_manager=SimpleNamespace(),
        data_module=SimpleNamespace(),
        index_module=SimpleNamespace(),
        knowledge_base_service=service,
    )


@pytest.mark.parametrize("method_name, service_method", [("build_knowledge_base", "build"), ("rebuild_knowledge_base", "rebuild")])
def test_executor_delegates_and_refreshes_manifest(method_name: str, service_method: str) -> None:
    manifest = ArtifactManifest(stage="ready", total_documents=1, total_chunks=1, vector_rows=1)
    service = SimpleNamespace(
        build=Mock(),
        rebuild=Mock(),
        artifact_manifest=manifest,
    )
    runtime = _runtime(service)
    progress = Mock()

    result = getattr(BuildRuntimeExecutor(), method_name)(
        runtime,
        progress=progress,
        request_id="request-1",
        build_job_id="job-1",
    )

    getattr(service, service_method).assert_called_once_with(
        progress=progress,
        request_id="request-1",
        build_job_id="job-1",
    )
    assert result is runtime
    assert runtime.artifact_manifest is manifest


@pytest.mark.parametrize("method_name", ["build_knowledge_base", "rebuild_knowledge_base"])
def test_executor_rejects_runtime_without_knowledge_base_service(method_name: str) -> None:
    with pytest.raises(ValueError, match="missing a knowledge base service"):
        getattr(BuildRuntimeExecutor(), method_name)(_runtime(None))
```

- [ ] **Step 4: Run focused tests and confirm both thresholds**

Run: `python -m pytest tests/test_hybrid_driver_service.py tests/test_build_runtime_executor.py -q`

Expected: all tests pass. Regenerate full coverage with
`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`,
then run:

```powershell
@'
import json
from pathlib import Path

report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
targets = [
    "rag_modules/retrieval/hybrid_driver_service.py",
    "rag_modules/app/composition/build_runtime_executor.py",
]
for path in targets:
    summary = report["files"][path]["summary"]
    combined = 100 * (summary["covered_lines"] + summary["covered_branches"]) / (
        summary["num_statements"] + summary["num_branches"]
    )
    branch = 100 * summary["covered_branches"] / summary["num_branches"]
    print(f"{path}: combined={combined:.2f}% branch={branch:.2f}%")
    assert combined >= 85 and branch >= 80
'@ | python -
```

Expected: both assertions pass.

- [ ] **Step 5: Commit lifecycle contracts**

```powershell
git add tests/test_hybrid_driver_service.py tests/test_build_runtime_executor.py
git commit -m "test: cover driver and build executor lifecycles"
```

---

### Task 7: Milvus Schema and Client Risk Tests

**Files:**
- Create: `tests/test_milvus_schema_client.py`

**Interfaces:**
- Consumes: private operation mixins through `MilvusIndexConstructionModule.__new__`, matching the repository's existing `test_milvus_blue_green.py` pattern.
- Produces: offline contracts for schema construction, collection/index operations, aliases, stats, load/delete, setup, close, and exception degradation.

- [ ] **Step 1: Record the Milvus coverage RED**

Run `python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`.

Expected baseline: `schema.py` is 22.45% combined/0.00% branch and `client.py` is 28.41%
combined/16.67% branch.

- [ ] **Step 2: Add a contract-shaped fake and schema tests**

```python
from types import SimpleNamespace
from unittest.mock import Mock, patch

from rag_modules.infra.milvus.module import MilvusIndexConstructionModule


class _IndexParams:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def add_index(self, **kwargs: object) -> None:
        self.calls.append(dict(kwargs))


class _Client:
    def __init__(self) -> None:
        self.collections: set[str] = set()
        self.aliases: dict[str, str] = {}
        self.created: list[dict[str, object]] = []
        self.dropped: list[str] = []
        self.loaded: list[str] = []
        self.indexes: list[dict[str, object]] = []
        self.stats: dict[str, object] = {"row_count": 4, "index_building_progress": 100}
        self.failure: RuntimeError | None = None

    def _raise(self) -> None:
        if self.failure:
            raise self.failure

    def list_collections(self) -> list[str]:
        self._raise()
        return sorted(self.collections)

    def has_collection(self, name: str) -> bool:
        self._raise()
        return name in self.collections

    def create_collection(self, **kwargs: object) -> None:
        self._raise()
        self.created.append(dict(kwargs))
        self.collections.add(str(kwargs["collection_name"]))

    def drop_collection(self, name: str) -> None:
        self._raise()
        self.dropped.append(name)
        self.collections.discard(name)

    def prepare_index_params(self) -> _IndexParams:
        self._raise()
        return _IndexParams()

    def create_index(self, **kwargs: object) -> None:
        self._raise()
        self.indexes.append(dict(kwargs))

    def get_collection_stats(self, name: str) -> dict[str, object]:
        self._raise()
        return dict(self.stats)

    def load_collection(self, name: str) -> None:
        self._raise()
        self.loaded.append(name)

    def describe_alias(self, *, alias: str) -> dict[str, str]:
        self._raise()
        if alias not in self.aliases:
            raise RuntimeError("alias missing")
        return {"collection": self.aliases[alias]}


def _module(client: _Client | None = None) -> MilvusIndexConstructionModule:
    module = MilvusIndexConstructionModule.__new__(MilvusIndexConstructionModule)
    module.client = client or _Client()
    module.host = "localhost"
    module.port = 19530
    module.dimension = 512
    module.base_collection_name = "recipes"
    module.collection_name = "recipes"
    module.collection_alias = "recipes__active"
    module.collection_created = False
    module.active_collection_name = ""
    module.active_collection_slot = ""
    module.blue_green_enabled = True
    module.embedding_client = SimpleNamespace(name="embedding")
    return module


def test_schema_contains_required_vector_and_metadata_fields() -> None:
    schema = _module()._create_collection_schema()
    fields = {field.name: field for field in schema.fields}
    assert set(fields) == {
        "id", "vector", "text", "node_id", "recipe_name", "node_type", "category",
        "cuisine_type", "difficulty", "doc_type", "chunk_id", "parent_id",
    }
    assert fields["vector"].params["dim"] == 512


def test_create_collection_reuses_or_force_recreates_and_degrades_failures() -> None:
    client = _Client()
    client.collections.add("recipes")
    module = _module(client)
    assert module.create_collection() is True
    assert client.created == []
    assert module.collection_created is True

    module.collection_created = False
    assert module.create_collection(force_recreate=True, collection_name="recipes") is True
    assert client.dropped == ["recipes"]
    assert client.created[0]["metric_type"] == "COSINE"

    client.failure = RuntimeError("milvus down")
    assert module.create_collection() is False


def test_create_index_requires_collection_and_uses_hnsw() -> None:
    module = _module()
    assert module.create_index() is False
    module.collection_created = True
    assert module.create_index(collection_name="recipes") is True
    params = module.client.indexes[0]["index_params"]
    assert params.calls[0]["index_type"] == "HNSW"
    assert params.calls[0]["params"] == {"M": 16, "efConstruction": 200}
```

- [ ] **Step 3: Add client setup, alias, stats, load/delete, close, and failure tests**

```python
def test_setup_client_and_embeddings_use_injected_dependencies() -> None:
    fake = _Client()
    with patch("rag_modules.infra.milvus.client.MilvusClient", return_value=fake) as constructor:
        module = _module()
        module._setup_client()
    constructor.assert_called_once_with(uri="http://localhost:19530")
    module._setup_embeddings()
    assert module.embeddings is module.embedding_client


def test_stats_resolve_alias_and_degrade_when_unavailable() -> None:
    client = _Client()
    client.collections.add("recipes__blue")
    client.aliases["recipes__active"] = "recipes__blue"
    module = _module(client)
    module.collection_created = True
    module.collection_name = "recipes__active"
    module.active_collection_name = "recipes__blue"
    module.active_collection_slot = "blue"

    stats = module.get_collection_stats()
    assert stats["collection_name"] == "recipes__active"
    assert stats["row_count"] == 4
    assert module.get_collection_stats("missing")["row_count"] == 4

    client.failure = RuntimeError("stats down")
    assert module.get_collection_stats() == {"error": "MILVUS_STATS_UNAVAILABLE"}

    module.collection_created = False
    assert "error" in module.get_collection_stats()


def test_has_delete_and_load_cover_alias_direct_absent_and_failure_paths() -> None:
    client = _Client()
    client.collections.update({"recipes", "recipes__blue"})
    client.aliases["recipes__active"] = "recipes__blue"
    module = _module(client)

    assert module.has_collection("recipes") is True
    assert module.has_collection("recipes__active") is True
    assert module.load_collection("recipes__active") is True
    assert client.loaded == ["recipes__blue"]
    assert module.collection_name == "recipes__active"
    assert module.delete_collection("recipes") is True
    assert module.collection_created is True
    assert module.delete_collection("absent") is True
    assert module.load_collection("absent") is False

    client.failure = RuntimeError("milvus down")
    assert module.has_collection("recipes") is False
    assert module.delete_collection("recipes") is False
    assert module.load_collection("recipes") is False


def test_close_and_destructor_tolerate_missing_or_present_client() -> None:
    module = _module()
    module.close()
    module.__del__()
    empty = MilvusIndexConstructionModule.__new__(MilvusIndexConstructionModule)
    empty.close()
```

- [ ] **Step 4: Run Milvus tests and confirm both thresholds**

Run: `python -m pytest tests/test_milvus_schema_client.py tests/test_milvus_blue_green.py -q`

Expected: all tests pass without a Milvus process.

Regenerate the full report with
`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`,
then run:

```powershell
@'
import json
from pathlib import Path

report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
targets = [
    "rag_modules/infra/milvus/schema.py",
    "rag_modules/infra/milvus/client.py",
]
for path in targets:
    summary = report["files"][path]["summary"]
    combined = 100 * (summary["covered_lines"] + summary["covered_branches"]) / (
        summary["num_statements"] + summary["num_branches"]
    )
    branch = 100 * summary["covered_branches"] / summary["num_branches"]
    print(f"{path}: combined={combined:.2f}% branch={branch:.2f}%")
    assert combined >= 85 and branch >= 80
'@ | python -
```

Expected: both assertions pass.

- [ ] **Step 5: Commit Milvus contracts**

```powershell
git add tests/test_milvus_schema_client.py
git commit -m "test: cover milvus schema and client risks"
```

---

### Task 8: File-Lock Backend Refactor and Concurrency Tests

**Files:**
- Modify: `rag_modules/runtime/build_jobs/locks.py`
- Create: `tests/test_build_job_locks.py`

**Interfaces:**
- Consumes: existing `InterprocessFileLock(path: str, *, blocking: bool = True)` public API.
- Produces: private `_WindowsFileLockBackend`, `_PosixFileLockBackend`, `_load_file_lock_backend()`, and leak-free acquire/release state transitions; public constructor/context semantics stay unchanged.

- [ ] **Step 1: Write failing backend and cleanup tests before refactoring**

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from rag_modules.runtime.build_jobs import locks
from rag_modules.runtime.build_jobs.locks import InterprocessFileLock


class _File:
    def __init__(self) -> None:
        self.closed = False
        self.seeks: list[int] = []

    def seek(self, offset: int) -> None:
        self.seeks.append(offset)

    def fileno(self) -> int:
        return 7

    def close(self) -> None:
        self.closed = True


def test_windows_backend_selects_blocking_flags_and_unlocks() -> None:
    api = SimpleNamespace(LK_LOCK=1, LK_NBLCK=2, LK_UNLCK=3, locking=Mock())
    backend = locks._WindowsFileLockBackend(api)
    file = _File()
    backend.lock(file, blocking=True)
    backend.lock(file, blocking=False)
    backend.unlock(file)
    assert api.locking.call_args_list[0].args == (7, 1, 1)
    assert api.locking.call_args_list[1].args == (7, 2, 1)
    assert api.locking.call_args_list[2].args == (7, 3, 1)
    assert file.seeks == [0, 0, 0]


def test_posix_backend_selects_nonblocking_flag_and_unlocks() -> None:
    api = SimpleNamespace(LOCK_EX=1, LOCK_NB=2, LOCK_UN=4, flock=Mock())
    backend = locks._PosixFileLockBackend(api)
    file = _File()
    backend.lock(file, blocking=False)
    backend.unlock(file)
    assert api.flock.call_args_list[0].args == (7, 3)
    assert api.flock.call_args_list[1].args == (7, 4)


def test_nonblocking_same_process_contention_and_context_failure(tmp_path) -> None:
    path = tmp_path / "jobs.lock"
    first = InterprocessFileLock(str(path))
    second = InterprocessFileLock(str(path), blocking=False)
    assert first.acquire() is True
    assert first.acquire() is True
    assert second.acquire() is False
    with pytest.raises(BlockingIOError, match="Could not acquire"):
        with second:
            raise AssertionError("context body must not run")
    first.release()
    assert second.acquire() is True
    second.release()
    second.release()


def test_acquire_open_failure_releases_process_lock(tmp_path) -> None:
    path = tmp_path / "jobs.lock"
    lock = InterprocessFileLock(str(path))
    with patch("builtins.open", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError, match="disk unavailable"):
            lock.acquire()
    contender = InterprocessFileLock(str(path), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_backend_failure_closes_file_and_nonblocking_returns_false(tmp_path) -> None:
    backend = Mock()
    backend.lock.side_effect = OSError("busy")
    file = _File()
    lock = InterprocessFileLock(str(tmp_path / "jobs.lock"), blocking=False)
    lock._backend = backend
    with patch("builtins.open", return_value=file):
        assert lock.acquire() is False
    assert file.closed is True
    contender = InterprocessFileLock(str(tmp_path / "jobs.lock"), blocking=False)
    assert contender.acquire() is True
    contender.release()


def test_context_body_exception_releases_os_and_process_locks(tmp_path) -> None:
    path = tmp_path / "jobs.lock"
    with pytest.raises(RuntimeError, match="body failed"):
        with InterprocessFileLock(str(path)):
            raise RuntimeError("body failed")
    with InterprocessFileLock(str(path), blocking=False):
        pass
```

- [ ] **Step 2: Run the lock tests and confirm RED**

Run: `python -m pytest tests/test_build_job_locks.py -q`

Expected: collection fails because private backend classes do not exist.

- [ ] **Step 3: Implement platform backends and exception-safe acquisition**

Replace function-local platform branches with:

```python
class _WindowsFileLockBackend:
    def __init__(self, api: Any) -> None:
        self._api = api

    def lock(self, file: BinaryIO, *, blocking: bool) -> None:
        file.seek(0)
        mode = self._api.LK_LOCK if blocking else self._api.LK_NBLCK
        self._api.locking(file.fileno(), mode, 1)

    def unlock(self, file: BinaryIO) -> None:
        file.seek(0)
        self._api.locking(file.fileno(), self._api.LK_UNLCK, 1)


class _PosixFileLockBackend:
    def __init__(self, api: Any) -> None:
        self._api = api

    def lock(self, file: BinaryIO, *, blocking: bool) -> None:
        flags = self._api.LOCK_EX
        if not blocking:
            flags |= self._api.LOCK_NB
        self._api.flock(file.fileno(), flags)

    def unlock(self, file: BinaryIO) -> None:
        self._api.flock(file.fileno(), self._api.LOCK_UN)


def _load_file_lock_backend() -> _WindowsFileLockBackend | _PosixFileLockBackend:
    if sys.platform == "win32":
        import msvcrt

        return _WindowsFileLockBackend(msvcrt)
    fcntl = cast(Any, __import__("fcntl"))
    return _PosixFileLockBackend(fcntl)
```

In `InterprocessFileLock.__init__`, add:

```python
self._backend = _load_file_lock_backend()
```

Replace `acquire` and `release` with:

```python
def acquire(self) -> bool:
    if self._acquired:
        return True
    if not self._process_lock.acquire(blocking=self.blocking):
        return False
    file: BinaryIO | None = None
    try:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        file = open(self.path, "a+b")
        self._backend.lock(file, blocking=self.blocking)
    except OSError:
        if file is not None:
            file.close()
        self._process_lock.release()
        if self.blocking:
            raise
        return False
    self._file = file
    self._acquired = True
    return True

def release(self) -> None:
    if not self._acquired:
        return
    file = self._file
    self._file = None
    self._acquired = False
    try:
        if file is not None:
            self._backend.unlock(file)
    finally:
        if file is not None:
            file.close()
        self._process_lock.release()
```

- [ ] **Step 4: Run lock and repository-storage tests**

Run: `python -m pytest tests/test_build_job_locks.py tests/test_build_job_persistence.py tests/test_build_job_migration.py tests/test_build_job_repository_recovery_retention.py tests/test_build_job_repository_records.py -q`

Expected: all lock and file-repository consumers pass.

- [ ] **Step 5: Confirm lock coverage and static checks**

Regenerate full coverage with
`python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=json:coverage.json`,
then run:

```powershell
@'
import json
from pathlib import Path

path = "rag_modules/runtime/build_jobs/locks.py"
summary = json.loads(Path("coverage.json").read_text(encoding="utf-8"))["files"][path]["summary"]
combined = 100 * (summary["covered_lines"] + summary["covered_branches"]) / (
    summary["num_statements"] + summary["num_branches"]
)
branch = 100 * summary["covered_branches"] / summary["num_branches"]
print(f"{path}: combined={combined:.2f}% branch={branch:.2f}%")
assert combined >= 85 and branch >= 80
'@ | python -
```

Expected: the assertion passes.

Run: `python -m ruff check rag_modules/runtime/build_jobs/locks.py tests/test_build_job_locks.py`

Expected: PASS.

- [ ] **Step 6: Commit the lock refactor**

```powershell
git add rag_modules/runtime/build_jobs/locks.py tests/test_build_job_locks.py
git commit -m "refactor: isolate file lock backends"
```

---

### Task 9: Atomically Activate the Coverage Policy Across Local Gate, CI, and Docs

**Files:**
- Modify: `pyproject.toml`
- Modify: `scripts/local_gate.py`
- Modify: `tests/test_local_gate.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `tests/test_enterprise_governance.py`
- Modify: `README.md`
- Modify: `docs/release_process.md`
- Delete: `scripts/check_branch_coverage.py`
- Delete: `tests/test_branch_coverage_gate.py`

**Interfaces:**
- Consumes: passing policy engine and all risk-path tests from Tasks 1-8.
- Produces: one repository policy, `coverage_policy` local-gate step, `python scripts/check_coverage_policy.py` CI command, and no legacy compatibility surface.

- [ ] **Step 1: Write failing migration contract tests**

Update `tests/test_local_gate.py` so the expected step names and display commands contain
`coverage_policy` and `("python", "scripts/check_coverage_policy.py")`, and update
`tests/test_enterprise_governance.py` to assert:

```python
def test_ci_enforces_package_and_risk_coverage_after_json_report() -> None:
    workflow = _read(".github/workflows/ci.yml")
    assert "--cov-report=json:coverage.json" in workflow
    assert "python scripts/check_coverage_policy.py" in workflow
    assert "python scripts/check_branch_coverage.py" not in workflow
    assert workflow.index("--cov-report=json:coverage.json") < workflow.index(
        "python scripts/check_coverage_policy.py"
    )
```

Add this exact configuration-governance assertion:

```python
def test_project_config_declares_every_risk_module_with_dual_thresholds() -> None:
    pyproject = _read("pyproject.toml")
    risk_paths = [
        "rag_modules/retrieval/fusion.py",
        "rag_modules/retrieval/adapters/constraint_retriever.py",
        "rag_modules/retrieval/keyword_service.py",
        "rag_modules/retrieval/adapters/bm25_retriever.py",
        "rag_modules/retrieval/hybrid_driver_service.py",
        "rag_modules/infra/milvus/schema.py",
        "rag_modules/infra/milvus/client.py",
        "rag_modules/app/composition/build_runtime_executor.py",
        "rag_modules/runtime/build_jobs/locks.py",
    ]
    assert "rag_modules_branch_fail_under" not in pyproject
    assert pyproject.count("[[tool.graph_rag.coverage.risk_modules]]") == 9
    assert pyproject.count("combined_fail_under = 85") == 9
    assert pyproject.count("branch_fail_under = 80") == 9
    for path in risk_paths:
        assert f'path = "{path}"' in pyproject
```

- [ ] **Step 2: Run migration contract tests and confirm RED**

Run: `python -m pytest tests/test_local_gate.py tests/test_enterprise_governance.py -q`

Expected: failures show the old step/command/configuration is still active.

- [ ] **Step 3: Replace the scalar config with the full structured policy**

```toml
[tool.graph_rag.coverage.package]
path = "rag_modules"
branch_fail_under = 70

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/adapters/constraint_retriever.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/keyword_service.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/adapters/bm25_retriever.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/hybrid_driver_service.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/infra/milvus/schema.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/infra/milvus/client.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/app/composition/build_runtime_executor.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/runtime/build_jobs/locks.py"
combined_fail_under = 85
branch_fail_under = 80
```

- [ ] **Step 4: Replace local and CI commands and delete the old checker**

In `scripts/local_gate.py`, change `DEFAULT_STEP_NAMES` from `branch_coverage` to
`coverage_policy` and replace the corresponding `GateStep` with:

```python
GateStep(
    name="coverage_policy",
    command=(python_executable, str(scripts_dir / "check_coverage_policy.py")),
    display_command=("python", "scripts/check_coverage_policy.py"),
),
```

Rename the GitHub Actions step to `Coverage policy` and run
`python scripts/check_coverage_policy.py`. Delete `scripts/check_branch_coverage.py` and
`tests/test_branch_coverage_gate.py` in the same change; do not leave an import shim.

- [ ] **Step 5: Update operational documentation with exact policy semantics**

In `README.md` and `docs/release_process.md`, replace the package-only description with:

```markdown
The full suite writes `coverage.json` and then runs
`python scripts/check_coverage_policy.py`. Coverage is enforced at three levels: 75% repository
combined coverage, 70% `rag_modules` branch coverage, and 85% combined plus 80% branch coverage
for every exact file listed under `tool.graph_rag.coverage.risk_modules`. Add a new risk file by
adding an explicit TOML entry; directory aggregation and inherited thresholds are not supported.
```

Follow the paragraph with this operator-visible list:

```markdown
Protected risk files:

- `rag_modules/retrieval/fusion.py`
- `rag_modules/retrieval/adapters/constraint_retriever.py`
- `rag_modules/retrieval/keyword_service.py`
- `rag_modules/retrieval/adapters/bm25_retriever.py`
- `rag_modules/retrieval/hybrid_driver_service.py`
- `rag_modules/infra/milvus/schema.py`
- `rag_modules/infra/milvus/client.py`
- `rag_modules/app/composition/build_runtime_executor.py`
- `rag_modules/runtime/build_jobs/locks.py`
```

- [ ] **Step 6: Run migration and policy tests**

Run: `python -m pytest tests/test_coverage_policy_config.py tests/test_coverage_policy_snapshot.py tests/test_coverage_policy_cli.py tests/test_local_gate.py tests/test_enterprise_governance.py -q`

Expected: all tests pass and no test imports the deleted module.

- [ ] **Step 7: Generate the authoritative report and run the activated policy**

Run:

```powershell
python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
python scripts/check_coverage_policy.py
```

Expected: pytest passes the 75% combined gate; the CLI prints ten PASS lines (one package and nine
risk modules); package branch coverage is at least 70%; every risk line shows combined coverage at
least 85% and branch coverage at least 80%.

- [ ] **Step 8: Commit the atomic activation**

```powershell
git add -A scripts tests pyproject.toml .github/workflows/ci.yml README.md docs/release_process.md
git commit -m "ci: enforce risk-module coverage policy"
```

---

### Task 10: Final Verification and Delivery Audit

**Files:**
- Verify only; fix only failures attributable to Tasks 1-9 in the owning task's files.

**Interfaces:**
- Consumes: the fully activated policy and fresh coverage report.
- Produces: evidence that formatting, typing, tests, release gates, and repository cleanliness all pass.

- [ ] **Step 1: Run the complete focused risk slice**

```powershell
python -m pytest tests/test_coverage_policy_config.py tests/test_coverage_policy_snapshot.py tests/test_coverage_policy_cli.py tests/test_retrieval_fusion.py tests/test_constraint_retriever.py tests/test_keyword_service.py tests/test_bm25_retriever.py tests/test_hybrid_driver_service.py tests/test_build_runtime_executor.py tests/test_milvus_schema_client.py tests/test_build_job_locks.py tests/test_local_gate.py tests/test_enterprise_governance.py -q
```

Expected: PASS.

- [ ] **Step 2: Run repository hooks and inspect formatter changes**

Run: `pre-commit run --all-files`

Expected: PASS. If Ruff reformats files, inspect `git diff` and rerun until the hook exits 0.

- [ ] **Step 3: Regenerate full coverage and prove every policy rule**

```powershell
python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-report=xml
python scripts/check_coverage_policy.py
```

Expected: full pytest PASS, global combined coverage at least 75%, package branch coverage at least
70%, and all nine risk files at least 85% combined/80% branch.

- [ ] **Step 4: Run release-sensitive gates**

```powershell
python scripts/release_gate.py
python scripts/local_gate.py
```

Expected: both commands exit 0. `local_gate.py` reports `coverage_policy` between pytest and the
offline release gate.

- [ ] **Step 5: Audit generated and unrelated files**

Run: `git status --short`

Expected: `coverage.json`, `coverage.xml`, `.coverage`, pytest temporary directories, and
`eval/reports/` are absent from the staged diff; no requirements lock or unrelated source file is
modified.

- [ ] **Step 6: Commit any verification-only formatter changes, if present**

If Step 2 produced legitimate formatting changes in Task 1-9 files:

```powershell
git add scripts rag_modules/runtime/build_jobs/locks.py tests pyproject.toml .github/workflows/ci.yml README.md docs/release_process.md
git commit -m "chore: finalize coverage policy verification"
```

If no tracked file changed, do not create an empty commit.

---

## Plan Self-Review Results

- Spec coverage: Tasks 1-3 implement strict policy parsing, normalized snapshots, ordered
  evaluation, diagnostics, and exit codes. Tasks 4-8 cover all nine risk files and the file-lock
  internal boundary. Task 9 removes legacy compatibility and updates configuration, local gate,
  CI, governance tests, and documentation. Task 10 executes every completion gate.
- Scope: no Docker, live service, dependency, lock-file, or public RAG API change is included.
- Type consistency: `CoveragePolicy`, `CoverageSnapshot`, `CoverageEvaluation`, and
  `CoverageRuleResult` names and signatures are identical across all tasks.
- Activation safety: the new engine remains dormant until the risk tests exist; the old checker and
  config are removed atomically only after a fresh full report can pass the new policy.
