# OpenTelemetry 1.43 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the OpenTelemetry SDK, OTLP HTTP exporter, and their resolved protocol family to 1.43.0 as one validated dependency change.

**Architecture:** Upgrade the two direct OpenTelemetry pins together because exporter 1.43.0 requires `opentelemetry-sdk~=1.43.0`. Leave API, common, proto, and semantic conventions transitive, then regenerate both locks with the repository script so the whole compatible family resolves atomically.

**Tech Stack:** Python 3.11, OpenTelemetry OTLP HTTP exporter, pip-tools, pytest.

## Global Constraints

- Base the branch on the latest `development` commit and target the pull request to `development`.
- Set the direct exporter pin to exactly `opentelemetry-exporter-otlp-proto-http==1.43.0`.
- Set the direct SDK pin to exactly `opentelemetry-sdk==1.43.0`.
- Keep `opentelemetry-proto` transitive; do not add it to `pyproject.toml`.
- Resolve `opentelemetry-proto==1.43.0` in both generated lock files.
- Use Python 3.11 and pip-tools; never hand-edit the final lock output.
- Preserve all unrelated direct and transitive versions unless the resolver proves a compatibility change is required.
- Do not modify `agent/` or its independent requirements.
- Follow RED-GREEN TDD for the dependency policy.

## Resolver Evidence

The first lock compilation with exporter 1.43.0 and SDK 1.42.1 failed deterministically.
Package metadata reports `opentelemetry-sdk~=1.43.0` as an exporter requirement. A pip dry-run
confirmed the minimal compatible family: API 1.43.0, exporter common 1.43.0, exporter HTTP 1.43.0,
proto 1.43.0, SDK 1.43.0, and semantic conventions 0.64b0.

---

### Task 1: Ratchet the Exporter and Protocol Pair

**Files:**
- Modify: `tests/test_dependency_isolation.py`

**Interfaces:**
- Consumes: `_pinned_requirement_version(entries: list[str], package_name: str) -> str`, `_requirement_names(entries: list[str]) -> set[str]`, and both generated locks.
- Produces: a dependency policy requiring SDK/exporter 1.43.0 in source and the complete compatible OpenTelemetry family in both locks, with no direct proto dependency.

- [ ] **Step 1: Write the failing OpenTelemetry dependency test**

Add this method after `test_pyproject_is_dependency_source_of_truth` in `DependencyIsolationTests`:

```python
    def test_opentelemetry_family_matches_approved_upgrade(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = pyproject["project"]["dependencies"]
        runtime_names = _requirement_names(runtime_dependencies)
        runtime_lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertEqual(
            _pinned_requirement_version(
                runtime_dependencies,
                "opentelemetry-exporter-otlp-proto-http",
            ),
            "1.43.0",
        )
        self.assertEqual(
            _pinned_requirement_version(runtime_dependencies, "opentelemetry-sdk"),
            "1.43.0",
        )
        self.assertNotIn("opentelemetry-proto", runtime_names)
        expected_lock_entries = {
            "opentelemetry-api==1.43.0",
            "opentelemetry-exporter-otlp-proto-common==1.43.0",
            "opentelemetry-exporter-otlp-proto-http==1.43.0",
            "opentelemetry-proto==1.43.0",
            "opentelemetry-sdk==1.43.0",
            "opentelemetry-semantic-conventions==0.64b0",
        }
        for lock in (runtime_lock, dev_lock):
            for entry in expected_lock_entries:
                self.assertIn(entry, lock)
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tests/test_dependency_isolation.py::DependencyIsolationTests::test_opentelemetry_family_matches_approved_upgrade -q --basetemp=.pytest_otel_red_sdk
```

Expected: FAIL because the direct SDK pin is `1.42.1` rather than `1.43.0`.

### Task 2: Upgrade the Direct Pins and Regenerate the OpenTelemetry Family

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `requirements.txt`
- Regenerate: `requirements-dev.txt`

**Interfaces:**
- Consumes: the direct exporter and SDK declarations plus Python 3.11 pip-tools resolution.
- Produces: SDK/exporter 1.43.0 in source and the compatible 1.43 family in both generated locks.

- [ ] **Step 1: Update both required direct pins**

Apply this exact replacement in `pyproject.toml`:

```text
opentelemetry-exporter-otlp-proto-http==1.42.1 -> opentelemetry-exporter-otlp-proto-http==1.43.0
opentelemetry-sdk==1.42.1 -> opentelemetry-sdk==1.43.0
```

- [ ] **Step 2: Regenerate both locks with the repository script**

```powershell
.\scripts\compile_locks.ps1
```

Expected: the script verifies Python 3.11 and regenerates both locks with the compatible 1.43 family.

- [ ] **Step 3: Run the focused dependency test and verify GREEN**

Run the Task 1 Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 4: Inspect resolver scope**

```powershell
git diff -- pyproject.toml requirements.txt requirements-dev.txt
```

Expected: `pyproject.toml` changes only the SDK and exporter pins; locks change the six OpenTelemetry family entries documented in Resolver Evidence.

- [ ] **Step 5: Commit the dependency upgrade**

```powershell
git add tests/test_dependency_isolation.py pyproject.toml requirements.txt requirements-dev.txt
git commit -m "deps: upgrade opentelemetry family to 1.43"
```

### Task 3: Validate the Resolved Telemetry Environment

**Files:**
- Verify: `requirements-dev.txt`
- Verify: `rag_modules/telemetry.py`
- Verify: `tests/test_answer_workflow.py`
- Verify: API test modules named in `AGENTS.md`

**Interfaces:**
- Consumes: the regenerated development lock and existing telemetry construction path.
- Produces: an isolated installed environment with no broken requirements and passing telemetry/API behavior.

- [ ] **Step 1: Create an ignored worktree-local environment**

```powershell
python -m venv .venv --system-site-packages
```

Expected: `.venv/` exists only inside this ignored worktree.

- [ ] **Step 2: Install the generated development lock and current project metadata**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
```

Expected: installation exits 0 and the editable metadata reflects the current `pyproject.toml`.

- [ ] **Step 3: Verify installed versions and requirement compatibility**

```powershell
.\.venv\Scripts\python.exe -c "import importlib.metadata as m; print(m.version('opentelemetry-exporter-otlp-proto-http')); print(m.version('opentelemetry-proto')); print(m.version('opentelemetry-sdk'))"
.\.venv\Scripts\python.exe -m pip check
```

Expected: all three versions are `1.43.0`; pip reports no broken requirements.

- [ ] **Step 4: Run dependency, telemetry, and API compatibility tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dependency_isolation.py tests/test_answer_workflow.py tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q --basetemp=.pytest_otel_focused
```

Expected: all focused tests and subtests pass.

### Task 4: Validate and Publish the OpenTelemetry Branch

**Files:**
- Verify: `pyproject.toml`
- Verify: `requirements.txt`
- Verify: `requirements-dev.txt`
- Verify: `tests/test_dependency_isolation.py`
- Verify: `docs/superpowers/plans/2026-07-14-opentelemetry-1-43-upgrade.md`

**Interfaces:**
- Consumes: the installed and focused-tested dependency graph from Task 3.
- Produces: a pushed `codex/opentelemetry-1-43` branch and draft pull request targeting `development`.

- [ ] **Step 1: Run Ruff and mypy in the resolved environment**

```powershell
.\.venv\Scripts\python.exe -m ruff check . --no-cache
.\.venv\Scripts\python.exe -m ruff format --check . --no-cache
.\.venv\Scripts\python.exe -m mypy --config-file pyproject.toml --cache-dir .mypy_otel
```

Expected: all commands exit 0.

- [ ] **Step 2: Run the complete test suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_otel_full
```

Expected: all tests and subtests pass.

- [ ] **Step 3: Run the offline release gate**

```powershell
.\.venv\Scripts\python.exe scripts/release_gate.py --output-dir .release_otel
```

Expected: all offline cases pass.

- [ ] **Step 4: Remove generated local validation state**

```powershell
$root = (Resolve-Path '.').Path
$targets = @(
    '.venv',
    '.mypy_otel',
    '.pytest_otel_baseline',
    '.pytest_otel_red',
    '.pytest_otel_focused',
    '.pytest_otel_full',
    '.release_otel',
    '.pytest_cache',
    'graph_rag_c9.egg-info'
)
foreach ($relative in $targets) {
    if (Test-Path -LiteralPath $relative) {
        $resolved = (Resolve-Path -LiteralPath $relative).Path
        if (-not $resolved.StartsWith($root + [IO.Path]::DirectorySeparatorChar)) {
            throw "Refusing to remove path outside worktree: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
```

Expected: only the listed generated paths are absent; tracked source and plan files remain.

- [ ] **Step 5: Inspect the final diff and status**

```powershell
git diff development...HEAD --check
git status --short --branch
git log --oneline development..HEAD
```

Expected: only the plan, dependency policy, exporter pin, and generated lock updates are present.

- [ ] **Step 6: Push and create the draft pull request**

```powershell
git push -u origin codex/opentelemetry-1-43
gh pr create --draft --base development --head codex/opentelemetry-1-43 --title "deps: upgrade OpenTelemetry family to 1.43" --body "Upgrade the SDK, OTLP HTTP exporter, and resolved protocol family to 1.43.0, then verify telemetry behavior."
```

Expected: the remote branch exists and the pull request base is `development`.
