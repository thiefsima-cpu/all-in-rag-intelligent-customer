# Setuptools 83 Security Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove PYSEC-2026-3447 from the shared `development` dependency baseline by
upgrading setuptools from 80.9.0 to 83.0.0 everywhere the repository installs or locks it.

**Architecture:** Keep the change isolated in one security branch and PR. Treat
`pyproject.toml` as the source of truth, align the Windows bootstrap pin, and regenerate
both locks with Python 3.11. Merge the security PR before synchronizing the three Draft PRs.

**Tech Stack:** Python 3.11, setuptools, pip-tools, pip-audit, pytest, Ruff, mypy, GitHub Actions.

## Global Constraints

- Target branch is `development`.
- Use `setuptools>=83.0.0` as the build-system floor.
- Lock `setuptools==83.0.0` in both generated requirements files.
- Keep `scripts/bootstrap_env.ps1` pinned to `setuptools==83.0.0`.
- Do not modify the independent `agent/` dependency set.
- Use the direct branch workflow requested for this repository; do not create another worktree.
- Confirm `python` reports Python 3.11 before compiling locks or running gates.
- Do not merge until strict pip-audit, full pytest, release gate, and GitHub CI are green.

---

### Task 1: Add a dependency-alignment regression test

**Files:**
- Modify: `tests/test_dependency_isolation.py`

**Interfaces:**
- Consumes: build-system requirements, committed lock files, and the Windows bootstrap script.
- Produces: `test_setuptools_security_floor_matches_bootstrap_and_locks`.

- [ ] **Step 1: Add the failing test**

```python
def test_setuptools_security_floor_matches_bootstrap_and_locks(self) -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    self.assertIn("setuptools>=83.0.0", pyproject["build-system"]["requires"])
    self.assertIn(
        '"setuptools==83.0.0"',
        (root / "scripts" / "bootstrap_env.ps1").read_text(encoding="utf-8"),
    )
    for lock_name in ("requirements.txt", "requirements-dev.txt"):
        with self.subTest(lock_name=lock_name):
            lock = (root / lock_name).read_text(encoding="utf-8")
            self.assertIn("setuptools==83.0.0", lock)
```

- [ ] **Step 2: Run the test and verify RED**

```powershell
python -m pytest tests/test_dependency_isolation.py::DependencyIsolationTests::test_setuptools_security_floor_matches_bootstrap_and_locks -q --basetemp=.pytest_setuptools_red -p no:cacheprovider
```

Expected: FAIL because the current build-system requirement is `setuptools>=80.9.0`.

### Task 2: Upgrade and regenerate the dependency baseline

**Files:**
- Modify: `pyproject.toml`
- Modify: `scripts/bootstrap_env.ps1`
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`

**Interfaces:**
- Consumes: the regression test from Task 1 and `scripts/compile_locks.ps1`.
- Produces: one resolver-consistent setuptools 83.0.0 baseline.

- [ ] **Step 1: Raise the source-of-truth and bootstrap versions**

```toml
[build-system]
requires = ["setuptools>=83.0.0", "wheel>=0.47.0"]
```

Update the bootstrap installer argument from `"setuptools==80.9.0"` to
`"setuptools==83.0.0"`.

- [ ] **Step 2: Regenerate both locks with Python 3.11**

```powershell
python -m piptools compile pyproject.toml --output-file requirements.txt --strip-extras --allow-unsafe --upgrade-package setuptools --pip-args="--index-url https://pypi.org/simple"
python -m piptools compile pyproject.toml --extra=dev --output-file requirements-dev.txt --strip-extras --allow-unsafe --upgrade-package setuptools --pip-args="--index-url https://pypi.org/simple"
```

Expected: both lock files contain exactly `setuptools==83.0.0`.

- [ ] **Step 3: Run the regression test and verify GREEN**

```powershell
python -m pytest tests/test_dependency_isolation.py::DependencyIsolationTests::test_setuptools_security_floor_matches_bootstrap_and_locks -q --basetemp=.pytest_setuptools_green -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 4: Prove the original CI failure is gone**

```powershell
python -m pip_audit -r requirements.txt -r requirements-dev.txt --strict --progress-spinner off
```

Expected: `No known vulnerabilities found`.

### Task 3: Verify and publish the security PR

**Files:**
- Verify only: all changed files from Tasks 1 and 2.

**Interfaces:**
- Consumes: the upgraded dependency baseline.
- Produces: a reviewable GitHub PR targeting `development`.

- [ ] **Step 1: Run focused and full local verification**

```powershell
python -m pytest tests/test_dependency_isolation.py -q --basetemp=.pytest_setuptools_focused -p no:cacheprovider
python -m ruff check . --no-cache
python -m ruff format --check . --no-cache
python -m mypy --config-file pyproject.toml --cache-dir .mypy_setuptools
python -m pytest -q --basetemp=.pytest_setuptools_full -p no:cacheprovider
python scripts/release_gate.py --output-dir .release_setuptools
```

Expected: all commands exit zero.

- [ ] **Step 2: Commit and push**

```powershell
git add pyproject.toml requirements.txt requirements-dev.txt scripts/bootstrap_env.ps1 tests/test_dependency_isolation.py docs/superpowers/plans/2026-07-14-setuptools-83-security-fix.md
git commit -m "fix: upgrade setuptools for security advisory"
git push -u origin codex/setuptools-83-security
```

- [ ] **Step 3: Create a ready PR**

```powershell
gh pr create --base development --head codex/setuptools-83-security --title "fix: upgrade setuptools for security advisory" --body "Upgrades the shared setuptools baseline to 83.0.0 to fix PYSEC-2026-3447, aligns bootstrap and lock files, and adds a regression test."
```

Expected: an open, non-draft PR targeting `development`.

### Task 4: Merge and synchronize dependent PRs

**Files:**
- Git branch integration only.

**Interfaces:**
- Consumes: a green security PR.
- Produces: updated `development` plus refreshed PRs #29, #30, and #31.

- [ ] **Step 1: Merge only after GitHub checks are green**

```powershell
gh pr checks codex/setuptools-83-security --repo thiefsima-cpu/all-in-rag-intelligent-customer --watch
gh pr merge codex/setuptools-83-security --repo thiefsima-cpu/all-in-rag-intelligent-customer --merge --delete-branch
```

- [ ] **Step 2: Fast-forward local `development`**

```powershell
git switch development
git pull --ff-only origin development
```

- [ ] **Step 3: Merge the updated base into each dependent branch**

```powershell
git -C .worktrees/ci-actions-node24 merge development
git -C .worktrees/fastapi-0-139 merge development
git -C .worktrees/opentelemetry-1-43 merge development
```

- [ ] **Step 4: Revalidate and push all dependent branches**

Run the relevant focused tests, strict pip-audit for dependency PRs, and
`git diff --check development...HEAD` before pushing each branch.

Expected: PRs #29, #30, and #31 receive fresh successful CI runs without
`PYSEC-2026-3447`.
