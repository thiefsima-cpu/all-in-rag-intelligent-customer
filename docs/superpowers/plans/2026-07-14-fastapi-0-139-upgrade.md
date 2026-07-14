# FastAPI 0.139 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the main application to FastAPI 0.139.0 and absorb the compatible AnyIO 4.14.1 lock update without introducing AnyIO as a direct dependency.

**Architecture:** Keep `pyproject.toml` as the dependency source of truth with FastAPI as the only changed direct pin. Regenerate both locks with Python 3.11, then use pip-tools' targeted upgrade option for the transitive AnyIO pin so the rest of the resolved graph remains stable and reproducible.

**Tech Stack:** Python 3.11, FastAPI, AnyIO, pip-tools, pytest.

## Global Constraints

- Base the branch on the latest `development` commit and target the pull request to `development`.
- Set the direct FastAPI dependency to exactly `fastapi==0.139.0`.
- Keep AnyIO transitive; do not add it to `pyproject.toml`.
- Resolve AnyIO to exactly `anyio==4.14.1` in both generated lock files.
- Use Python 3.11 and pip-tools; never hand-edit the final lock output.
- Preserve all other direct dependency pins unless the resolver proves a compatibility change is required.
- Do not modify `agent/` or its independent requirements.
- Follow RED-GREEN TDD for the dependency policy.

---

### Task 1: Ratchet the FastAPI and AnyIO Upgrade

**Files:**
- Modify: `tests/test_dependency_isolation.py`

**Interfaces:**
- Consumes: `_pinned_requirement_version(entries: list[str], package_name: str) -> str` and the two generated lock files.
- Produces: a dependency governance test that requires FastAPI 0.139.0 in the source and locks, plus AnyIO 4.14.1 in both locks.

- [ ] **Step 1: Write the failing dependency policy test**

Add this method after `test_pyproject_is_dependency_source_of_truth` in `DependencyIsolationTests`:

```python
    def test_fastapi_and_anyio_match_approved_upgrade(self) -> None:
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        runtime_dependencies = pyproject["project"]["dependencies"]
        runtime_lock = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        dev_lock = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")

        self.assertEqual(
            _pinned_requirement_version(runtime_dependencies, "fastapi"),
            "0.139.0",
        )
        self.assertNotIn("anyio", _requirement_names(runtime_dependencies))
        for lock in (runtime_lock, dev_lock):
            self.assertIn("fastapi==0.139.0", lock)
            self.assertIn("anyio==4.14.1", lock)
```

- [ ] **Step 2: Run the focused test and verify RED**

```powershell
python -m pytest tests/test_dependency_isolation.py::DependencyIsolationTests::test_fastapi_and_anyio_match_approved_upgrade -q --basetemp=.pytest_fastapi_red
```

Expected: FAIL because the direct FastAPI pin is `0.136.3`.

### Task 2: Upgrade the Source Pin and Regenerate Locks

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `requirements.txt`
- Regenerate: `requirements-dev.txt`

**Interfaces:**
- Consumes: the direct dependency declaration in `pyproject.toml` and Python 3.11 pip-tools resolution.
- Produces: FastAPI 0.139.0 in source/runtime/dev and AnyIO 4.14.1 in both generated locks.

- [ ] **Step 1: Update only the FastAPI direct pin**

Apply this exact replacement in `pyproject.toml`:

```text
fastapi==0.136.3 -> fastapi==0.139.0
```

- [ ] **Step 2: Regenerate both locks with the repository script**

```powershell
.\scripts\compile_locks.ps1
```

Expected: the script verifies Python 3.11 and regenerates `requirements.txt` and `requirements-dev.txt` from `pyproject.toml`.

- [ ] **Step 3: Regenerate the runtime lock with a targeted AnyIO upgrade**

```powershell
python -m piptools compile pyproject.toml --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple" --upgrade-package anyio
```

Expected: the generated runtime lock contains `fastapi==0.139.0` and `anyio==4.14.1` without broad unrelated upgrades.

- [ ] **Step 4: Regenerate the development lock with the same targeted upgrade**

```powershell
python -m piptools compile pyproject.toml --extra=dev --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple" --upgrade-package anyio
```

Expected: the generated development lock contains the same FastAPI and AnyIO versions.

- [ ] **Step 5: Run the focused dependency test and verify GREEN**

Run the Task 1 Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 6: Confirm the resolver did not broaden the direct dependency scope**

```powershell
git diff -- pyproject.toml requirements.txt requirements-dev.txt
```

Expected: `pyproject.toml` changes only the FastAPI pin; generated locks change only resolver output attributable to FastAPI and AnyIO.

- [ ] **Step 7: Commit the dependency upgrade**

```powershell
git add tests/test_dependency_isolation.py pyproject.toml requirements.txt requirements-dev.txt
git commit -m "deps: upgrade fastapi to 0.139"
```

### Task 3: Validate API Compatibility and Publish

**Files:**
- Verify: `pyproject.toml`
- Verify: `requirements.txt`
- Verify: `requirements-dev.txt`
- Verify: `tests/test_dependency_isolation.py`
- Verify: `docs/superpowers/plans/2026-07-14-fastapi-0-139-upgrade.md`

**Interfaces:**
- Consumes: the regenerated dependency graph from Task 2.
- Produces: a pushed `codex/fastapi-0-139` branch and draft pull request targeting `development`.

- [ ] **Step 1: Run dependency and API test slices**

```powershell
python -m pytest tests/test_dependency_isolation.py tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q --basetemp=.pytest_fastapi_api
```

Expected: all dependency, serving, build, security, SSE, public-surface, and entrypoint tests pass.

- [ ] **Step 2: Run Ruff and mypy**

```powershell
python -m ruff check . --no-cache
python -m ruff format --check . --no-cache
python -m mypy --config-file pyproject.toml --cache-dir .mypy_fastapi
```

Expected: all commands exit 0.

- [ ] **Step 3: Run the complete test suite**

```powershell
python -m pytest -q --basetemp=.pytest_fastapi_full
```

Expected: all tests and subtests pass.

- [ ] **Step 4: Run the offline release gate**

```powershell
python scripts/release_gate.py --output-dir .release_fastapi
```

Expected: all offline cases pass.

- [ ] **Step 5: Inspect the final diff and status**

```powershell
git diff development...HEAD --check
git status --short --branch
git log --oneline development..HEAD
```

Expected: only the plan, dependency policy, direct FastAPI pin, and generated lock updates are present; generated verification paths are absent or ignored.

- [ ] **Step 6: Push and create the draft pull request**

```powershell
git push -u origin codex/fastapi-0-139
gh pr create --draft --base development --head codex/fastapi-0-139 --title "deps: upgrade FastAPI to 0.139" --body "Upgrade FastAPI to 0.139.0, resolve AnyIO 4.14.1 in generated locks, and verify API compatibility."
```

Expected: the remote branch exists and the pull request base is `development`.
