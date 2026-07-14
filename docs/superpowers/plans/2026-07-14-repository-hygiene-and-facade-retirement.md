# Repository Hygiene and Facade Retirement Implementation Plan

Status: completed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove proven repository-local generated state, stale setuptools metadata, six thin
forwarding modules, and one explicitly retired linked worktree without changing runtime behavior
or deleting protected local/project state.

**Architecture:** Keep each real implementation in its existing owner module and migrate every
repository consumer directly to that owner before deleting forwarding files. Repository hygiene is
enforced through narrow ignore-policy tests and existing retired-facade boundary tests; local state
cleanup remains an operational final step after validation so test-generated artifacts do not
reappear in the delivered workspace.

**Tech Stack:** Python 3.11, FastAPI, pytest, Ruff, mypy, setuptools, Git worktrees, Windows
PowerShell.

## Global Constraints

- Use Python `>=3.11,<3.12` exactly as required by `pyproject.toml`.
- Use a hard cutover: no aliases, forwarding modules, deprecation shims, or dual import paths.
- Preserve `.env`, `.venv/`, `storage/`, `volumes/`, `agent/`, `docs/superpowers/`, profiles,
  fixtures, Cypher assets, release evidence, and all formal public entrypoints.
- Remove `.worktrees/performance-hotspot-ratchet`, but preserve branch
  `codex/performance-hotspot-ratchet` and its exact tip commit.
- Do not delete or rewrite any Git branch.
- Keep `rag_modules.graph` package-level lazy exports working through their current owner modules.
- Do not modify `requirements.txt` or `requirements-dev.txt`; no dependency changes are required.
- Follow Ruff's Python 3.11 target, 100-character line width, sorted imports, and double quotes.
- Run implementation inline in the current session. Do not dispatch subagents unless the user
  explicitly changes the collaboration instruction.
- Use `apply_patch` for tracked file edits and deletions. Use `git worktree remove` for the linked
  worktree so Git metadata remains consistent.
- Before recursive local-state deletion, resolve every target and verify it is below the repository
  root. Never recurse through `.venv`, `storage`, `volumes`, `agent`, or `docs/superpowers`.

## File Structure

- Modify `.gitignore`: canonical generated-state and setuptools metadata rules.
- Modify `tests/test_enterprise_governance.py`: repository ignore-policy contract.
- Delete `graph_rag_c9.egg-info/`: six tracked generated metadata files.
- Modify `tests/public_surface_boundary_helpers.py`: retired import-path registry.
- Modify `tests/test_graph_cache_stats.py`: import cache types from `cache_stats`.
- Modify `tests/test_graph_retrieval_executor.py`: import executor from `retrieval_executor`.
- Modify `tests/test_retrieval_service_factories.py`: import retrieval collaborators from their
  owner modules.
- Delete `rag_modules/graph/cache.py`, `evidence.py`, `query.py`, `reasoning.py`, and
  `retrieval.py`.
- Modify `tests/test_api_route_structure.py`: require direct route-owner imports.
- Modify `rag_modules/interfaces/api/app.py`: import build and serving registration directly.
- Delete `rag_modules/interfaces/api/routes.py`.
- Modify `tests/test_public_surface_boundaries.py`: bind policy documentation to the current
  package version and retired paths.
- Modify `docs/public_surface_retirement_plan.md`: record the approved internal hard cutover.
- Remove `.worktrees/performance-hotspot-ratchet` operationally while retaining its branch.
- Remove approved generated local state only after all validation commands have completed.

---

### Task 1: Generated Metadata Policy and Stale Egg-Info Removal

**Files:**

- Modify: `.gitignore`
- Modify: `tests/test_enterprise_governance.py`
- Delete: `graph_rag_c9.egg-info/PKG-INFO`
- Delete: `graph_rag_c9.egg-info/SOURCES.txt`
- Delete: `graph_rag_c9.egg-info/dependency_links.txt`
- Delete: `graph_rag_c9.egg-info/entry_points.txt`
- Delete: `graph_rag_c9.egg-info/requires.txt`
- Delete: `graph_rag_c9.egg-info/top_level.txt`

**Interfaces:**

- Consumes: repository ignore policy and `pyproject.toml` as the package metadata source of truth.
- Produces: stable ignore rules for pytest basetemps, setuptools metadata, and root SDD scratch;
  no tracked `graph_rag_c9.egg-info` files remain.

- [ ] **Step 1: Write the failing repository-hygiene policy test**

Add this test after `test_agent_config_template_does_not_contain_credentials` in
`tests/test_enterprise_governance.py`:

```python
def test_generated_repository_metadata_is_ignored() -> None:
    ignored_paths = set(_read(".gitignore").splitlines())

    assert {
        ".pytest_*/",
        "*.egg-info/",
        "/.superpowers/",
    } <= ignored_paths
```

- [ ] **Step 2: Run the policy test to verify it fails**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_generated_repository_metadata_is_ignored -q --basetemp=.pytest_cleanup_policy_red
```

Expected: FAIL because `.gitignore` does not yet contain `.pytest_*/`, `*.egg-info/`, and
`/.superpowers/`.

- [ ] **Step 3: Consolidate the ignore rules**

Replace the two specific pytest directory lines with one generated-basetemp rule and add the two
new policy lines. The generated-state section must read:

```gitignore
__pycache__/
*.py[cod]
.pytest_*/
.coverage
.coverage.*
coverage.json
coverage.xml
htmlcov/
.mypy_cache/
.ruff_cache/
*.egg-info/
.venv/
.venv-*/
.worktrees/
/.superpowers/
.idea/
.restore_*/
```

Keep every other environment, volume, storage, report, log, and operating-system rule in its
current location.

- [ ] **Step 4: Delete the tracked setuptools output**

Use `apply_patch` to delete exactly the six files listed in this task. Do not delete
`pyproject.toml`, lockfiles, or console entrypoint modules.

- [ ] **Step 5: Run the policy and packaging-sensitive tests**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py tests/test_entrypoints.py tests/test_public_api_manifest.py -q --basetemp=.pytest_cleanup_policy_green
```

Expected: PASS.

Then run:

```powershell
git status --short -- graph_rag_c9.egg-info .gitignore tests/test_enterprise_governance.py
```

Expected: `.gitignore` and the test are modified; all six `egg-info` files are deleted; no other
path appears.

- [ ] **Step 6: Commit the generated-metadata policy**

```powershell
git add -- .gitignore tests/test_enterprise_governance.py graph_rag_c9.egg-info
git commit -m "chore: remove generated package metadata"
```

### Task 2: Graph Namespace Forwarding Module Retirement

**Files:**

- Modify: `tests/public_surface_boundary_helpers.py`
- Modify: `tests/test_graph_cache_stats.py`
- Modify: `tests/test_graph_retrieval_executor.py`
- Modify: `tests/test_retrieval_service_factories.py`
- Delete: `rag_modules/graph/cache.py`
- Delete: `rag_modules/graph/evidence.py`
- Delete: `rag_modules/graph/query.py`
- Delete: `rag_modules/graph/reasoning.py`
- Delete: `rag_modules/graph/retrieval.py`

**Interfaces:**

- Consumes: concrete graph owner modules and the existing retired-facade import-failure test.
- Produces: direct test imports and five permanently retired exact submodule paths while preserving
  `rag_modules.graph` package-level exports.

- [ ] **Step 1: Register the five graph modules as retired**

Add these names to `RETIRED_LEGACY_FACADE_MODULES` in
`tests/public_surface_boundary_helpers.py`:

```python
"rag_modules.graph.cache",
"rag_modules.graph.evidence",
"rag_modules.graph.query",
"rag_modules.graph.reasoning",
"rag_modules.graph.retrieval",
```

- [ ] **Step 2: Run the import-failure boundary to verify it fails**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceLegacyBoundaryTests::test_retired_facade_import_paths_fail_instead_of_forwarding -q --basetemp=.pytest_cleanup_graph_red
```

Expected: FAIL because the five graph forwarding modules still import successfully.

- [ ] **Step 3: Migrate the three test consumers to owner modules**

In `tests/test_graph_cache_stats.py`, replace the two graph cache imports with:

```python
from rag_modules.graph.cache_stats import (
    GraphCacheEntityStats,
    GraphCacheStats,
    GraphCacheStatsStore,
)
```

In `tests/test_graph_retrieval_executor.py`, replace the two executor imports with:

```python
from rag_modules.graph.retrieval_executor import (
    GraphRetrievalExecutor,
    GraphRetrievalExecutorServices,
)
```

In `tests/test_retrieval_service_factories.py`, replace the forwarding import with:

```python
from rag_modules.graph.rag_retrieval import GraphRAGRetrieval
from rag_modules.graph.retrieval_components import GraphRetrievalComponents
```

- [ ] **Step 4: Delete the five forwarding modules**

Use `apply_patch` to delete exactly:

```text
rag_modules/graph/cache.py
rag_modules/graph/evidence.py
rag_modules/graph/query.py
rag_modules/graph/reasoning.py
rag_modules/graph/retrieval.py
```

Do not change `rag_modules/graph/__init__.py`; its lazy exports already target owner modules.

- [ ] **Step 5: Run the graph and public-surface tests**

Run:

```powershell
python -m pytest tests/test_graph_cache_stats.py tests/test_graph_retrieval_executor.py tests/test_retrieval_service_factories.py tests/test_public_surface_boundaries.py -q --basetemp=.pytest_cleanup_graph_green
```

Expected: PASS.

Then run:

```powershell
rg -n "rag_modules\.graph\.(cache|evidence|query|reasoning|retrieval)\b" rag_modules scripts tests -g "!tests/public_surface_boundary_helpers.py" -g "!tests/test_public_surface_boundaries.py"
```

Expected: exit code 1 with no matches.

- [ ] **Step 6: Commit the graph hard cutover**

```powershell
git add -- rag_modules/graph/cache.py rag_modules/graph/evidence.py rag_modules/graph/query.py rag_modules/graph/reasoning.py rag_modules/graph/retrieval.py tests/public_surface_boundary_helpers.py tests/test_graph_cache_stats.py tests/test_graph_retrieval_executor.py tests/test_retrieval_service_factories.py
git commit -m "refactor: retire graph namespace forwarding modules"
```

### Task 3: API Route Forwarding Module Retirement

**Files:**

- Modify: `tests/test_api_route_structure.py`
- Modify: `tests/public_surface_boundary_helpers.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Delete: `rag_modules/interfaces/api/routes.py`

**Interfaces:**

- Consumes: `register_build_routes` from `build_routes` and `register_serving_routes` from
  `serving_routes`.
- Produces: API application assembly with direct owner imports and a retired
  `rag_modules.interfaces.api.routes` path.

- [ ] **Step 1: Replace the compatibility-facade test with a direct-import contract**

Remove the plain `import importlib` line from `tests/test_api_route_structure.py`; keep
`import importlib.util`. Replace `test_routes_module_is_thin_compatibility_facade` with:

```python
def test_application_assembly_imports_route_owners_directly(self) -> None:
    spec = importlib.util.find_spec("rag_modules.interfaces.api.app")
    self.assertIsNotNone(spec)
    self.assertIsNotNone(spec.origin)

    source = Path(spec.origin).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=spec.origin)
    direct_imports = {
        (node.level, node.module, alias.name)
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    self.assertIn((1, "build_routes", "register_build_routes"), direct_imports)
    self.assertIn((1, "serving_routes", "register_serving_routes"), direct_imports)
    self.assertFalse(
        any(level == 1 and module == "routes" for level, module, _name in direct_imports)
    )
```

Also add this entry to `RETIRED_LEGACY_FACADE_MODULES`:

```python
"rag_modules.interfaces.api.routes",
```

Replace `test_api_routes_register_only_versioned_operational_paths` with the complete owner scan:

```python
def test_api_routes_register_only_versioned_operational_paths(self) -> None:
    paths = tuple(
        RAG_MODULES_DIR / "interfaces" / "api" / filename
        for filename in ("build_routes.py", "operational_routes.py", "serving_routes.py")
    )
    sources: list[str] = []
    violations: list[str] = []

    def route_path(node: ast.AST) -> tuple[str, str] | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return ("unversioned", node.value)
        if not isinstance(node, ast.JoinedStr):
            return None
        has_api_prefix = any(
            isinstance(value, ast.FormattedValue)
            and isinstance(value.value, ast.Name)
            and value.value.id == "API_PREFIX"
            for value in node.values
        )
        if not has_api_prefix:
            return None
        suffix = "".join(
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
        return ("versioned", suffix)

    for path in paths:
        source = path.read_text(encoding="utf-8-sig")
        sources.append(source)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (
                    not isinstance(func, ast.Attribute)
                    or func.attr not in {"get", "post"}
                    or not isinstance(func.value, ast.Name)
                    or func.value.id != "app"
                    or not decorator.args
                ):
                    continue
                parsed_path = route_path(decorator.args[0])
                if parsed_path is None:
                    continue
                kind, parsed = parsed_path
                if kind == "unversioned":
                    violations.append(f"{path.name}:{node.name}: {parsed}")

    self.assertEqual(
        [],
        violations,
        "API route decorators must use canonical /v1 paths only.",
    )
    self.assertNotIn("_versioned_alias_route", "\n".join(sources))
```

- [ ] **Step 2: Run the structural and import-failure tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api_route_structure.py tests/test_public_surface_boundaries.py::PublicSurfaceLegacyBoundaryTests::test_retired_facade_import_paths_fail_instead_of_forwarding -q --basetemp=.pytest_cleanup_routes_red
```

Expected: FAIL because `app.py` still imports `.routes` and the module still exists.

- [ ] **Step 3: Bind application assembly directly to the route owners**

In `rag_modules/interfaces/api/app.py`, replace the `.routes` import block with these direct
imports, allowing Ruff to place them in sorted order:

```python
from .build_routes import register_build_routes
from .error_handlers import register_api_error_handlers
from .error_models import error_response_openapi
from .request_context import RequestContextMiddleware
from .security import ApiSecurityMiddleware, configure_openapi_security
from .serving_routes import register_serving_routes
```

Keep the existing `.services` and `.versioning` imports immediately after this block.

- [ ] **Step 4: Delete the API route forwarding module**

Use `apply_patch` to delete:

```text
rag_modules/interfaces/api/routes.py
```

- [ ] **Step 5: Run the focused API tests**

Run:

```powershell
python -m pytest tests/test_api_route_structure.py tests/test_api_public_surface.py tests/test_entrypoints.py tests/test_public_surface_boundaries.py -q --basetemp=.pytest_cleanup_routes_green
```

Expected: PASS.

Then run:

```powershell
rg -n "rag_modules\.interfaces\.api\.routes|from \.routes" rag_modules scripts tests -g "!tests/public_surface_boundary_helpers.py" -g "!tests/test_public_surface_boundaries.py"
```

Expected: exit code 1 with no matches.

- [ ] **Step 6: Commit the API route hard cutover**

```powershell
git add -- rag_modules/interfaces/api/app.py rag_modules/interfaces/api/routes.py tests/test_api_route_structure.py tests/public_surface_boundary_helpers.py tests/test_public_surface_boundaries.py
git commit -m "refactor: retire API route forwarding module"
```

### Task 4: Retirement Policy Synchronization

**Files:**

- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `docs/public_surface_retirement_plan.md`

**Interfaces:**

- Consumes: package version from `pyproject.toml` and the six retired module paths.
- Produces: current, test-bound documentation of the hard cutover and canonical owners.

- [ ] **Step 1: Extend the policy-document contract**

In `test_retirement_plan_document_states_current_policy`, add these strings to the existing
`expected` tuple:

```python
"rag_modules.graph.cache",
"rag_modules.graph.evidence",
"rag_modules.graph.query",
"rag_modules.graph.reasoning",
"rag_modules.graph.retrieval",
"rag_modules.interfaces.api.routes",
```

In `test_version_governance_distinguishes_package_api_and_compat_versions`, add this assertion
after `normalized_policy` is created:

```python
self.assertIn(f"current package version is `{package_version}`", normalized_policy)
```

- [ ] **Step 2: Run the policy tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceLegacyBoundaryTests::test_retirement_plan_document_states_current_policy tests/test_public_surface_boundaries.py::PublicSurfaceLegacyBoundaryTests::test_version_governance_distinguishes_package_api_and_compat_versions -q --basetemp=.pytest_cleanup_docs_red
```

Expected: FAIL because the policy still says `0.3.0` and does not name the six newly retired
paths.

- [ ] **Step 3: Update current package-version wording**

In `docs/public_surface_retirement_plan.md`, change the package-version paragraph to:

```markdown
- Package version comes from `[project].version` in `pyproject.toml`. The
  current package version is `0.4.0.dev0`, which is the development release
  axis for Python package publication and customer upgrade notes.
```

- [ ] **Step 4: Record the internal hard cutover and canonical owners**

After the paragraph listing old shim modules without formal facade roles, add:

```markdown
The `0.4.0.dev0` internal hard cutover also retires namespace-only forwarding
modules that own no behavior:

- `rag_modules.graph.cache` -> `rag_modules.graph.cache_stats` and
  `rag_modules.graph.cache_warmup`
- `rag_modules.graph.evidence` -> `rag_modules.graph.evidence_builder`,
  `rag_modules.graph.evidence_orchestrator`, and `rag_modules.graph.path_ranker`
- `rag_modules.graph.query` -> `rag_modules.graph.query_executor`,
  `rag_modules.graph.query_intent`, and `rag_modules.graph.query_resolution`
- `rag_modules.graph.reasoning` -> `rag_modules.graph.reasoning_strategy`
- `rag_modules.graph.retrieval` -> the focused `rag_modules.graph.retrieval_*`
  modules and `rag_modules.graph.rag_retrieval`
- `rag_modules.interfaces.api.routes` -> `rag_modules.interfaces.api.build_routes`
  and `rag_modules.interfaces.api.serving_routes`

These exact retired paths fail instead of forwarding. Package-level exports
from `rag_modules.graph` remain supported and resolve directly to owner modules.
```

Add this bullet under `## Retired Facade History`:

```markdown
- Graph cache, evidence, query, reasoning, and retrieval namespace forwarders,
  plus the API routes forwarder, retired in favor of their focused owner
  modules during the `0.4.0.dev0` development cycle.
```

- [ ] **Step 5: Run documentation and public-surface tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q --basetemp=.pytest_cleanup_docs_green
```

Expected: PASS.

- [ ] **Step 6: Commit the synchronized policy**

```powershell
git add -- docs/public_surface_retirement_plan.md tests/test_public_surface_boundaries.py
git commit -m "docs: record internal facade hard cutover"
```

### Task 5: Full Validation, Worktree Removal, and Final Local-State Cleanup

**Files and state:**

- Verify: all tracked implementation, test, policy, and design changes.
- Remove operationally: `.worktrees/performance-hotspot-ratchet`.
- Remove operationally: approved generated caches, reports, coverage files, and pytest basetemps.
- Preserve: `.env`, `.venv/`, `storage/`, `volumes/`, `agent/`, formal entrypoints, and
  `docs/superpowers/`.

**Interfaces:**

- Consumes: Tasks 1-4 and the recorded `codex/performance-hotspot-ratchet` branch tip.
- Produces: verified release-sensitive code, a preserved worktree branch, and a clean local
  directory without approved generated pollution.

- [ ] **Step 1: Run the combined focused regression slice**

```powershell
python -m pytest tests/test_enterprise_governance.py tests/test_graph_cache_stats.py tests/test_graph_retrieval_executor.py tests/test_retrieval_service_factories.py tests/test_api_route_structure.py tests/test_api_public_surface.py tests/test_entrypoints.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q --basetemp=.pytest_cleanup_focused
```

Expected: PASS.

- [ ] **Step 2: Run the complete API slice required by `AGENTS.md`**

```powershell
python -m pytest tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py -q --basetemp=.pytest_cleanup_api
```

Expected: PASS.

- [ ] **Step 3: Run formatting, lint, and typing checks**

```powershell
python -m ruff check --no-cache rag_modules tests scripts main.py main_build_service.py main_build_worker.py
python -m ruff format --check --no-cache rag_modules tests scripts main.py main_build_service.py main_build_worker.py
python -m mypy --config-file pyproject.toml --cache-dir .mypy_cleanup_verify
```

Expected: all commands exit 0. If Ruff formatting changes are required, format only touched Python
files, inspect the diff, and repeat all three commands.

- [ ] **Step 4: Run the full test suite**

```powershell
python -m pytest -q --basetemp=.pytest_cleanup_full_20260714
```

Expected: PASS. Treat an access-denied error on an old cache or basetemp as an environmental ACL
problem; remove only that verified generated path and rerun.

- [ ] **Step 5: Run the offline release gate**

```powershell
python scripts/release_gate.py --output-dir eval/reports/repository-cleanup-release-gate
```

Expected: PASS with report and summary paths under the supplied generated output directory.

- [ ] **Step 6: Remove the linked worktree while preserving its branch tip**

Run this as one PowerShell block so the before/after commit comparison stays in memory:

```powershell
$worktree = ".worktrees/performance-hotspot-ratchet"
$branch = "codex/performance-hotspot-ratchet"
$dirty = git -C $worktree status --porcelain=v1
if ($dirty) { throw "Refusing to remove dirty worktree: $worktree" }
$tipBefore = git -C $worktree rev-parse HEAD
$branchBefore = git -C $worktree branch --show-current
if ($branchBefore -ne $branch) { throw "Unexpected worktree branch: $branchBefore" }
git show-ref --verify "refs/heads/$branch"
git worktree remove -- $worktree
if (Test-Path -LiteralPath $worktree) { throw "Worktree directory still exists" }
$tipAfter = git rev-parse $branch
if ($tipAfter -ne $tipBefore) { throw "Branch tip changed during worktree removal" }
git worktree prune
Write-Output "preserved $branch at $tipAfter"
```

Expected: the directory is absent, the branch still exists, and both printed tips are identical.
This command writes Git worktree metadata and may require the sandbox's narrow Git escalation.

- [ ] **Step 7: Remove only verified generated local state**

Run this PowerShell block from the repository root:

```powershell
$root = (Resolve-Path -LiteralPath ".").Path
$prefix = $root.TrimEnd("\") + "\"
$targets = [System.Collections.Generic.List[string]]::new()

foreach ($relative in @(
    ".mypy_cache",
    ".mypy_cleanup_verify",
    ".ruff_cache",
    ".superpowers",
    "__pycache__",
    "eval/reports",
    ".coverage",
    "coverage.json",
    "coverage.xml"
)) {
    $candidate = Join-Path $root $relative
    if (Test-Path -LiteralPath $candidate) { $targets.Add($candidate) }
}

Get-ChildItem -LiteralPath $root -Force -Directory |
    Where-Object { $_.Name -like ".pytest_*" } |
    ForEach-Object { $targets.Add($_.FullName) }

foreach ($base in @("rag_modules", "scripts", "tests")) {
    $basePath = Join-Path $root $base
    Get-ChildItem -LiteralPath $basePath -Directory -Filter "__pycache__" -Recurse -Force |
        ForEach-Object { $targets.Add($_.FullName) }
}

foreach ($target in ($targets | Sort-Object -Unique)) {
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if ($resolved -eq $root -or -not $resolved.StartsWith(
        $prefix,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing to delete path outside repository root: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
```

Expected: generated targets are absent. The script never enumerates `.venv`, `storage`, `volumes`,
`agent`, or `docs/superpowers`. If one target fails with access denied, retry only that resolved
target with the sandbox's narrow filesystem escalation.

- [ ] **Step 8: Run final structural and protected-state verification**

```powershell
rg -n "rag_modules\.graph\.(cache|evidence|query|reasoning|retrieval)\b|rag_modules\.interfaces\.api\.routes|from \.routes" rag_modules scripts tests -g "!tests/public_surface_boundary_helpers.py" -g "!tests/test_public_surface_boundaries.py"
git diff --check
git diff -- agent
git status --short --branch
git status --short --ignored
git worktree list --porcelain
git show-ref --verify refs/heads/codex/performance-hotspot-ratchet
```

Expected:

- `rg` exits 1 with no matches;
- `git diff --check` and `git diff -- agent` print nothing;
- tracked status is clean and shows only the branch relationship;
- ignored status retains protected local paths such as `.env`, `.venv/`, `storage/`, and
  `volumes/`, but not the deleted caches or generated reports;
- worktree output does not contain `.worktrees/performance-hotspot-ratchet`;
- `show-ref` succeeds for `codex/performance-hotspot-ratchet`.

Finally verify protected paths explicitly:

```powershell
$protected = @(
    ".env",
    ".venv",
    "storage",
    "volumes",
    "agent",
    "docs/superpowers",
    "main.py",
    "main_build_service.py",
    "main_build_worker.py"
)
$missing = $protected | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) { throw "Protected paths missing: $($missing -join ', ')" }
```

Expected: no exception. If an unexpected tracked file changed, stop and inspect it rather than
committing generated cleanup noise.

- [ ] **Step 9: Mark the implementation plan complete and verify final status**

Only after Steps 1-8 pass, change this plan's header from `Status: active` to `Status: completed`,
then commit only the plan status:

```powershell
git add -- docs/superpowers/plans/2026-07-14-repository-hygiene-and-facade-retirement.md
git commit -m "docs: complete repository hygiene plan"
git status --short --branch
```

Expected: the plan-status commit succeeds and tracked status is clean.
