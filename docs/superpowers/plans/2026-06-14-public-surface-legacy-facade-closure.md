# Public Surface Legacy Facade Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the public-surface manifest the single source of truth and keep remaining legacy facades as thin, registered external bridges only.

**Architecture:** The manifest owns category membership, canonical targets, and legacy phase metadata. Boundary tests derive wrapper names and prohibited imports from the manifest, then enforce thin-wrapper structure with AST checks. Documentation becomes a current policy document instead of a mixed history and plan.

**Tech Stack:** Python 3.11, `unittest`, `ast`, `importlib.util.resolve_name`, `pytest`, Markdown documentation. Checkpoints stage files instead of committing because the user requested no repository commits.

---

## File Structure

- Modify `rag_modules/public_surface_manifest.py`: add small query helpers for manifest-derived module sets and legacy facade names.
- Modify `tests/test_public_api_manifest.py`: replace duplicated hard-coded expected module sets with manifest self-consistency tests and use manifest helpers for internal-only prefixes.
- Modify `tests/test_public_surface_boundaries.py`: derive root-wrapper allowlists from the manifest, make import resolution package-aware, block remaining legacy facades in scripts and ordinary tests, and add a thin-wrapper AST check.
- Modify `docs/public_surface_retirement_plan.md`: rewrite as the current public-surface policy with canonical packages, remaining bridges, rules, retired history, and deletion criteria.
- Create or update `docs/superpowers/plans/2026-06-14-public-surface-legacy-facade-closure.md`: this implementation plan.

---

### Task 1: Manifest Query Helpers

**Files:**
- Modify: `rag_modules/public_surface_manifest.py`
- Test: `tests/test_public_api_manifest.py`

- [ ] **Step 1: Write failing manifest-helper tests**

Replace the import block and the three hard-coded module-set tests in `tests/test_public_api_manifest.py` with helper-driven consistency tests:

```python
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from rag_modules.public_surface_manifest import (
    ALL_PUBLIC_SURFACE,
    CANONICAL_SURFACE,
    EXTERNAL_PUBLIC_SURFACE,
    INTERNAL_ONLY_SURFACE,
    LEGACY_PUBLIC_SURFACE,
    PUBLIC_API_SURFACE,
    ROOT_PUBLIC_SURFACE,
    SERVICE_API_SURFACE,
    canonical_surface_by_module,
    legacy_surface_by_module,
    modules_for,
    public_surface_by_module,
    repo_root_facade_module_names,
    root_facade_module_names,
    surface_by_kind,
)
```

Inside `PublicApiManifestTests`, replace `test_manifest_lists_expected_public_api_modules`, `test_manifest_lists_expected_service_api_modules`, and `test_manifest_lists_expected_internal_only_packages` with:

```python
    def test_surface_entries_are_unique_and_indexed(self) -> None:
        all_modules = [entry.module_name for entry in ALL_PUBLIC_SURFACE]

        self.assertEqual(len(all_modules), len(set(all_modules)))
        self.assertEqual(set(all_modules), set(public_surface_by_module()))
        self.assertEqual(set(modules_for(CANONICAL_SURFACE)), set(canonical_surface_by_module()))
        self.assertEqual(set(modules_for(LEGACY_PUBLIC_SURFACE)), set(legacy_surface_by_module()))

    def test_surface_collections_match_declared_kind(self) -> None:
        expected_by_kind = {
            "public_api": PUBLIC_API_SURFACE,
            "service_api": SERVICE_API_SURFACE,
            "internal_only": INTERNAL_ONLY_SURFACE,
            "root_facade": ROOT_PUBLIC_SURFACE,
            "repo_root_facade": EXTERNAL_PUBLIC_SURFACE,
        }
        grouped = surface_by_kind()

        self.assertEqual(set(expected_by_kind), set(grouped))
        for kind, entries in expected_by_kind.items():
            self.assertEqual({kind}, {entry.kind for entry in entries})
            self.assertEqual(modules_for(entries), modules_for(grouped[kind]))

    def test_legacy_surface_entries_name_canonical_targets(self) -> None:
        for entry in LEGACY_PUBLIC_SURFACE:
            self.assertNotEqual(entry.module_name, entry.canonical_module)
            self.assertNotEqual("canonical", entry.retirement_phase)

        self.assertEqual(
            root_facade_module_names(),
            frozenset(f"rag_modules.{entry.module_name}" for entry in ROOT_PUBLIC_SURFACE),
        )
        self.assertEqual(repo_root_facade_module_names(), modules_for(EXTERNAL_PUBLIC_SURFACE))
```

Change the module-level internal prefix constant in `tests/test_public_api_manifest.py` to derive from the manifest:

```python
INTERNAL_PACKAGE_PREFIXES = tuple(modules_for(INTERNAL_ONLY_SURFACE))
```

- [ ] **Step 2: Run the manifest tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py -q
```

Expected: FAIL with an import error for one of `modules_for`, `surface_by_kind`, `legacy_surface_by_module`, `root_facade_module_names`, or `repo_root_facade_module_names`.

- [ ] **Step 3: Add manifest query helpers**

In `rag_modules/public_surface_manifest.py`, add this import below the dataclass import:

```python
from collections.abc import Iterable
```

Add these helper functions after `ALL_PUBLIC_SURFACE`:

```python
def modules_for(entries: Iterable[PublicSurfaceEntry]) -> frozenset[str]:
    return frozenset(entry.module_name for entry in entries)


def surface_by_kind(
    entries: Iterable[PublicSurfaceEntry] = ALL_PUBLIC_SURFACE,
) -> dict[str, tuple[PublicSurfaceEntry, ...]]:
    grouped: dict[str, list[PublicSurfaceEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.kind, []).append(entry)
    return {kind: tuple(kind_entries) for kind, kind_entries in grouped.items()}


def legacy_surface_by_module() -> dict[str, PublicSurfaceEntry]:
    return {entry.module_name: entry for entry in LEGACY_PUBLIC_SURFACE}


def root_facade_module_names() -> frozenset[str]:
    return frozenset(f"rag_modules.{entry.module_name}" for entry in ROOT_PUBLIC_SURFACE)


def repo_root_facade_module_names() -> frozenset[str]:
    return modules_for(EXTERNAL_PUBLIC_SURFACE)
```

Add these names to `__all__`:

```python
    "legacy_surface_by_module",
    "modules_for",
    "repo_root_facade_module_names",
    "root_facade_module_names",
    "surface_by_kind",
```

- [ ] **Step 4: Run the manifest tests and verify they pass**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 5: Stage the manifest checkpoint**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- rag_modules/public_surface_manifest.py tests/test_public_api_manifest.py
git -c safe.directory=E:/ai-project/all-in-rag diff --cached --name-status
```

Expected staged files include only `rag_modules/public_surface_manifest.py` and `tests/test_public_api_manifest.py` from this task, plus any files intentionally staged from earlier approved steps.

---

### Task 2: Manifest-Driven Boundary Guardrails

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`
- Test: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Add manifest-derived boundary constants and guardrail tests**

Change the manifest import in `tests/test_public_surface_boundaries.py` to:

```python
from rag_modules.public_surface_manifest import (
    EXTERNAL_PUBLIC_SURFACE,
    LEGACY_PUBLIC_SURFACE,
    ROOT_PUBLIC_SURFACE,
    repo_root_facade_module_names,
    root_facade_module_names,
)
```

Replace the module-level constants with:

```python
ALLOWED_ROOT_WRAPPERS = {
    f"{entry.module_name}.py"
    for entry in ROOT_PUBLIC_SURFACE
}
PROHIBITED_ROOT_MODULES = root_facade_module_names()
PROHIBITED_REPO_ROOT_MODULES = repo_root_facade_module_names()
LEGACY_FACADE_MODULES = PROHIBITED_ROOT_MODULES | PROHIBITED_REPO_ROOT_MODULES
```

Add these helper methods inside `PublicSurfaceBoundaryTests` after `_module_name_for_path`:

```python
    @staticmethod
    def _package_name_for_path(path: Path) -> str:
        if path.is_relative_to(RAG_MODULES_DIR):
            rel = path.relative_to(RAG_MODULES_DIR)
            if rel.name == "__init__.py":
                parts = ("rag_modules", *rel.parts[:-1])
            else:
                parts = ("rag_modules", *rel.parts[:-1])
            return ".".join(part for part in parts if part)
        return path.stem

    @staticmethod
    def _legacy_facade_path(entry) -> Path:
        if entry.kind == "root_facade":
            return RAG_MODULES_DIR / f"{entry.module_name}.py"
        if entry.kind == "repo_root_facade":
            return ROOT / f"{entry.module_name}.py"
        raise AssertionError(f"Unsupported legacy facade kind: {entry.kind!r}")
```

Replace `_resolve_import_from` with this package-aware implementation:

```python
    @classmethod
    def _resolve_import_from(cls, path: Path, node: ast.ImportFrom) -> str:
        module = node.module or ""
        if node.level == 0:
            return module
        relative_name = "." * node.level + module
        return resolve_name(relative_name, cls._package_name_for_path(path))
```

Replace `test_scripts_do_not_import_default_config_from_repo_root_facade` with:

```python
    def test_scripts_do_not_import_repo_root_config_facade(self) -> None:
        violations: list[str] = []

        for path in (ROOT / "scripts").rglob("*.py"):
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in PROHIBITED_REPO_ROOT_MODULES:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in PROHIBITED_REPO_ROOT_MODULES:
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found scripts importing repo-root configuration facades:\n"
            + "\n".join(violations),
        )
```

Add this test after `test_scripts_do_not_import_repo_root_config_facade`:

```python
    def test_scripts_and_non_compat_tests_do_not_import_remaining_legacy_facades(self) -> None:
        violations: list[str] = []
        allowed_test_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }

        for base_dir in (ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_test_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        if module_name in LEGACY_FACADE_MODULES:
                            violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in LEGACY_FACADE_MODULES:
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found scripts/tests importing remaining legacy facades outside compatibility checks:\n"
            + "\n".join(violations),
        )
```

Add this thin-wrapper test after `test_manifest_covers_remaining_legacy_public_surface`:

```python
    def test_remaining_legacy_facades_are_thin_registered_wrappers(self) -> None:
        violations: list[str] = []

        for entry in LEGACY_PUBLIC_SURFACE:
            path = self._legacy_facade_path(entry)
            rel = path.relative_to(ROOT)
            self.assertTrue(path.exists(), f"Missing legacy facade file for {entry.module_name}")
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            imported_modules: set[str] = set()

            for index, node in enumerate(tree.body):
                if (
                    index == 0
                    and isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    imported_modules.add(module_name)
                    if module_name == "__future__":
                        continue
                    if module_name != entry.canonical_module:
                        violations.append(
                            f"{rel}:{node.lineno}: imports {module_name!r}, expected {entry.canonical_module!r}"
                        )
                    if any(alias.name == "*" for alias in node.names):
                        violations.append(f"{rel}:{node.lineno}: star import is not a thin facade")
                    continue
                if isinstance(node, ast.Assign) and all(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                ):
                    continue
                violations.append(f"{rel}:{node.lineno}: {source.splitlines()[node.lineno - 1].strip()}")

            self.assertIn(
                entry.canonical_module,
                imported_modules,
                f"{entry.module_name} should import its canonical target {entry.canonical_module}",
            )

        self.assertFalse(
            violations,
            "Found legacy facades with local logic or unregistered dependencies:\n"
            + "\n".join(violations),
        )
```

- [ ] **Step 2: Run the focused thin-wrapper guardrail**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_remaining_legacy_facades_are_thin_registered_wrappers -q
```

Expected: PASS against the current thin facades. This is a characterization
guardrail: a failure means a remaining legacy wrapper already owns local logic
or imports a non-canonical dependency.

- [ ] **Step 3: Run public-surface boundary tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: PASS. If this exposes an existing internal import through the corrected package-aware resolver, change that import to its canonical package and rerun this command.

- [ ] **Step 4: Stage the boundary checkpoint**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- tests/test_public_surface_boundaries.py
git -c safe.directory=E:/ai-project/all-in-rag diff --cached --name-status
```

Expected staged files include `tests/test_public_surface_boundaries.py`.

---

### Task 3: Current Public Surface Policy Document

**Files:**
- Modify: `docs/public_surface_retirement_plan.md`
- Test: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Update the documentation test expectations**

Replace `test_retirement_plan_document_exists` in `tests/test_public_surface_boundaries.py` with:

```python
    def test_retirement_plan_document_states_current_policy(self) -> None:
        plan_path = ROOT / "docs" / "public_surface_retirement_plan.md"
        self.assertTrue(plan_path.exists())
        content = plan_path.read_text(encoding="utf-8")

        for heading in (
            "## Current Policy",
            "## Canonical Packages",
            "## Remaining Legacy Bridges",
            "## Internal Freeze Rule",
            "## Thin Wrapper Rule",
            "## Retired Facade History",
            "## Final Retirement Criteria",
        ):
            self.assertIn(heading, content)
        self.assertIn("public_surface_manifest.py", content)
        self.assertIn("canonical imports", content)
```

- [ ] **Step 2: Run the documentation test and verify it fails**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_retirement_plan_document_states_current_policy -q
```

Expected: FAIL because the current document still uses the older "Goal" and "Retirement Phases" shape.

- [ ] **Step 3: Rewrite `docs/public_surface_retirement_plan.md`**

Replace the document with:

```markdown
# Public Surface Retirement Policy

## Current Policy

The repository uses canonical packages for all internal implementation,
scripts, and ordinary tests. Legacy facades remain only as registered external
compatibility bridges during the migration window. New code should use
canonical imports; compatibility modules are not an alternate architecture.

The machine-readable source of truth is
[`rag_modules/public_surface_manifest.py`](E:/ai-project/all-in-rag/code/C9/rag_modules/public_surface_manifest.py:1).

## Canonical Packages

- Application: `rag_modules.app.*`
- Configuration: `rag_modules.configuration.*`
- Generation: `rag_modules.generation.*`
- Retrieval: `rag_modules.retrieval.*`
- Runtime contracts: `rag_modules.runtime.*`
- Query understanding: `rag_modules.query_understanding.*`
- Graph retrieval: `rag_modules.graph.*`
- Build/document artifacts: `rag_modules.build_pipeline.document_artifacts.*`
- Infra adapters: `rag_modules.infra.*`

## Remaining Legacy Bridges

| Legacy module | Canonical module | Phase |
| --- | --- | --- |
| `config.py` | `rag_modules.configuration` | external migration window |
| `rag_modules.graph_data_preparation` | `rag_modules.graph.data_preparation` | external migration window |
| `rag_modules.graph_indexing` | `rag_modules.graph.indexing` | external migration window |

These bridges are for external callers that have not migrated yet. Repository
code should import the canonical module directly.

## Internal Freeze Rule

- No internal module, script, or ordinary test may import repo-root `config.py`,
  `rag_modules.compat.*`, or root graph facade modules.
- New implementation lands in canonical packages only.
- Compatibility tests may import legacy facades only to prove external import
  behavior still works.

## Thin Wrapper Rule

Remaining legacy facades may re-export or delegate to their canonical target.
They may not own business logic, lifecycle orchestration, state, fallback
policy, or new dependencies. Wrapper files must be registered in
`public_surface_manifest.py`, and boundary tests must fail if an unregistered
wrapper appears.

Flat runtime and system attributes such as `system.query_router` and
`runtime.data_module` are served by the grouped mapping in
[`rag_modules/app/legacy_surface.py`](E:/ai-project/all-in-rag/code/C9/rag_modules/app/legacy_surface.py:1).
Canonical code should use `system.infrastructure`, `system.retrieval`,
`system.services`, and matching grouped runtime views.

## Retired Facade History

- `evidence` facades retired in favor of `rag_modules.evidence_processing`.
- `application`, `knowledge_base_service`, and `question_answer_service`
  facades retired in favor of `rag_modules.app.system` and
  `rag_modules.app.services.*`.
- `generation_integration` and `hybrid_retrieval` facades retired in favor of
  `rag_modules.generation.integration` and `rag_modules.retrieval.hybrid_facade`.
- Most `graph_*` root wrappers retired; only `graph_data_preparation` and
  `graph_indexing` remain for external import compatibility.
- `indexing_pipeline` facades retired in favor of
  `rag_modules.build_pipeline.document_artifacts`.
- `milvus_index_construction` facades retired in favor of
  `rag_modules.infra.milvus_index_construction`.
- `query_plan`, `query_semantics`, and `runtime_models` facades retired in
  favor of `rag_modules.query_understanding` and `rag_modules.runtime`.
- `rag_modules.compat` namespace retired.

## Final Retirement Criteria

The remaining bridges can be deleted after all downstream entrypoints,
documentation, examples, scripts, and eval tooling use canonical imports for
one release cycle. Deletion must update `public_surface_manifest.py`, remove
the wrapper file, and keep a compatibility note in release documentation.
```

- [ ] **Step 4: Run the documentation and boundary tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 5: Stage the documentation checkpoint**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- docs/public_surface_retirement_plan.md tests/test_public_surface_boundaries.py
git -c safe.directory=E:/ai-project/all-in-rag diff --cached --name-status
```

Expected staged files include `docs/public_surface_retirement_plan.md` and `tests/test_public_surface_boundaries.py`.

---

### Task 4: Focused Verification And Staging

**Files:**
- Verify: `rag_modules/public_surface_manifest.py`
- Verify: `tests/test_public_api_manifest.py`
- Verify: `tests/test_public_surface_boundaries.py`
- Verify: `docs/public_surface_retirement_plan.md`

- [ ] **Step 1: Run focused public-surface verification**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_bootstrap_facade_support.py tests/test_generation_integration_facade.py
```

Expected: PASS with all collected tests green. A warning from `jieba`/`pkg_resources` is acceptable if the tests pass.

- [ ] **Step 2: Run a final legacy-import grep**

Run:

```powershell
rg -n "^\s*(from|import)\s+(config|rag_modules\.graph_data_preparation|rag_modules\.graph_indexing)\b|^\s*from\s+(config|rag_modules\.graph_data_preparation|rag_modules\.graph_indexing)\s+import\b" scripts tests rag_modules main.py main_build_kb.py main_build_service.py main_qa.py
```

Expected: no matches. This intentionally checks import statements only; serialization
compatibility strings such as `__module__ = "rag_modules.graph_data_preparation"`
are covered by the thin-wrapper and manifest policy tests rather than this grep.

- [ ] **Step 3: Check staged and unstaged scope**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag diff --cached --name-status
git -c safe.directory=E:/ai-project/all-in-rag status --short
```

Expected: staged changes include the public-surface refactor files and approved spec/plan docs. Existing unrelated worktree changes may remain unstaged; do not revert them.

- [ ] **Step 4: Stage the final implementation set without committing**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add -- rag_modules/public_surface_manifest.py tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py docs/public_surface_retirement_plan.md docs/superpowers/specs/2026-06-14-public-surface-legacy-facade-closure-design.md docs/superpowers/plans/2026-06-14-public-surface-legacy-facade-closure.md
git -c safe.directory=E:/ai-project/all-in-rag diff --cached --name-status
```

Expected: all files intentionally changed for this public-surface closure are staged, and no commit is created.
