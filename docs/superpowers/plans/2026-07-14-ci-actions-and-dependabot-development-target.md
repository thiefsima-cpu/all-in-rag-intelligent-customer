# CI Actions and Dependabot Development Target Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route automated dependency updates through `development` and move the repository's GitHub Actions to the approved Node 24-compatible major versions.

**Architecture:** Keep repository governance declarative: `.github/dependabot.yml` owns the integration target, while `tests/test_enterprise_governance.py` ratchets the target and workflow action majors. Update both CI and release workflows atomically so no long-lived branch uses mixed action majors.

**Tech Stack:** GitHub Actions YAML, Dependabot YAML, Python 3.11, pytest.

## Global Constraints

- Base all work on the latest `development` commit and open the pull request against `development`.
- Set `target-branch: "development"` for both the `pip` and `github-actions` Dependabot ecosystems.
- Use `actions/checkout@v7`, `actions/setup-python@v6`, `actions/upload-artifact@v7`, and `gitleaks/gitleaks-action@v3`.
- Preserve `ubuntu-latest`, Python `3.11`, workflow permissions, cache settings, job ordering, and release behavior.
- Do not modify `agent/`, application dependencies, generated lock files, or unrelated workflows.
- Follow RED-GREEN TDD for both governance behaviors.

---

### Task 1: Ratchet Dependabot to the Integration Branch

**Files:**
- Modify: `tests/test_enterprise_governance.py`
- Modify: `.github/dependabot.yml`

**Interfaces:**
- Consumes: repository text helper `_read(relative_path: str) -> str`.
- Produces: a governance assertion requiring exactly two Dependabot targets for `development`.

- [ ] **Step 1: Write the failing Dependabot target test**

Add this test after `test_ci_targets_all_long_lived_branches`:

```python
def test_dependabot_targets_development_for_all_ecosystems() -> None:
    dependabot = _read(".github/dependabot.yml")

    assert dependabot.count('target-branch: "development"') == 2
    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_dependabot_targets_development_for_all_ecosystems -q --basetemp=.pytest_ci_actions_red_dependabot
```

Expected: FAIL because the current file contains zero `target-branch: "development"` entries.

- [ ] **Step 3: Add the minimal Dependabot configuration**

Add the same property to each update entry immediately after `directory: "/"`:

```yaml
    target-branch: "development"
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Commit the Dependabot target policy**

```powershell
git add tests/test_enterprise_governance.py .github/dependabot.yml
git commit -m "ci: target dependabot updates to development"
```

### Task 2: Ratchet Node 24-Compatible Action Majors

**Files:**
- Modify: `tests/test_enterprise_governance.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: repository text helper `_read(relative_path: str) -> str`.
- Produces: exact occurrence checks for all upgraded action majors and rejection checks for their retired majors.

- [ ] **Step 1: Write the failing workflow-major test**

Add this test after the Dependabot target test:

```python
def test_workflows_use_node24_compatible_action_majors() -> None:
    ci = _read(".github/workflows/ci.yml")
    release = _read(".github/workflows/release.yml")
    workflows = ci + release

    assert ci.count("actions/checkout@v7") == 4
    assert release.count("actions/checkout@v7") == 1
    assert ci.count("actions/setup-python@v6") == 2
    assert release.count("actions/setup-python@v6") == 1
    assert ci.count("actions/upload-artifact@v7") == 1
    assert release.count("actions/upload-artifact@v7") == 1
    assert ci.count("gitleaks/gitleaks-action@v3") == 1

    for retired_action in (
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "gitleaks/gitleaks-action@v2",
    ):
        assert retired_action not in workflows
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py::test_workflows_use_node24_compatible_action_majors -q --basetemp=.pytest_ci_actions_red_majors
```

Expected: FAIL on the first missing `actions/checkout@v7` assertion.

- [ ] **Step 3: Upgrade only the action major references**

Apply these exact replacements in both workflow files:

```text
actions/checkout@v4 -> actions/checkout@v7
actions/setup-python@v5 -> actions/setup-python@v6
actions/upload-artifact@v4 -> actions/upload-artifact@v7
gitleaks/gitleaks-action@v2 -> gitleaks/gitleaks-action@v3
```

Do not change workflow job names, triggers, permissions, inputs, shell commands, or artifact paths.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Step 2 command again.

Expected: `1 passed`.

- [ ] **Step 5: Run the complete governance test module**

Run:

```powershell
python -m pytest tests/test_enterprise_governance.py -q --basetemp=.pytest_ci_actions_governance
```

Expected: all tests pass.

- [ ] **Step 6: Commit the workflow upgrades**

```powershell
git add tests/test_enterprise_governance.py .github/workflows/ci.yml .github/workflows/release.yml
git commit -m "ci: upgrade actions for node 24 runners"
```

### Task 3: Validate and Publish the CI Branch

**Files:**
- Verify: `.github/dependabot.yml`
- Verify: `.github/workflows/ci.yml`
- Verify: `.github/workflows/release.yml`
- Verify: `tests/test_enterprise_governance.py`
- Verify: `docs/superpowers/specs/2026-07-14-development-integration-branch-hygiene-design.md`
- Verify: `docs/superpowers/plans/2026-07-14-ci-actions-and-dependabot-development-target.md`

**Interfaces:**
- Consumes: the committed policy and action-major changes from Tasks 1 and 2.
- Produces: a pushed `codex/ci-actions-node24` branch and a draft pull request targeting `development`.

- [ ] **Step 1: Run repository formatting and lint checks**

```powershell
python -m ruff check . --no-cache
python -m ruff format --check . --no-cache
```

Expected: both commands exit 0.

- [ ] **Step 2: Run mypy with a branch-local cache**

```powershell
python -m mypy --config-file pyproject.toml --cache-dir .mypy_ci_actions
```

Expected: success with no issues.

- [ ] **Step 3: Run the complete test suite**

```powershell
python -m pytest -q --basetemp=.pytest_ci_actions_full
```

Expected: all tests and subtests pass.

- [ ] **Step 4: Run the offline release gate**

```powershell
python scripts/release_gate.py --output-dir .release_ci_actions
```

Expected: all offline release cases pass.

- [ ] **Step 5: Inspect the final diff and repository status**

```powershell
git diff development...HEAD --check
git status --short --branch
git log --oneline development..HEAD
```

Expected: no whitespace errors; only the approved branch commits are ahead of `development`; generated verification paths remain ignored.

- [ ] **Step 6: Push and create the draft pull request**

```powershell
git push -u origin codex/ci-actions-node24
gh pr create --draft --base development --head codex/ci-actions-node24 --title "ci: route dependency updates through development" --body-file <generated-temp-pr-body>
```

Expected: the remote branch exists and the pull request base is `development`.
