# Risk-Weighted Branch Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise full-suite `rag_modules` branch coverage to at least 70%, enforce it independently, and raise combined coverage enforcement to 75% through risk-weighted behavioral tests.

**Architecture:** Add a small coverage-JSON evaluator whose threshold is configured in `pyproject.toml`, then connect it to the existing CI and local-gate sequences. Increase coverage in rings: first the seven named production hotspots, then adjacent graph/retrieval/storage paths, and finally three predetermined reserve modules only if the fresh full-suite report remains below 70.3%.

**Tech Stack:** Python 3.11, pytest 9, pytest-cov 7, coverage.py JSON reports, Pydantic-backed test configuration, GitHub Actions, Ruff, mypy, pre-commit.

## Global Constraints

- Use Python `>=3.11,<3.12`.
- Add no runtime or development dependencies.
- Keep `tool.coverage.run.branch = true`; do not add omit or exclusion rules.
- Enforce `tool.coverage.report.fail_under = 75`.
- Enforce `tool.graph_rag.coverage.rag_modules_branch_fail_under = 70`.
- Target at least 70.3% full-suite `rag_modules` branch coverage before stopping.
- Do not use DTO, protocol-instantiation, or trivial model tests to raise the metric.
- Do not call live Milvus, Neo4j, model providers, or Docker services.
- Modify production behavior only after a failing regression test demonstrates a real defect.
- Keep Ruff's Python 3.11 target, 100-character line width, import sorting, and double-quote format.
- Treat `.coverage`, `coverage.json`, caches, and `eval/reports/` as generated artifacts.

## File Structure

- Create `scripts/check_branch_coverage.py`: parse coverage JSON, aggregate package branch exits, load the configured threshold, print diagnostics, and return stable exit codes.
- Create `tests/test_branch_coverage_gate.py`: unit-test report aggregation, schema rejection, configuration, path normalization, and CLI outcomes.
- Create six first-ring test files, one per focused responsibility; keep graph evidence builder tests with the graph ranker because they share graph snapshots.
- Extend existing second-ring tests only when their current fixtures already match; otherwise create focused graph adapter tests.
- Modify `.github/workflows/ci.yml`, `scripts/local_gate.py`, `tests/test_local_gate.py`, `tests/test_enterprise_governance.py`, `README.md`, `docs/release_process.md`, `.gitignore`, and `pyproject.toml` for the dual gate.
- Modify production files only when a new failing behavior test requires a minimal defect fix.

---

### Task 1: Independent Branch Coverage Evaluator

**Files:**
- Create: `scripts/check_branch_coverage.py`
- Create: `tests/test_branch_coverage_gate.py`
- Modify: `pyproject.toml:92-101`

**Interfaces:**
- Consumes: coverage.py JSON `files.<path>.summary.covered_branches` and `num_branches`.
- Produces: `BranchCoverageResult`, `calculate_branch_coverage(payload, package)`, `load_threshold(path)`, and `main(argv=None) -> int`.

- [ ] **Step 1: Write evaluator tests before the module exists**

Create `tests/test_branch_coverage_gate.py` with the following complete test cases:

```python
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
```

- [ ] **Step 2: Run the tests and verify the expected import failure**

Run: `python -m pytest tests/test_branch_coverage_gate.py -q`

Expected: collection fails with `ModuleNotFoundError: No module named 'scripts.check_branch_coverage'`.

- [ ] **Step 3: Implement the evaluator and configure the threshold**

Create `scripts/check_branch_coverage.py`:

```python
"""Enforce package-specific branch coverage from a coverage.py JSON report."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_PATH = ROOT_DIR / "coverage.json"
DEFAULT_CONFIG_PATH = ROOT_DIR / "pyproject.toml"


@dataclass(frozen=True)
class BranchCoverageResult:
    covered_branches: int
    num_branches: int

    @property
    def percent(self) -> float:
        return 100.0 * self.covered_branches / self.num_branches


def _required_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def calculate_branch_coverage(
    payload: object,
    *,
    package: str,
) -> BranchCoverageResult:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("files"), Mapping):
        raise ValueError("coverage report must contain a files mapping")
    normalized_prefix = package.replace("\\", "/").strip("/") + "/"
    matching = []
    for filename, file_payload in payload["files"].items():
        normalized_name = str(filename).replace("\\", "/").lstrip("./")
        if normalized_name.startswith(normalized_prefix):
            matching.append(file_payload)
    if not matching:
        raise ValueError(f"coverage report contains no matching files for {package}")

    covered = 0
    total = 0
    for file_payload in matching:
        if not isinstance(file_payload, Mapping) or not isinstance(
            file_payload.get("summary"), Mapping
        ):
            raise ValueError("matching file is missing a summary mapping")
        summary = file_payload["summary"]
        covered += _required_non_negative_int(
            summary.get("covered_branches"), "covered_branches"
        )
        total += _required_non_negative_int(summary.get("num_branches"), "num_branches")
    if total == 0:
        raise ValueError(f"coverage report contains no branch data for {package}")
    if covered > total:
        raise ValueError("covered_branches cannot exceed num_branches")
    return BranchCoverageResult(covered_branches=covered, num_branches=total)


def load_threshold(path: Path) -> float:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    value = payload["tool"]["graph_rag"]["coverage"][
        "rag_modules_branch_fail_under"
    ]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("rag_modules_branch_fail_under must be numeric")
    threshold = float(value)
    if not 0.0 <= threshold <= 100.0:
        raise ValueError("rag_modules_branch_fail_under must be between 0 and 100")
    return threshold


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-json", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--package", default="rag_modules")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.coverage_json.read_text(encoding="utf-8"))
        threshold = load_threshold(args.config)
        result = calculate_branch_coverage(payload, package=args.package)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ERROR] branch coverage gate: {exc}", file=sys.stderr)
        return 2

    status = "PASS" if result.percent >= threshold else "FAIL"
    print(
        f"[{status}] {args.package} branch coverage "
        f"{result.percent:.2f}% ({result.covered_branches}/{result.num_branches}); "
        f"required {threshold:.2f}%"
    )
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Modify `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 75
precision = 2
show_missing = true
skip_covered = true

[tool.graph_rag.coverage]
rag_modules_branch_fail_under = 70
```

- [ ] **Step 4: Run evaluator tests and static checks**

Run: `python -m pytest tests/test_branch_coverage_gate.py -q`

Expected: all evaluator tests pass.

Run: `python -m ruff check scripts/check_branch_coverage.py tests/test_branch_coverage_gate.py`

Expected: exit code 0.

- [ ] **Step 5: Commit the evaluator**

```powershell
git add pyproject.toml scripts/check_branch_coverage.py tests/test_branch_coverage_gate.py
git commit -m "test: add independent branch coverage gate"
```

---

### Task 2: CI, Local Gate, Documentation, And Generated Artifacts

**Files:**
- Modify: `.github/workflows/ci.yml:48-66`
- Modify: `scripts/local_gate.py:14-115`
- Modify: `tests/test_local_gate.py:25-39,133-138`
- Modify: `tests/test_enterprise_governance.py:30-44`
- Modify: `.gitignore`
- Modify: `README.md:83-101`
- Modify: `docs/release_process.md:66-71`

**Interfaces:**
- Consumes: `scripts/check_branch_coverage.py` and `coverage.json` from Task 1.
- Produces: a five-step local gate and a separate CI branch-coverage step.

- [ ] **Step 1: Update governance tests first**

Change the expected local commands in `tests/test_local_gate.py` to:

```python
self.assertEqual(
    [step.display_command for step in steps],
    [
        ("pre-commit", "run", "--all-files"),
        ("python", "scripts/check_encoding.py"),
        (
            "python",
            "-m",
            "pytest",
            "-q",
            "--cov=rag_modules",
            "--cov=scripts",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-report=json:coverage.json",
        ),
        ("python", "scripts/check_branch_coverage.py"),
        ("python", "scripts/release_gate.py"),
    ],
)
```

Add this assertion to `tests/test_enterprise_governance.py`:

```python
def test_ci_enforces_package_branch_coverage_after_json_report() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "--cov-report=json:coverage.json" in workflow
    assert "python scripts/check_branch_coverage.py" in workflow
    assert workflow.index("--cov-report=json:coverage.json") < workflow.index(
        "python scripts/check_branch_coverage.py"
    )
```

- [ ] **Step 2: Verify the governance tests fail**

Run: `python -m pytest tests/test_local_gate.py tests/test_enterprise_governance.py -q`

Expected: failures show the current four-step local gate and missing CI branch-gate command.

- [ ] **Step 3: Implement local and CI sequencing**

Set `DEFAULT_STEP_NAMES` in `scripts/local_gate.py`:

```python
DEFAULT_STEP_NAMES = (
    "pre_commit",
    "encoding_audit",
    "pytest",
    "branch_coverage",
    "release_gate",
)
```

Replace the pytest step and insert the branch step:

```python
GateStep(
    name="pytest",
    command=(
        python_executable,
        "-m",
        "pytest",
        "-q",
        "--cov=rag_modules",
        "--cov=scripts",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-report=json:coverage.json",
    ),
    display_command=(
        "python",
        "-m",
        "pytest",
        "-q",
        "--cov=rag_modules",
        "--cov=scripts",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-report=json:coverage.json",
    ),
),
GateStep(
    name="branch_coverage",
    command=(python_executable, str(scripts_dir / "check_branch_coverage.py")),
    display_command=("python", "scripts/check_branch_coverage.py"),
),
```

Add `--cov-report=json:coverage.json` to the CI pytest command, then add:

```yaml
      - name: Package branch coverage
        run: python scripts/check_branch_coverage.py
```

- [ ] **Step 4: Ignore generated coverage files and document the policy**

Append to `.gitignore`:

```gitignore
.coverage
.coverage.*
coverage.json
coverage.xml
htmlcov/
```

Update `README.md` so the local-gate sequence explicitly lists combined coverage and package branch
coverage. Replace the Coverage Policy paragraph in `docs/release_process.md` with:

```markdown
The full suite enforces combined coverage through `tool.coverage.report.fail_under = 75` and
independently enforces `rag_modules` branch coverage at 70% through
`python scripts/check_branch_coverage.py`. Pull requests continue to enforce 80% incremental
coverage with `diff-cover`. Raise either baseline only after full-suite results remain stable; do
not lower a baseline without recording the reason in `CHANGELOG.md`.
```

- [ ] **Step 5: Run the gate-contract tests**

Run: `python -m pytest tests/test_branch_coverage_gate.py tests/test_local_gate.py tests/test_enterprise_governance.py -q`

Expected: all tests pass.

- [ ] **Step 6: Commit gate integration**

```powershell
git add .gitignore .github/workflows/ci.yml scripts/local_gate.py tests/test_local_gate.py tests/test_enterprise_governance.py README.md docs/release_process.md
git commit -m "ci: enforce package branch coverage"
```

---

### Task 3: Parent-Document Enrichment Branches

**Files:**
- Create: `tests/test_parent_doc_enricher.py`
- Test: `rag_modules/retrieval/parent_doc_enricher.py`

**Interfaces:**
- Consumes: `ParentDocumentEnricher`, `TextDocument`, `EvidenceDocument`, and `build_test_config`.
- Produces: behavioral coverage for identifier fallback, ranking limits, truncation, graph context, and metadata inheritance.

- [ ] **Step 1: Capture the failing focused coverage condition**

Run: `python -m pytest tests/test_hybrid_retrieval_runtime.py -q --cov=rag_modules.retrieval.parent_doc_enricher --cov-branch --cov-report=term-missing`

Expected: tests pass, but the report shows approximately 0/62 covered branches for the target file.

- [ ] **Step 2: Add focused parent-enrichment tests**

Create `tests/test_parent_doc_enricher.py`:

```python
from __future__ import annotations

from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument
from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.parent_doc_enricher import ParentDocumentEnricher


def _enricher(*documents: TextDocument) -> ParentDocumentEnricher:
    config = build_test_config(
        {"retrieval": {"parent_doc_top_n": 1, "parent_doc_max_chars": 5}}
    )
    return ParentDocumentEnricher(config, documents)


def test_rebuild_indexes_only_documents_with_node_ids() -> None:
    enricher = _enricher()
    mapping = enricher.rebuild(
        [
            TextDocument(content="ignored", metadata={}),
            TextDocument(content="parent", metadata={"node_id": 7}),
        ]
    )

    assert mapping == {"7": TextDocument(content="parent", metadata={"node_id": 7})}


def test_attach_respects_top_n_missing_parent_and_truncation() -> None:
    enricher = _enricher(
        TextDocument(
            content="123456",
            metadata={"node_id": "recipe-1", "recipe_name": "Mapo tofu"},
        )
    )
    docs = [
        TextDocument(content="chunk", metadata={"parent_id": "recipe-1"}),
        TextDocument(content="second", metadata={"node_id": "recipe-1"}),
        TextDocument(content="missing", metadata={"node_id": "unknown"}),
    ]

    result = enricher.attach(docs)

    assert result[0].content == "12345... (truncated parent document)"
    assert result[0].metadata == docs[0].metadata
    assert result[1] is docs[1]
    assert result[2] is docs[2]


def test_attach_evidence_fills_parent_identity_without_overwriting_child_values() -> None:
    enricher = _enricher(
        TextDocument(
            content="short",
            metadata={
                "node_id": "recipe-1",
                "recipe_id": "parent-id",
                "recipe_name": "Parent recipe",
            },
        )
    )
    inherited = EvidenceDocument(content="chunk", metadata={"parent_id": "recipe-1"})
    explicit = EvidenceDocument(
        content="chunk",
        node_id="recipe-1",
        recipe_name="Child recipe",
    )

    first, second = enricher.attach_evidence([inherited, explicit], top_n=2)

    assert first.node_id == "recipe-1"
    assert first.recipe_name == "Parent recipe"
    assert first.metadata["recipe_name"] == "Parent recipe"
    assert second.recipe_name == "Child recipe"


def test_graph_enrichment_finds_parent_by_recipe_lists_and_preserves_graph_source() -> None:
    enricher = _enricher(
        TextDocument(
            content="parent",
            metadata={"node_id": "recipe-1", "recipe_name": "Mapo tofu"},
        )
    )
    by_id = TextDocument(
        content="graph detail",
        metadata={"recipe_node_ids": ["missing", "recipe-1"], "search_type": "path"},
    )
    by_name = TextDocument(
        content="parent",
        metadata={"recipe_names": ["Mapo tofu"], "search_source": "graph"},
    )

    first, second = enricher.enrich_graph_documents([by_id, by_name], top_n=2)

    assert "[Graph retrieval evidence]" in first.content
    assert first.metadata["search_source"] == "path"
    assert second.content == "parent"
    assert second.metadata["search_source"] == "graph"


def test_graph_evidence_returns_originals_for_empty_input_or_missing_parent() -> None:
    empty = _enricher()
    docs = [EvidenceDocument(content="graph", metadata={"recipe_name": "unknown"})]

    assert empty.enrich_graph_evidence_documents(docs) is docs
    populated = _enricher(TextDocument(content="parent", metadata={"node_id": "recipe-1"}))
    assert populated.enrich_graph_evidence_documents(docs)[0] is docs[0]
```

- [ ] **Step 3: Run focused tests and inspect branch delta**

Run: `python -m pytest tests/test_parent_doc_enricher.py -q --cov=rag_modules.retrieval.parent_doc_enricher --cov-branch --cov-report=term-missing`

Expected: all tests pass and the target file covers the empty, hit, miss, top-N, graph-context, and truncation branches.

- [ ] **Step 4: Run adjacent retrieval tests**

Run: `python -m pytest tests/test_parent_doc_enricher.py tests/test_hybrid_retrieval_runtime.py tests/test_hybrid_retrieval_executor.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit parent-enrichment tests**

```powershell
git add tests/test_parent_doc_enricher.py
git commit -m "test: cover parent document enrichment branches"
```

---

### Task 4: Milvus Writer Success And Failure Paths

**Files:**
- Create: `tests/test_milvus_writer.py`
- Test: `rag_modules/infra/milvus/writer.py`

**Interfaces:**
- Consumes: `_MilvusWriterOperations` and `TextDocument`.
- Produces: deterministic fake embedding and client hosts for write-path tests.

- [ ] **Step 1: Record the current missing writer branches**

Run: `python -m pytest tests/test_milvus_blue_green.py -q --cov=rag_modules.infra.milvus.writer --cov-branch --cov-report=term-missing`

Expected: the existing tests pass while the writer report remains near 0/16 covered branches.

- [ ] **Step 2: Add a complete fake host and behavior tests**

Create `tests/test_milvus_writer.py`:

```python
from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_modules.infra.milvus.writer import _MilvusWriterOperations
from rag_modules.kernel.documents import TextDocument


class _Embeddings:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.texts: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.error:
            raise self.error
        self.texts = list(texts)
        return [[float(index)] for index, _ in enumerate(texts)]


class _Client:
    def __init__(self) -> None:
        self.inserted: list[tuple[str, list[dict[str, object]]]] = []
        self.flushed: list[str] = []
        self.loaded: list[str] = []

    def insert(self, *, collection_name: str, data: list[dict[str, object]]) -> None:
        self.inserted.append((collection_name, data))

    def flush(self, *, collection_name: str) -> None:
        self.flushed.append(collection_name)

    def load_collection(self, collection_name: str) -> None:
        self.loaded.append(collection_name)


class _Writer(_MilvusWriterOperations):
    def __init__(self) -> None:
        self.collection_name = "recipes"
        self.build_collection_name = ""
        self.collection_created = True
        self.client = _Client()
        self.embeddings = _Embeddings()
        self.create_collection_result = True
        self.create_index_result = True

    def create_collection(self, force_recreate=False, *, collection_name=None) -> bool:
        assert force_recreate is True
        return self.create_collection_result

    def create_index(self, *, collection_name=None) -> bool:
        return self.create_index_result


def _chunk(content: str = "content", **metadata: object) -> TextDocument:
    return TextDocument(content=content, metadata=dict(metadata))


def test_build_vector_index_rejects_empty_chunks() -> None:
    with pytest.raises(ValueError):
        _Writer().build_vector_index([])


def test_build_vector_index_writes_sanitized_entities_to_explicit_collection() -> None:
    writer = _Writer()
    chunks = [
        _chunk(
            "x" * 15001,
            chunk_id="c" * 151,
            node_id="recipe-1",
            recipe_name="Mapo tofu",
            difficulty="3",
        ),
        _chunk("second"),
    ]

    with patch("rag_modules.infra.milvus.writer.time.sleep") as sleep:
        assert writer.build_vector_index(chunks, collection_name="recipes__green") is True

    assert writer.collection_name == "recipes__green"
    assert writer.build_collection_name == "recipes__green"
    assert writer.embeddings.texts == [chunk.page_content for chunk in chunks]
    assert len(writer.client.inserted[0][1][0]["id"]) == 150
    assert len(writer.client.inserted[0][1][0]["text"]) == 15000
    assert writer.client.flushed == ["recipes__green"]
    assert writer.client.loaded == ["recipes__green"]
    sleep.assert_called_once_with(2)


@pytest.mark.parametrize("failed_stage", ["collection", "index"])
def test_build_vector_index_returns_false_for_setup_failures(failed_stage: str) -> None:
    writer = _Writer()
    if failed_stage == "collection":
        writer.create_collection_result = False
    else:
        writer.create_index_result = False

    with patch("rag_modules.infra.milvus.writer.time.sleep"):
        assert writer.build_vector_index([_chunk()]) is False


def test_build_vector_index_degrades_embedding_failure() -> None:
    writer = _Writer()
    writer.embeddings = _Embeddings(error=RuntimeError("provider failed"))

    assert writer.build_vector_index([_chunk()]) is False


def test_add_documents_requires_existing_collection_and_inserts_defaults() -> None:
    writer = _Writer()
    writer.collection_created = False
    with pytest.raises(ValueError):
        writer.add_documents([_chunk()])

    writer.collection_created = True
    with patch("rag_modules.infra.milvus.writer.time.time", return_value=123):
        assert writer.add_documents([_chunk()]) is True
    entity = writer.client.inserted[-1][1][0]
    assert entity["id"] == "new_chunk_0_123"
    assert entity["chunk_id"] == "new_chunk_0_123"


def test_add_documents_degrades_client_failure() -> None:
    writer = _Writer()
    writer.client.insert = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("insert failed"))

    assert writer.add_documents([_chunk()]) is False
```

- [ ] **Step 3: Run writer tests and adjacent Milvus tests**

Run: `python -m pytest tests/test_milvus_writer.py tests/test_milvus_blue_green.py -q --cov=rag_modules.infra.milvus.writer --cov-branch --cov-report=term-missing`

Expected: tests pass and all major writer decision families are covered.

- [ ] **Step 4: Commit Milvus writer tests**

```powershell
git add tests/test_milvus_writer.py
git commit -m "test: cover Milvus writer branches"
```

---

### Task 5: Graph Ranking And Evidence Construction

**Files:**
- Create: `tests/test_graph_path_ranker.py`
- Modify: `tests/test_graph_reasoning_strategy.py`
- Test: `rag_modules/graph/path_ranker.py`
- Test: `rag_modules/graph/evidence_builder.py`

**Interfaces:**
- Consumes: `GraphDocumentRanker`, `GraphEvidenceBuilder`, graph snapshots, and `EvidenceDocument`.
- Produces: tests for scoring fallbacks, de-duplication keys, evidence merging, empty graph shapes, and relationship limits.

- [ ] **Step 1: Capture the initial focused branch report**

Run: `python -m pytest tests/test_graph_reasoning_strategy.py -q --cov=rag_modules.graph.path_ranker --cov=rag_modules.graph.evidence_builder --cov-branch --cov-report=term-missing`

Expected: existing evidence-builder tests pass; `path_ranker.py` remains near 0/24 branch coverage.

- [ ] **Step 2: Add ranker tests**

Create `tests/test_graph_path_ranker.py` with these tests and helpers:

```python
from __future__ import annotations

from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument
from rag_modules.graph.path_ranker import GraphDocumentRanker


def _ranker() -> GraphDocumentRanker:
    return GraphDocumentRanker(build_test_config().graph)


def test_rank_rewards_semantic_relationships_recipe_identity_and_query_overlap() -> None:
    rich = EvidenceDocument(
        content="pepper aroma",
        recipe_name="Mapo tofu",
        score=0.1,
        evidence_units=[{"claim": "aroma"}],
        graph_evidence={"relationships": [{"type": "CONTRIBUTES_TO"}]},
        metadata={"recipe_node_ids": ["r1"], "relevance_score": 0.2},
    )
    plain = EvidenceDocument(content="unrelated", score=0.2)

    assert _ranker().rank([plain, rich], "pepper")[0] is rich


def test_score_uses_semantic_count_fallback_and_handles_empty_query() -> None:
    document = EvidenceDocument(
        content="graph",
        graph_evidence={"semantic_relationship_count": 2},
        metadata={"final_score": 0.5, "recipe_names": ["Mapo tofu"]},
    )

    assert _ranker()._score(document, "") > 0.5


def test_dedupe_merges_duplicate_recipe_evidence_without_reordering() -> None:
    first = EvidenceDocument(
        content="first",
        score=0.2,
        metadata={"recipe_node_ids": ["r1"], "relationship_count": 1},
    )
    duplicate = EvidenceDocument(
        content="second",
        score=0.9,
        graph_evidence={"description": "path"},
        metadata={"recipe_node_ids": ["r1"], "relationship_count": 3},
    )
    by_name = EvidenceDocument(
        content="third",
        metadata={"recipe_names": ["Other"]},
    )

    merged = _ranker().dedupe([first, duplicate, by_name])

    assert [doc.content for doc in merged] == ["first\nsecond", "third"]
    assert merged[0].score == 0.9
    assert merged[0].metadata["relationship_count"] == 3
    assert merged[0].metadata["merged_graph_evidence"] == [{"description": "path"}]


def test_dedupe_keeps_identical_or_empty_duplicate_content_once() -> None:
    first = EvidenceDocument(content="same", recipe_name="Recipe")
    duplicate = EvidenceDocument(content="same", recipe_name="Recipe")

    [merged] = _ranker().dedupe([first, duplicate])

    assert merged.content == "same"
    assert "merged_graph_evidence" not in merged.metadata
```

- [ ] **Step 3: Extend evidence-builder boundary tests**

Append to `tests/test_graph_reasoning_strategy.py`:

```python
def test_evidence_builder_handles_empty_paths_and_relationship_defaults() -> None:
    builder = GraphEvidenceBuilder()
    empty = GraphPath()
    assert builder.build_path_description(empty)

    path = GraphPath(
        nodes=[
            GraphNodeSnapshot(node_id="r1", name="Recipe", labels=("Recipe",)),
            GraphNodeSnapshot(node_id="i1", name="Pepper", labels=("Ingredient",)),
        ],
        relationships=[
            GraphRelationshipSnapshot(start_node_id="r1", end_node_id="i1")
        ],
    )
    assert "RELATED" in builder.build_path_description(path)


def test_relationship_lines_deduplicate_and_respect_limit() -> None:
    builder = GraphEvidenceBuilder()
    relation = GraphRelationshipSnapshot(
        relation_type="USES",
        start_node_id="r1",
        end_node_id="i1",
    )
    subgraph = KnowledgeSubgraph(
        central_nodes=[GraphNodeSnapshot(node_id="r1", name="Recipe")],
        connected_nodes=[GraphNodeSnapshot(node_id="i1", name="Pepper")],
        relationships=[relation, relation],
    )

    assert builder.relationship_lines(subgraph, limit=1) == ["Recipe -[USES]-> Pepper"]


def test_subgraph_description_and_evidence_use_fallback_identity() -> None:
    builder = GraphEvidenceBuilder()
    subgraph = KnowledgeSubgraph(graph_metrics={"density": 0.25})

    [document] = builder.subgraph_to_evidence(subgraph, ["chain"], "query")

    assert document.node_id == ""
    assert document.score == 0.25
    assert document.recipe_graph_evidence["reasoning_chains"] == ["chain"]
```

- [ ] **Step 4: Run focused and adjacent graph tests**

Run: `python -m pytest tests/test_graph_path_ranker.py tests/test_graph_reasoning_strategy.py -q --cov=rag_modules.graph.path_ranker --cov=rag_modules.graph.evidence_builder --cov-branch --cov-report=term-missing`

Expected: all tests pass and both files show material branch gains.

- [ ] **Step 5: Commit graph ranking tests**

```powershell
git add tests/test_graph_path_ranker.py tests/test_graph_reasoning_strategy.py
git commit -m "test: cover graph ranking and evidence branches"
```

---

### Task 6: Vector Retriever And Neo4j Fallback Adapters

**Files:**
- Create: `tests/test_vector_retriever.py`
- Create: `tests/test_neo4j_fallback_retriever.py`
- Test: `rag_modules/retrieval/adapters/vector_retriever.py`
- Test: `rag_modules/retrieval/adapters/neo4j_fallback_retriever.py`

**Interfaces:**
- Consumes: `RetrievalRequest`, `VectorRetriever`, and `Neo4jFallbackRetriever`.
- Produces: shared faithful fake session/driver patterns for success, invalid data, timeout, and degradation behavior.

- [ ] **Step 1: Capture the adapter branch deficit**

Run: `python -m pytest tests/test_dual_level_retriever.py -q --cov=rag_modules.retrieval.adapters.vector_retriever --cov=rag_modules.retrieval.adapters.neo4j_fallback_retriever --cov-branch --cov-report=term-missing`

Expected: existing tests pass while both adapter files remain near 0% branch coverage.

- [ ] **Step 2: Create vector retriever tests**

Create `tests/test_vector_retriever.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from rag_modules.contracts import RetrievalRequest
from rag_modules.retrieval.adapters.vector_retriever import VectorRetriever


class _Milvus:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = list(results or [])
        self.error = error

    def similarity_search(self, request):
        if self.error:
            raise self.error
        return list(self.results)


class _Session:
    def __init__(self, records=None, error: Exception | None = None) -> None:
        self.records = list(records or [])
        self.error = error
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, parameters, **kwargs):
        self.calls.append((parameters, kwargs))
        if self.error:
            raise self.error
        return self.records


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


class _Control:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1

    def remaining_seconds(self) -> float:
        return 2.5


def test_search_enriches_neighbors_coerces_metadata_and_limits_candidates() -> None:
    session = _Session([{"nid": "r1", "names": ["Pepper", "", "Tofu", "Sauce", "Oil"]}])
    retriever = VectorRetriever(
        _Milvus(
            [
                {
                    "text": "chunk",
                    "score": "0.8",
                    "metadata": {"node_id": "r1", "name": "Mapo tofu"},
                },
                {"text": "second", "score": "bad", "metadata": "invalid"},
            ]
        ),
        _Driver(session),
    )
    control = _Control()
    request = RetrievalRequest.from_inputs(
        query="tofu", top_k=1, candidate_k=1, control=control
    )

    [document] = retriever.search(request)

    assert document.node_id == "r1"
    assert document.recipe_name == "Mapo tofu"
    assert document.score == 0.8
    assert "Pepper, Tofu, Sauce" in document.content
    assert session.calls[0][1]["timeout"] == 2.5
    assert control.checks >= 3


def test_search_returns_empty_for_provider_failure_or_no_results() -> None:
    request = RetrievalRequest.from_inputs(query="tofu")
    assert VectorRetriever(_Milvus(error=RuntimeError("down"))).search(request) == []
    assert VectorRetriever(_Milvus()).search(request) == []


def test_neighbor_enrichment_is_optional_and_degrades_query_failure() -> None:
    request = RetrievalRequest.from_inputs(query="tofu")
    result = [{"text": "chunk", "metadata": {"node_id": "r1"}}]

    assert VectorRetriever(_Milvus(result)).search(request)[0].content == "chunk"
    failing = VectorRetriever(_Milvus(result), _Driver(_Session(error=RuntimeError("down"))))
    assert failing.search(request)[0].content == "chunk"


def test_batch_neighbors_returns_empty_for_missing_driver_or_ids() -> None:
    retriever = VectorRetriever(_Milvus())
    request = RetrievalRequest.from_inputs(query="tofu")

    assert retriever._batch_get_neighbors(request, []) == {}
    assert retriever._batch_get_neighbors(request, ["r1"]) == {}
```

- [ ] **Step 3: Create Neo4j fallback tests**

Create `tests/test_neo4j_fallback_retriever.py`:

```python
from __future__ import annotations

from rag_modules.retrieval.adapters.neo4j_fallback_retriever import Neo4jFallbackRetriever


class _Session:
    def __init__(self, entity=None, topic=None, neighbors=None, error=None) -> None:
        self.entity = list(entity or [])
        self.topic = list(topic or [])
        self.neighbors = list(neighbors or [])
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, parameters):
        if self.error:
            raise self.error
        if "fulltext" in query:
            return self.entity
        if "matched_keyword" in query:
            return self.topic
        return self.neighbors


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


def test_entity_search_builds_partial_records_and_coerces_scores() -> None:
    retriever = Neo4jFallbackRetriever(
        driver=_Driver(
            _Session(
                entity=[
                    {
                        "node_id": "r1",
                        "name": "Mapo tofu",
                        "description": "spicy",
                        "labels": ["Recipe", ""],
                        "score": "0.5",
                    },
                    {
                        "node_id": "r2",
                        "name": "",
                        "description": "fallback",
                        "labels": "invalid",
                        "score": object(),
                    },
                ]
            )
        ),
        database="neo4j",
    )

    first, second = retriever.entity_search(["tofu"], 2)

    assert first.score == 0.35
    assert first.metadata["labels"] == ["Recipe"]
    assert second.score == 0.0
    assert second.metadata["labels"] == []


def test_topic_search_includes_optional_fields_and_filters_ingredients() -> None:
    record = {
        "node_id": "r1",
        "name": "Mapo tofu",
        "category": "main",
        "cuisine_type": "Sichuan",
        "difficulty": 2,
        "ingredients": ["tofu", "", "pepper", "oil"],
        "matched_keyword": "Sichuan",
    }
    retriever = Neo4jFallbackRetriever(
        driver=_Driver(_Session(topic=[record])), database="neo4j"
    )

    [document] = retriever.topic_search(["Sichuan"], 1)

    assert document.score == 0.75
    assert document.matched_terms == ["Sichuan"]
    assert "tofu" in document.content


def test_guards_neighbors_and_failures_return_empty() -> None:
    no_driver = Neo4jFallbackRetriever(driver=None, database="neo4j")
    assert no_driver.entity_search([], 1) == []
    assert no_driver.topic_search(["x"], 0) == []
    assert no_driver.node_neighbors("") == []

    success = Neo4jFallbackRetriever(
        driver=_Driver(_Session(neighbors=[{"name": "Pepper"}, {"name": ""}])),
        database="neo4j",
    )
    assert success.node_neighbors("r1") == ["Pepper"]

    failing = Neo4jFallbackRetriever(
        driver=_Driver(_Session(error=RuntimeError("down"))), database="neo4j"
    )
    assert failing.entity_search(["x"], 1) == []
    assert failing.topic_search(["x"], 1) == []
    assert failing.node_neighbors("r1") == []
```

- [ ] **Step 4: Run adapter and adjacent tests**

Run: `python -m pytest tests/test_vector_retriever.py tests/test_neo4j_fallback_retriever.py tests/test_dual_level_retriever.py tests/test_hybrid_retrieval_runtime.py -q --cov=rag_modules.retrieval.adapters.vector_retriever --cov=rag_modules.retrieval.adapters.neo4j_fallback_retriever --cov-branch --cov-report=term-missing`

Expected: all tests pass and success, guard, invalid-data, timeout, and exception branches are covered.

- [ ] **Step 5: Commit retrieval adapter tests**

```powershell
git add tests/test_vector_retriever.py tests/test_neo4j_fallback_retriever.py
git commit -m "test: cover vector and Neo4j fallback branches"
```

---

### Task 7: Graph Evidence Orchestration

**Files:**
- Create: `tests/test_graph_evidence_orchestrator.py`
- Test: `rag_modules/graph/evidence_orchestrator.py`

**Interfaces:**
- Consumes: `GraphEvidenceOrchestrator`, `GraphRetrievalPlan`, `GraphQuery`, graph DTOs, and `RetrievalRequest`.
- Produces: fake executor/postprocessor/reasoner fixtures that exercise path, subgraph, trace, cancellation, and degradation branches.

- [ ] **Step 1: Record the current orchestrator branch report**

Run: `python -m pytest tests/test_graph_retrieval_executor.py -q --cov=rag_modules.graph.evidence_orchestrator --cov-branch --cov-report=term-missing`

Expected: existing executor tests pass while the orchestrator remains near 17/76 covered branches.

- [ ] **Step 2: Add orchestrator fixtures and dispatch tests**

Create `tests/test_graph_evidence_orchestrator.py` with:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag_modules.contracts import EvidenceDocument, GraphQueryType, RetrievalRequest
from rag_modules.contracts.graph import GraphQuery
from rag_modules.graph.evidence_orchestrator import GraphEvidenceOrchestrator
from rag_modules.graph.reasoning_strategy import GraphReasoningOutcome
from rag_modules.graph.retrieval_plan import GraphRetrievalPlan
from rag_modules.graph.retrieval_types import GraphPath, KnowledgeSubgraph


class _Executor:
    def __init__(self, *, driver=object(), error: Exception | None = None) -> None:
        self.driver = driver
        self.error = error
        self.calls: list[str] = []

    def _records(self, name: str):
        self.calls.append(name)
        if self.error:
            raise self.error
        return [{"kind": name}, None]

    def shortest_paths(self, plan, *, control=None):
        return self._records("shortest")

    def entity_relation_paths(self, plan, *, control=None):
        return self._records("entity")

    def multi_hop_paths(self, plan, *, control=None):
        return self._records("multi")

    def subgraphs(self, plan, *, control=None):
        return self._records("subgraph")


class _Postprocessor:
    def parse_neo4j_path(self, record, path_type="multi_hop"):
        if record is None:
            return None
        return GraphPath(path_type=path_type)

    def build_knowledge_subgraph(self, record):
        return KnowledgeSubgraph(graph_metrics={"density": 0.5})

    def merge_subgraphs(self, subgraphs):
        return subgraphs[0]

    def to_ranked_evidence_documents(self, documents, query):
        return list(reversed(documents))

    def paths_to_evidence_documents(self, paths, query):
        return [EvidenceDocument(content=path.path_type, evidence_units=[{"claim": query}]) for path in paths]

    def subgraph_to_evidence_documents(self, subgraph, reasoning_chains, query):
        return [EvidenceDocument(content=query, metadata={"chains": reasoning_chains})]

    def build_path_description(self, path):
        return path.path_type

    def build_subgraph_description(self, subgraph):
        return "subgraph"

    def summarize_subgraph_evidence(self, subgraph):
        return {"density": subgraph.graph_metrics.get("density", 0.0)}

    def relationship_lines(self, subgraph, limit=30):
        return [str(limit)]

    def empty_subgraph(self):
        return KnowledgeSubgraph()


class _Reasoner:
    def reason(self, subgraph, query):
        return GraphReasoningOutcome(patterns=["causal"], validated_chains=[query])

    def identify_reasoning_patterns(self, subgraph, query):
        return ["causal"]

    def build_reasoning_chains(self, pattern, subgraph, query):
        return [pattern] if pattern else []


def _orchestrator(executor=None) -> GraphEvidenceOrchestrator:
    return GraphEvidenceOrchestrator(
        graph_plan_builder=SimpleNamespace(build=lambda query, evidence_goals: None),
        graph_executor=executor or _Executor(),
        postprocessor=_Postprocessor(),
        reasoning_strategy=_Reasoner(),
    )


def _plan(query_type: GraphQueryType) -> GraphRetrievalPlan:
    return GraphRetrievalPlan(query_type=query_type.value, source_entities=["tofu"])


@pytest.mark.parametrize(
    "query_type, expected_call, expected_path_type",
    [
        (GraphQueryType.PATH_FINDING, "shortest", "shortest_path"),
        (GraphQueryType.ENTITY_RELATION, "entity", "entity_relation"),
        (GraphQueryType.MULTI_HOP, "multi", "multi_hop"),
    ],
)
def test_execute_graph_plan_dispatches_and_skips_unparseable_records(
    query_type, expected_call, expected_path_type
) -> None:
    orchestrator = _orchestrator()

    [path] = orchestrator.execute_graph_plan(_plan(query_type))

    assert orchestrator.graph_executor.calls == [expected_call]
    assert path.path_type == expected_path_type


def test_extract_subgraph_handles_disconnected_empty_success_and_error() -> None:
    assert _orchestrator(_Executor(driver=None)).extract_knowledge_subgraph(
        _plan(GraphQueryType.SUBGRAPH)
    ) == KnowledgeSubgraph()

    merged = _orchestrator().extract_knowledge_subgraph(_plan(GraphQueryType.SUBGRAPH))
    assert merged.graph_metrics == {"density": 0.5}

    failed = _orchestrator(_Executor(error=RuntimeError("down"))).extract_knowledge_subgraph(
        _plan(GraphQueryType.SUBGRAPH)
    )
    assert failed == KnowledgeSubgraph()


def test_reasoning_degrades_ordinary_errors_and_validates_unique_chains() -> None:
    orchestrator = _orchestrator()
    orchestrator.reasoning_strategy.reason = lambda subgraph, query: (_ for _ in ()).throw(
        RuntimeError("bad reasoning")
    )

    assert orchestrator.reason_over_subgraph(KnowledgeSubgraph(), "query") == GraphReasoningOutcome()
    assert orchestrator.validate_reasoning_chains([" a ", "", "a", "b", "c", "d"], "q") == [
        "a",
        "b",
        "c",
    ]
```

- [ ] **Step 3: Add retrieval path, subgraph, and empty-query-type tests**

Append to the same file:

```python
def _event_recorder(events):
    def record(trace, name, **kwargs):
        events.append((name, kwargs["details"]))

    return record


@pytest.mark.parametrize(
    "query_type",
    [GraphQueryType.MULTI_HOP, GraphQueryType.PATH_FINDING, GraphQueryType.ENTITY_RELATION],
)
def test_retrieve_path_queries_rank_truncate_and_record_counts(query_type) -> None:
    orchestrator = _orchestrator()
    events = []
    trace = SimpleNamespace(path_count=0)
    request = RetrievalRequest.from_inputs(query="why", top_k=1)
    graph_query = GraphQuery(query_type=query_type, source_entities=["tofu"])

    result = orchestrator.retrieve(
        request=request,
        graph_query=graph_query,
        retrieval_plan=_plan(query_type),
        trace=trace,
        record_event=_event_recorder(events),
    )

    assert len(result.final_documents) == 1
    assert result.evidence_unit_count == 1
    assert trace.path_count == 1
    assert [name for name, _ in events] == [
        "execute_graph_paths",
        "rank_graph_evidence_documents",
    ]


@pytest.mark.parametrize("query_type", [GraphQueryType.SUBGRAPH, GraphQueryType.CLUSTERING])
def test_retrieve_subgraph_queries_record_reasoning(query_type) -> None:
    orchestrator = _orchestrator()
    events = []
    trace = SimpleNamespace(subgraph_count=0, reasoning_patterns=[], reasoning_chain_count=0)

    result = orchestrator.retrieve(
        request=RetrievalRequest.from_inputs(query="why", top_k=2),
        graph_query=GraphQuery(query_type=query_type, source_entities=["tofu"]),
        retrieval_plan=_plan(query_type),
        trace=trace,
        record_event=_event_recorder(events),
    )

    assert result.final_documents[0].metadata["chains"] == ["why"]
    assert trace.reasoning_patterns == ["causal"]
    assert trace.reasoning_chain_count == 1


def test_execute_graph_evidence_returns_empty_for_unknown_query_type() -> None:
    orchestrator = _orchestrator()
    request = RetrievalRequest.from_inputs(query="query")
    graph_query = SimpleNamespace(query_type=SimpleNamespace(value="unknown"))

    assert orchestrator._execute_graph_evidence(
        request=request,
        graph_query=graph_query,
        retrieval_plan=_plan(GraphQueryType.MULTI_HOP),
        trace=SimpleNamespace(),
        record_event=lambda *args, **kwargs: None,
    ) == []
```

- [ ] **Step 4: Run focused and graph-executor tests**

Run: `python -m pytest tests/test_graph_evidence_orchestrator.py tests/test_graph_retrieval_executor.py -q --cov=rag_modules.graph.evidence_orchestrator --cov-branch --cov-report=term-missing`

Expected: all tests pass and dispatch, fallback, path, subgraph, ranking, and trace branches are covered.

- [ ] **Step 5: Commit orchestrator tests**

```powershell
git add tests/test_graph_evidence_orchestrator.py
git commit -m "test: cover graph evidence orchestration branches"
```

---

### Task 8: Second-Ring Graph Reasoning, Semantic Writes, Entity Linking, And Graph KV

**Files:**
- Modify: `tests/test_graph_reasoning_strategy.py`
- Modify: `tests/test_semantic_graph_writer.py`
- Create: `tests/test_graph_retrieval_adapters.py`
- Test: `rag_modules/graph/reasoning_strategy.py`
- Test: `rag_modules/infra/semantic_graph_writer.py`
- Test: `rag_modules/graph/entity_linker.py`
- Test: `rag_modules/retrieval/adapters/graph_kv_retriever.py`

**Interfaces:**
- Consumes: existing graph snapshots, policy-backed reasoner, semantic writer rows, `EntityLinker`, and `GraphKVRetriever`.
- Produces: second-ring branch gains in graph decisions without live Neo4j.

- [ ] **Step 1: Add reasoning branch cases**

Append these tests to `tests/test_graph_reasoning_strategy.py`:

```python
def test_reasoning_builds_causal_compositional_comparative_and_connectivity_chains() -> None:
    strategy = GraphReasoningStrategy()
    causal = next(iter(strategy.causal_relation_types))
    nodes = [
        GraphNodeSnapshot(node_id="r1", name="A", labels=("Recipe",)),
        GraphNodeSnapshot(node_id="r2", name="B", labels=("Recipe",)),
        GraphNodeSnapshot(node_id="t1", name="Fry", labels=("Technique",)),
        GraphNodeSnapshot(node_id="f1", name="Spicy", labels=("Flavor",)),
    ]
    subgraph = KnowledgeSubgraph(
        central_nodes=nodes[:2],
        connected_nodes=nodes[2:],
        relationships=[
            GraphRelationshipSnapshot(
                relation_type=causal, start_node_id="r1", end_node_id="f1"
            )
        ],
    )

    outcome = strategy.reason(subgraph, "compare spicy")

    assert {"causal", "compositional", "comparative"}.issubset(outcome.patterns)
    assert outcome.validated_chains
    assert outcome.summary["central_node_count"] == 2

    connectivity = KnowledgeSubgraph(
        central_nodes=[nodes[0]],
        relationships=[GraphRelationshipSnapshot(relation_type="RELATED")],
    )
    assert strategy.identify_reasoning_patterns(connectivity, "") == ["connectivity"]


def test_reasoning_validation_deduplicates_ranks_and_limits_four() -> None:
    strategy = GraphReasoningStrategy()
    result = strategy.validate_reasoning_chains(
        ["", "plain", "query semantic", "plain", "longer chain", "four", "five"],
        "query",
        KnowledgeSubgraph(
            connected_nodes=[GraphNodeSnapshot(name="semantic", labels=("Flavor",))]
        ),
    )

    assert result[0] == "query semantic"
    assert len(result) == 4
```

- [ ] **Step 2: Add semantic writer normalization and lifecycle cases**

Append to `tests/test_semantic_graph_writer.py`:

```python
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.kernel.documents import TextDocument


def test_build_rows_skips_invalid_recipes_and_normalizes_relation_families() -> None:
    writer = SemanticGraphSchemaWriter(build_test_config())
    rows = writer._build_rows(
        [
            TextDocument(content="ignored", metadata={}),
            TextDocument(
                content="recipe",
                metadata={
                    "node_id": "r1",
                    "recipe_name": "Mapo tofu",
                    "semantic_relations": {
                        "HAS_FLAVOR": [" spicy ", "spicy", ""],
                        "CONTRIBUTES_TO": [
                            {"effect": "aroma", "causes": ["pepper", "pepper", ""]},
                            {"effect": ""},
                        ],
                        "INGREDIENT_CONTRIBUTES_TO": [
                            {"source": "pepper", "effect": "heat"},
                            {"source": "", "effect": "ignored"},
                        ],
                    },
                },
            ),
        ]
    )

    assert rows[0]["recipe_id"] == "r1"
    assert [item["name"] for item in rows[0]["relations"]] == ["spicy", "aroma", "heat"]
    assert rows[0]["relations"][1]["causes"] == ["pepper"]


def test_persist_guards_disabled_empty_and_closes_owned_driver(monkeypatch) -> None:
    disabled = SemanticGraphSchemaWriter(
        build_test_config({"graph": {"enable_semantic_graph_schema": False}})
    )
    assert disabled.persist_from_documents([TextDocument(content="x")]) == {
        "recipes": 0,
        "nodes": 0,
        "relationships": 0,
    }

    enabled = SemanticGraphSchemaWriter(build_test_config())
    assert enabled.persist_from_documents([]) == {"recipes": 0, "nodes": 0, "relationships": 0}
```

- [ ] **Step 3: Add graph KV scoring and interleaving tests**

Create `tests/test_graph_retrieval_adapters.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field

from rag_modules.retrieval.adapters.graph_kv_retriever import GraphKVRetriever


@dataclass
class _Entity:
    entity_name: str
    entity_type: str = "Recipe"
    index_keys: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    value_content: str = "content"


@dataclass
class _Relation:
    relation_id: str
    relation_type: str = "RELATED"
    source_entity: str = "r1"
    target_entity: str = "i1"
    index_keys: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    value_content: str = "relation"


class _Index:
    def __init__(self, entities=(), relations=()) -> None:
        self.entities = list(entities)
        self.relations = list(relations)

    def get_entities_by_key(self, key):
        return self.entities

    def get_relations_by_key(self, key):
        return self.relations


def test_graph_kv_guards_scores_deduplicates_and_interleaves() -> None:
    assert GraphKVRetriever(None).search(["tofu"]) == []
    assert GraphKVRetriever(_Index()).entity_search([]) == []

    index = _Index(
        entities=[
            _Entity("tofu", index_keys=("tofu",), metadata={"node_id": "r1", "degree": 12}),
            _Entity("tofu", index_keys=("tofu",)),
            _Entity("unmatched", index_keys=("other",), metadata={"degree": "bad"}),
        ],
        relations=[
            _Relation("rel-1", index_keys=("tofu",), metadata={"source_name": "Mapo tofu"}),
            _Relation("rel-1", index_keys=("tofu",)),
        ],
    )

    results = GraphKVRetriever(index).search(["tofu"], top_k=2)

    assert [document.retrieval_level for document in results] == ["entity", "topic"]
    assert results[0].score <= 1.0
    assert results[1].recipe_name == "Mapo tofu"
```

Add these `EntityLinker` fakes and tests to the same file:

```python
from rag_modules.graph.entity_linker import EntityLinkContext, EntityLinker


class _LinkSession:
    def __init__(self, records=(), error: Exception | None = None) -> None:
        self.records = list(records)
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query, **kwargs):
        if self.error:
            raise self.error
        return self.records


class _LinkDriver:
    def __init__(self, session: _LinkSession) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


def test_entity_linker_guards_empty_input_and_returns_unresolved_without_driver() -> None:
    linker = EntityLinker(driver=None, database="neo4j")


    assert linker.link_many([]) == []
    unresolved = linker.link_many([" tofu ", "tofu", ""])

    assert len(unresolved) == 1
    assert unresolved[0].text == "tofu"
    assert unresolved[0].confidence == 0.0


def test_entity_linker_prefers_exact_contextual_candidates_and_deduplicates() -> None:
    records = [
        {
            "node_id": "tofu",
            "name": "Tofu",
            "category": "ingredient",
            "labels": ["Ingredient"],
            "match_score": 1.0,
            "degree": 200,
        },
        {
            "node_id": "tofu",
            "name": "Tofu duplicate",
            "category": "ingredient",
            "labels": ["Ingredient"],
            "match_score": 0.9,
            "degree": 1,
        },
        {
            "node_id": "recipe-1",
            "name": "Tofu",
            "category": "main",
            "labels": ["Recipe"],
            "match_score": 0.95,
            "degree": 10,
        },
    ]
    linker = EntityLinker(driver=_LinkDriver(_LinkSession(records)), database="neo4j")
    context = EntityLinkContext(query_type="entity_relation", entity_role="source")

    linked = linker.link_many(["tofu"], context=context)

    assert linked[0].node_id == "tofu"
    assert linked[0].match_reason == "node_id"
    assert len({candidate.node_id for candidate in linked}) == len(linked)


def test_entity_linker_degrades_driver_failure_to_unresolved_result() -> None:
    linker = EntityLinker(
        driver=_LinkDriver(_LinkSession(error=RuntimeError("neo4j down"))),
        database="neo4j",
    )

    [linked] = linker.link_many(["tofu"])

    assert linked.text == "tofu"
    assert linked.node_id == ""
    assert linked.confidence == 0.0
```

- [ ] **Step 4: Run the second-ring graph slice and inspect missing branches**

Run: `python -m pytest tests/test_graph_reasoning_strategy.py tests/test_semantic_graph_writer.py tests/test_graph_retrieval_adapters.py -q --cov=rag_modules.graph.reasoning_strategy --cov=rag_modules.infra.semantic_graph_writer --cov=rag_modules.graph.entity_linker --cov=rag_modules.retrieval.adapters.graph_kv_retriever --cov-branch --cov-report=term-missing`

Expected: all tests pass; each selected module gains behavior branches, and the entity-link tests use
the current `EntityLinker(driver, database, graph_settings=None)` constructor without production
changes.

- [ ] **Step 5: Commit second-ring graph tests**

```powershell
git add tests/test_graph_reasoning_strategy.py tests/test_semantic_graph_writer.py tests/test_graph_retrieval_adapters.py
git commit -m "test: cover second-ring graph branches"
```

---

### Task 9: Graph Query Execution, Post-Processing, Milvus Search, And Blue/Green Recovery

**Files:**
- Modify: `tests/test_graph_retrieval_executor.py`
- Modify: `tests/test_graph_reasoning_strategy.py`
- Create: `tests/test_milvus_search.py`
- Modify: `tests/test_milvus_blue_green.py`
- Test: `rag_modules/graph/query_executor.py`
- Test: `rag_modules/graph/retrieval_postprocess.py`
- Test: `rag_modules/infra/milvus/search.py`
- Test: `rag_modules/infra/milvus/blue_green.py`

**Interfaces:**
- Consumes: existing recording Neo4j and Milvus fakes.
- Produces: coverage for query selection, malformed records, filter expressions, result formatting, and publish recovery.

- [ ] **Step 1: Add graph query and post-process branch tests**

Append to `tests/test_graph_retrieval_executor.py`:

```python
def test_graph_query_executor_guards_missing_driver_and_selects_target_filter() -> None:
    no_driver = GraphQueryExecutor(None, database="neo4j")
    plan = _FakeRetrievalPlan()

    assert no_driver.multi_hop_paths(plan) == []
    assert no_driver.entity_relation_paths(plan) == []
    assert no_driver.shortest_paths(plan) == []
    assert no_driver.subgraphs(plan) == []
    assert GraphQueryExecutor._target_filter_clause(plan) == ""

    plan.target_terms = ["pepper"]
    assert "target_terms" in GraphQueryExecutor._target_filter_clause(plan)


def test_graph_query_executor_params_include_linked_ids_and_terms() -> None:
    plan = _FakeRetrievalPlan()
    plan.source_node_ids = ["r1"]
    plan.target_node_ids = ["i1"]
    plan.source_terms = ["tofu"]
    plan.target_terms = ["pepper"]

    params = GraphQueryExecutor._params(plan)

    assert params["source_node_ids"] == ["r1"]
    assert params["target_node_ids"] == ["i1"]
    assert params["source_terms"] == ["tofu"]
    assert params["target_terms"] == ["pepper"]


def test_graph_query_executor_omits_timeout_without_control() -> None:
    assert GraphQueryExecutor._run_kwargs(None) == {}
```

Append to `tests/test_graph_reasoning_strategy.py`:

```python
def test_postprocessor_rejects_missing_path_and_coerces_malformed_subgraph_values() -> None:
    processor = GraphRetrievalPostProcessor()

    assert processor.parse_neo4j_path({"path_nodes": []}) is None
    subgraph = processor.build_knowledge_subgraph(
        {
            "central_nodes": [{"nodeId": "r1", "name": "Recipe", "labels": "Recipe"}],
            "connected_nodes": [None, {"nodeId": "i1", "name": "Pepper"}],
            "relationships": [{"type": "USES", "startNodeId": "r1", "endNodeId": "i1"}],
            "graph_metrics": {"density": "0.5", "invalid": "bad"},
        }
    )

    assert subgraph.central_nodes[0].labels == ("Recipe",)
    assert subgraph.graph_metrics == {"density": 0.5}
```

- [ ] **Step 2: Add Milvus search tests**

Create `tests/test_milvus_search.py`:

```python
from __future__ import annotations

from rag_modules.contracts import RetrievalRequest
from rag_modules.infra.milvus.search import (
    _MilvusSearchOperations,
    _filter_expression,
    _format_hits,
    _metadata_filter,
)


class _Embeddings:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = []

    def embed_query(self, query, *, timeout_seconds=None):
        if self.error:
            raise self.error
        self.calls.append((query, timeout_seconds))
        return [0.1, 0.2]


class _Client:
    def __init__(self, results=None, error: Exception | None = None) -> None:
        self.results = results
        self.error = error
        self.calls = []

    def search(self, **kwargs):
        if self.error:
            raise self.error
        self.calls.append(kwargs)
        return self.results


class _Search(_MilvusSearchOperations):
    def __init__(self, results=None) -> None:
        self.collection_created = True
        self.collection_name = "recipes"
        self.vector_search_max_k = 2
        self.vector_search_ef = 1
        self.embeddings = _Embeddings()
        self.client = _Client(results)


class _Control:
    def __init__(self) -> None:
        self.checks = 0

    def raise_if_cancelled(self) -> None:
        self.checks += 1

    def remaining_seconds(self) -> float:
        return 3.0


def _hit() -> dict[str, object]:
    return {
        "id": "c1",
        "distance": 0.8,
        "entity": {
            "text": "chunk",
            "node_id": "r1",
            "recipe_name": "Mapo tofu",
            "node_type": "Recipe",
            "category": "main",
            "cuisine_type": "Sichuan",
            "difficulty": 2,
            "doc_type": "chunk",
            "chunk_id": "c1",
            "parent_id": "r1",
        },
    }


def test_similarity_search_caps_k_filters_metadata_and_formats_hits() -> None:
    search = _Search([[_hit()]])
    control = _Control()
    request = RetrievalRequest.from_inputs(
        query="tofu",
        candidate_k=5,
        control=control,
        metadata={"milvus_filter": {"category": "main", "difficulty": 2}},
    )

    [result] = search.similarity_search(request)

    assert result["text"] == "chunk"
    assert result["score"] == 0.8
    assert result["metadata"]["node_id"] == "r1"
    assert search.client.calls[0]["limit"] == 2
    assert search.client.calls[0]["search_params"]["params"]["ef"] == 2
    assert search.client.calls[0]["filter"] == 'category == "main" and difficulty == 2'
    assert search.client.calls[0]["timeout"] == 3.0
    assert control.checks == 3


def test_search_guards_collection_and_degrades_embedding_or_client_failures() -> None:
    search = _Search([])
    search.collection_created = False
    try:
        search.similarity_search(RetrievalRequest.from_inputs(query="x"))
    except ValueError as exc:
        assert "built or loaded" in str(exc)
    else:
        raise AssertionError("missing collection must raise")

    search.collection_created = True
    search.embeddings = _Embeddings(RuntimeError("embedding down"))
    assert search.similarity_search(RetrievalRequest.from_inputs(query="x")) == []

    search.embeddings = _Embeddings()
    search.client = _Client(error=RuntimeError("search down"))
    assert search.similarity_search(RetrievalRequest.from_inputs(query="x")) == []


def test_filter_helpers_handle_alias_lists_numbers_and_invalid_payloads() -> None:
    assert _metadata_filter({"filters": {"category": ["main", "side"]}}) == {
        "category": ["main", "side"]
    }
    assert _metadata_filter({"filters": "invalid"}) == {}
    assert _filter_expression(
        {"category": ["main", "side"], "difficulty": [1, 2], "ignored": None}
    ) == 'category in ["main", "side"] and difficulty in [1, 2]'
    assert _format_hits([]) == []
    assert _format_hits(None) == []
```

- [ ] **Step 3: Extend blue/green failure recovery tests**

Append the following methods inside `MilvusBlueGreenTests` in
`tests/test_milvus_blue_green.py`:

```python
def test_blue_green_disabled_build_publish_and_rollback_use_physical_name() -> None:
    module = _build_index_module(_FakeMilvusClient())
    module.blue_green_enabled = False

    target = module.prepare_blue_green_build("recipes__blue")
    previous = module.publish_collection("recipes__blue")
    module.rollback_collection_publish("recipes__green")

    self.assertEqual(target["collection_name"], "recipes")
    self.assertEqual(previous, "")
    self.assertEqual(module.collection_name, "recipes__green")


def test_publish_rejects_missing_collection_and_discard_preserves_active() -> None:
    client = _FakeMilvusClient()
    module = _build_index_module(client)

    with self.assertRaises(ValueError):
        module.publish_collection("recipes__missing")

    module.active_collection_name = "recipes__blue"
    self.assertTrue(module.discard_build_collection(""))
    self.assertTrue(module.discard_build_collection("recipes__blue"))
    self.assertEqual(client.collections, {"recipes__blue", "recipes__green"})


def test_rollback_without_previous_target_drops_alias_and_resets_state() -> None:
    client = _FakeMilvusClient()
    module = _build_index_module(client)
    client.create_alias(collection_name="recipes__blue", alias="recipes__active")

    module.rollback_collection_publish("")

    self.assertNotIn("recipes__active", client.aliases)
    self.assertEqual(module.collection_name, "recipes")
    self.assertEqual(module.active_collection_name, "")
    self.assertEqual(module.physical_collection_name("green"), "recipes__green")
    self.assertEqual(module.physical_collection_name("other"), "recipes__blue")
```

- [ ] **Step 4: Run the graph and Milvus slice**

Run: `python -m pytest tests/test_graph_retrieval_executor.py tests/test_graph_reasoning_strategy.py tests/test_milvus_search.py tests/test_milvus_blue_green.py -q --cov=rag_modules.graph.query_executor --cov=rag_modules.graph.retrieval_postprocess --cov=rag_modules.infra.milvus.search --cov=rag_modules.infra.milvus.blue_green --cov-branch --cov-report=term-missing`

Expected: all tests pass with material gains in each selected file.

- [ ] **Step 5: Commit graph query and Milvus recovery tests**

```powershell
git add tests/test_graph_retrieval_executor.py tests/test_graph_reasoning_strategy.py tests/test_milvus_search.py tests/test_milvus_blue_green.py
git commit -m "test: cover graph query and Milvus recovery branches"
```

---

### Task 10: Hybrid Index Cache And Graph Extraction Boundaries

**Files:**
- Create: `tests/test_hybrid_index_service.py`
- Test: `rag_modules/retrieval/hybrid_index_service.py`

**Interfaces:**
- Consumes: `HybridIndexService`, `HybridIndexArtifacts`, `TextDocument`, and narrow cache/driver fakes.
- Produces: deterministic coverage for cache payload validation, parent-document serialization, BM25 restoration, and Neo4j relationship extraction.

- [ ] **Step 1: Capture the current hybrid-index branch report**

Run: `python -m pytest tests/test_hybrid_retrieval_runtime.py tests/test_retrieval_cache.py -q --cov=rag_modules.retrieval.hybrid_index_service --cov-branch --cov-report=term-missing`

Expected: existing tests pass while `hybrid_index_service.py` remains close to 0/24 branch coverage.

- [ ] **Step 2: Add focused cache and relationship tests**

Create `tests/test_hybrid_index_service.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.kernel.documents import TextDocument
from rag_modules.retrieval.hybrid_index_service import HybridIndexService
from rag_modules.retrieval.parent_doc_enricher import ParentDocumentEnricher


class _BM25:
    def __init__(self, restore=True) -> None:
        self.restore = restore
        self.bm25 = object()
        self.corpus_docs = [TextDocument(content="cached")]

    def from_cache_dict(self, payload):
        return self.restore

    def to_cache_dict(self):
        return {"tokens": [["cached"]]}


class _Session:
    def __init__(self, records=(), error: Exception | None = None) -> None:
        self.records = list(records)
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def run(self, query):
        if self.error:
            raise self.error
        return self.records


class _Driver:
    def __init__(self, session: _Session) -> None:
        self.session_obj = session

    def session(self, **kwargs):
        return self.session_obj


def _service(*, restore=True) -> HybridIndexService:
    config = build_test_config()
    data_module = SimpleNamespace(documents=[], recipes=[], ingredients=[], cooking_steps=[])
    graph_indexing = SimpleNamespace(
        from_cache_dict=lambda payload: True,
        to_cache_dict=lambda: {"graph": True},
        create_entity_key_values=lambda *args: None,
        create_relation_key_values=lambda relationships: None,
        deduplicate_entities_and_relations=lambda: None,
        get_statistics=lambda: {},
    )
    return HybridIndexService(
        config=config,
        data_module=data_module,
        graph_indexing=graph_indexing,
        cache_store=SimpleNamespace(load=lambda chunks: None, save=lambda chunks, payload: None),
        bm25_retriever=_BM25(restore=restore),
        parent_enricher=ParentDocumentEnricher(config),
    )


def test_parent_document_cache_round_trip_filters_invalid_items() -> None:
    serialized = HybridIndexService._serialize_parent_documents(
        {
            "r1": TextDocument(
                content="parent", metadata={"node_id": "r1", "rank": 1}
            )
        }
    )

    assert HybridIndexService._deserialize_parent_documents(serialized) == {
        "r1": TextDocument(content="parent", metadata={"node_id": "r1", "rank": 1})
    }
    assert HybridIndexService._deserialize_parent_documents("invalid") == {}
    assert HybridIndexService._deserialize_parent_documents(
        {"bad": "invalid", "r2": {"page_content": "ok", "metadata": "invalid"}}
    ) == {"r2": TextDocument(content="ok", metadata={})}


def test_restore_bm25_requires_mapping_and_successful_retriever_restore() -> None:
    assert _service().restore_bm25_retriever({}) is False
    assert _service().restore_bm25_retriever({"bm25_retriever": "invalid"}) is False
    assert _service(restore=False).restore_bm25_retriever({"bm25_retriever": {}}) is False
    assert _service().restore_bm25_retriever({"bm25_retriever": {}}) is True


def test_extract_relationships_handles_absent_successful_and_failed_driver() -> None:
    service = _service()
    assert service._extract_relationships_from_graph(None) == []

    driver = _Driver(
        _Session(
            [
                {"source_id": 1, "relation_type": "USES", "target_id": 2},
                {"source_id": "r1", "relation_type": "HAS", "target_id": "i1"},
            ]
        )
    )
    assert service._extract_relationships_from_graph(driver) == [
        ("1", "USES", "2"),
        ("r1", "HAS", "i1"),
    ]
    assert service._extract_relationships_from_graph(
        _Driver(_Session(error=RuntimeError("neo4j down")))
    ) == []
```

- [ ] **Step 3: Run hybrid-index and adjacent retrieval tests**

Run: `python -m pytest tests/test_hybrid_index_service.py tests/test_hybrid_retrieval_runtime.py tests/test_retrieval_cache.py -q --cov=rag_modules.retrieval.hybrid_index_service --cov-branch --cov-report=term-missing`

Expected: all tests pass and cache/relationship success, guard, invalid-payload, and failure branches are covered.

- [ ] **Step 4: Commit hybrid-index tests**

```powershell
git add tests/test_hybrid_index_service.py
git commit -m "test: cover hybrid index cache branches"
```

---

### Task 11: Full-Suite Measurement And Fixed Reserve Modules

**Files:**
- Modify if activated: `tests/test_graph_data_preparation_module.py`
- Modify if activated: `tests/test_milvus_blue_green.py`
- Modify if activated: `tests/test_generation_client.py`
- Test if activated: `rag_modules/build_pipeline/graph_preparation/document_builder.py`
- Test if activated: `rag_modules/runtime/artifact_adapters.py`
- Test if activated: `rag_modules/generation/clients/adapter.py`

**Interfaces:**
- Consumes: `coverage.json` and `scripts/check_branch_coverage.py`.
- Produces: either evidence that the first two rings exceed 70.3%, or deterministic reserve tests for exactly three approved runtime modules.

- [ ] **Step 1: Generate a fresh full-suite package report**

Run:

```powershell
python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
```

Expected: zero test failures/errors; combined coverage exceeds 75%. Then run:

```powershell
python scripts/check_branch_coverage.py
```

Expected stopping rule: if the output is at least 70.30%, skip Steps 2-4 and continue to Task 12. If
the output is below 70.30%, execute all of Steps 2-4; do not choose DTO or protocol files.

- [ ] **Step 2: Add fixed reserve document-builder cases when required**

Append the following method inside `GraphDataPreparationModuleTests` in
`tests/test_graph_data_preparation_module.py`:

```python
def test_recipe_document_builder_handles_sparse_invalid_relationship_rows(self) -> None:
    driver = self._build_driver()
    driver.responses["recipes"][0]["originalProperties"].update(
        {
            "difficulty": "invalid",
            "tags": ["quick", "", "quick"],
            "prepTime": "",
            "cookTime": None,
        }
    )
    driver.responses["recipe_ingredients"] = [
        {
            "recipe_id": "200000001",
            "name": "tofu",
            "category": "",
            "amount": None,
            "unit": "",
            "description": "",
        }
    ]
    driver.responses["recipe_steps"] = [
        {
            "recipe_id": "200000001",
            "name": "",
            "description": "simmer",
            "stepNumber": "bad",
            "methods": [],
            "tools": None,
            "timeEstimate": "",
            "stepOrder": "bad",
        }
    ]
    module = GraphDataPreparationModule(database="neo4j", driver=driver)
    module.load_graph_data()

    [document] = module.build_recipe_documents()

    self.assertEqual(document.metadata["ingredients_count"], 1)
    self.assertEqual(document.metadata["steps_count"], 1)
    self.assertIn("tofu", document.content)
    self.assertIn("simmer", document.content)
    self.assertEqual(document.metadata["difficulty"], 0)
```

- [ ] **Step 3: Add fixed reserve artifact and generation adapter cases when required**

Add these imports to `tests/test_milvus_blue_green.py`:

```python
from rag_modules.runtime.artifact_adapters import DefaultRuntimeArtifactAccess
```

Add this module-level fake and these methods inside `MilvusBlueGreenTests`:

```python
class _LegacyVectorIndex:
    def __init__(self) -> None:
        self.collection_name = "recipes"
        self.build_calls = []

    def has_collection(self):
        return 1

    def load_collection(self):
        return 1

    def build_vector_index(self, chunks, **kwargs):
        self.build_calls.append((list(chunks), dict(kwargs)))
        return 1

    def delete_collection(self):
        return 1


def test_default_artifact_access_uses_legacy_vector_fallbacks(self) -> None:
    access = DefaultRuntimeArtifactAccess()
    index = _LegacyVectorIndex()
    manifest = ArtifactManifest(collection_name="recipes__blue")

    self.assertEqual(access.configure_vector_collection(index, manifest), "recipes__blue")
    self.assertEqual(index.collection_name, "recipes__blue")
    self.assertTrue(access.has_vector_collection(index))
    self.assertTrue(access.load_vector_collection(index))
    self.assertEqual(
        access.prepare_vector_index_build(index),
        {
            "collection_name": "recipes__blue",
            "collection_base_name": "recipes__blue",
            "collection_slot": "",
        },
    )
    self.assertEqual(access.publish_vector_index(index, "recipes__green"), "")
    self.assertEqual(index.collection_name, "recipes__green")
    self.assertTrue(access.discard_vector_index(index, "recipes__candidate"))
    self.assertTrue(access.delete_vector_collection(index))


def test_default_artifact_access_passes_explicit_build_collection() -> None:
    access = DefaultRuntimeArtifactAccess()
    index = _LegacyVectorIndex()
    chunks = [TextDocument(content="chunk")]

    self.assertTrue(access.build_vector_index(index, chunks, collection_name="recipes__green"))
    self.assertEqual(index.build_calls[0][1], {"collection_name": "recipes__green"})
```

Add `from unittest.mock import patch` with the imports in `tests/test_generation_client.py`, then
append these methods inside `GenerationClientAdapterTests`:

```python
def test_completion_estimates_usage_when_provider_omits_usage(self) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="estimated completion"))]
    )
    adapter = GenerationClientAdapter(
        client=_FakeClient([response]),
        model_name="test-model",
        default_temperature=0.0,
        request_retries=1,
        stream_timeout_seconds=5,
    )

    result = adapter.create_completion(
        prompt="estimated prompt",
        temperature=0.0,
        max_tokens=10,
        timeout=2,
    )

    self.assertEqual(GenerationClientAdapter.response_text(result), "estimated completion")
    usage = adapter.consume_token_usage()
    self.assertEqual(usage["token_usage_source"], "estimated")
    self.assertGreater(usage["total_tokens"], 0)


def test_consume_retry_count_resets_after_provider_retry(self) -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
    )
    adapter = GenerationClientAdapter(
        client=_FakeClient([TimeoutError("transient"), response]),
        model_name="test-model",
        default_temperature=0.0,
        request_retries=2,
        stream_timeout_seconds=5,
    )

    with patch("rag_modules.generation.clients.adapter.time.sleep"):
        adapter.create_completion(
            prompt="retry",
            temperature=0.0,
            max_tokens=10,
            timeout=3,
        )

    self.assertEqual(adapter.consume_retry_count(), 1)
    self.assertEqual(adapter.consume_retry_count(), 0)
```

- [ ] **Step 4: Verify reserve slices and remeasure globally**

Run:

```powershell
python -m pytest tests/test_graph_data_preparation_module.py tests/test_milvus_blue_green.py tests/test_generation_client.py -q
python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=term-missing --cov-report=json:coverage.json
python scripts/check_branch_coverage.py
```

Expected: all tests pass; the branch gate reports at least 70.00%, with the delivery target at or
above 70.30%. If the result is between 70.00% and 70.29%, add only the already-specified missing
input variants in Steps 2-3 until one additional coherent scenario raises the result to 70.30%.

- [ ] **Step 5: Commit activated reserve tests or record that they were unnecessary**

If reserve tests were added:

```powershell
git add tests/test_graph_data_preparation_module.py tests/test_milvus_blue_green.py tests/test_generation_client.py
git commit -m "test: close branch coverage reserve gap"
```

If no reserve test was needed, record the fresh percentage in the implementation checklist and do
not create an empty commit.

---

### Task 12: Final Verification And Release-Sensitive Handoff

**Files:**
- Verify: all files changed by Tasks 1-11
- Verify: `docs/superpowers/specs/2026-07-12-risk-weighted-branch-coverage-design.md`
- Verify: `docs/superpowers/plans/2026-07-12-risk-weighted-branch-coverage.md`

**Interfaces:**
- Consumes: the completed dual gate and all risk-weighted tests.
- Produces: fresh test, coverage, formatting, release-gate, and clean-diff evidence.

- [ ] **Step 1: Run focused gate and hotspot tests**

Run:

```powershell
python -m pytest tests/test_branch_coverage_gate.py tests/test_local_gate.py tests/test_enterprise_governance.py tests/test_parent_doc_enricher.py tests/test_milvus_writer.py tests/test_graph_path_ranker.py tests/test_vector_retriever.py tests/test_neo4j_fallback_retriever.py tests/test_graph_evidence_orchestrator.py -q
```

Expected: all selected tests pass with zero errors.

- [ ] **Step 2: Run the complete coverage command and independent branch gate**

Run:

```powershell
python -m pytest -q --cov=rag_modules --cov=scripts --cov-branch --cov-report=term-missing --cov-report=xml --cov-report=json:coverage.json
python scripts/check_branch_coverage.py
```

Expected: pytest exits 0; combined coverage is at least 75%; the branch gate exits 0 and reports
`rag_modules` at or above 70%, targeting at least 70.3%.

- [ ] **Step 3: Run formatting and static analysis**

Run: `pre-commit run --all-files`

Expected: exit code 0. If Ruff modifies files, inspect `git diff`, rerun focused tests, and rerun
`pre-commit run --all-files` until it exits 0 without new modifications.

- [ ] **Step 4: Run the release-sensitive gate**

Run: `python scripts/release_gate.py`

Expected: exit code 0 and a passing offline release-gate report.

- [ ] **Step 5: Verify generated artifacts and scope**

Run:

```powershell
git status --short
git diff --check
git diff --stat HEAD~10..HEAD
```

Expected: no `.coverage`, `coverage.json`, `coverage.xml`, `htmlcov`, cache, storage, or
`eval/reports` artifact is tracked; `git diff --check` exits 0; changed production files, if any,
have an associated failing-then-passing regression test recorded in the task notes.

- [ ] **Step 6: Commit final documentation or formatting adjustments**

If verification changed tracked documentation or formatting:

```powershell
git add README.md docs/release_process.md .github/workflows/ci.yml scripts tests pyproject.toml .gitignore
git commit -m "test: enforce risk-weighted branch coverage"
```

If verification made no tracked changes, do not create an empty commit.
