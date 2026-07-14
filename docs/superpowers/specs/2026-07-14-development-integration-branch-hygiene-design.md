# Development Integration Branch Hygiene and Dependency Upgrade Design

Status: approved

Date: 2026-07-14

## Goal

Restore `development` as the single feature-integration branch by retiring branches whose useful
changes are already integrated, preventing Dependabot from targeting `main`, and rebuilding the
remaining dependency upgrades as small reviewable branches from the current `development` tip.

The work must not merge stale branch ancestry, generated cache files, or lock-only dependency
changes that bypass `pyproject.toml` and the repository lock-generation workflow.

## Current State

At the start of this work, local and remote `development` both resolve to commit `1ddc4ac8` and
have no ahead/behind difference. `development` contains the current `main` and `production` tips,
so it remains the correct base for new integration work.

Three manually maintained branches are no longer merge candidates:

| Branch | Evidence | Disposition |
| --- | --- | --- |
| `codex/performance-application-layer-purification` | Its useful application-layer commits are already patch-equivalent in `development`; the only unique tip adds generated pre-commit cache data. | Delete the local and remote branch without merging. |
| `codex/risk-weighted-branch-coverage` | PR #20 already merged the feature into `development`; the remaining remote tip only merges a later `development` snapshot back into the old branch. | Delete the remote branch without merging. |
| `codex/root-helper-ownership` | The branch is based on old history and would replace a large current tree; its intended helper moves already exist in canonical owner modules on `development`. | Delete the local branch without merging. |

All nine open Dependabot PRs target `main` because `.github/dependabot.yml` omits an explicit
target branch. They must not be merged in their current form. Several patches conflict with the
current integration tree, and some edit generated lock files without changing the dependency
source of truth.

## Branch and Pull Request Policy

All new work starts from the latest `development` commit and uses a `codex/` branch. Every new
pull request targets `development`. No task branch may be based on an obsolete Dependabot branch
or on one of the three retired manual branches.

The implementation is split into three pull requests because the changes have independent risk
and rollback boundaries:

1. `codex/ci-actions-node24`
   - set `target-branch: "development"` for both Dependabot ecosystems;
   - upgrade `actions/checkout` from v4 to v7;
   - upgrade `actions/setup-python` from v5 to v6;
   - upgrade `actions/upload-artifact` from v4 to v7;
   - upgrade `gitleaks/gitleaks-action` from v2 to v3;
   - update focused governance tests so the integration target and action majors are enforced.
2. `codex/fastapi-0-139`
   - upgrade the FastAPI source declaration from `0.136.3` to `0.139.0`;
   - regenerate both lock files with the repository script under Python 3.11;
   - accept the compatible AnyIO resolution produced by lock compilation instead of merging the
     lock-only Dependabot PR.
3. `codex/opentelemetry-1-43`
   - upgrade the OpenTelemetry OTLP HTTP exporter from `1.42.1` to `1.43.0`;
   - regenerate both lock files so `opentelemetry-proto` and related packages resolve together;
   - do not merge the exporter and proto Dependabot PRs independently.

Each pull request must be published only after its focused checks and the repository's
release-sensitive validation pass. A failure remains attached to the branch that caused it; the
three scopes must not be combined merely to reduce the number of pull requests.

## Independent Agent Boundary

Dependabot PR #8 changes only `agent/requirements.txt`, upgrading Neo4j from `5.28.1` to `6.2.0`.
The main package already uses Neo4j `6.2.0`, but `agent/` is intentionally independent and has its
own dependency conventions. This upgrade is deferred and excluded from all three integration
branches. It requires a later agent-specific compatibility review and validation run.

## Retiring Existing Branches and Pull Requests

Branch deletion happens only after the replacement integration branches have been pushed and the
corresponding pull requests exist. Before deletion, record the current ref and confirm the branch
is not checked out by another worktree. Delete only the named obsolete refs; do not prune unrelated
local or remote branches.

After replacement pull requests are available, close Dependabot PRs #2 through #10 as superseded
or deferred:

- PRs #2 through #7 and #9 through #10 are superseded by the three clean integration pull
  requests;
- PR #8 is deferred to a separate `agent/` dependency task and must not be presented as completed.

Closing the stale PRs does not delete `development`, `production`, `main`, any replacement branch,
or the independent `agent/` directory.

## Testing and Validation

Use test-first changes for the Dependabot policy and workflow-major assertions: add a focused
governance test that fails against the current configuration, then update the configuration and
workflows until it passes.

For each dependency branch, verify the source declaration first, regenerate locks rather than
editing them by hand, and run the narrowest relevant import/startup tests before broader checks.
Validation expands in this order:

1. focused governance or dependency/import tests;
2. Ruff check and format verification without a shared cache;
3. mypy with a writable branch-local cache;
4. the full pytest suite with a unique branch-local basetemp;
5. `python scripts/release_gate.py` with output outside tracked source paths;
6. `git diff --check`, lock/source consistency checks, and a clean final status review.

The GitHub-hosted workflows use `ubuntu-latest`, so the Node 24 action-major upgrades are
compatible with the runner family. A passing local YAML/text governance test is not sufficient by
itself: the resulting GitHub pull request checks remain part of the merge decision.

## Success Criteria

- Dependabot opens future `pip` and `github-actions` pull requests against `development`;
- the four GitHub Actions use the approved Node 24-compatible major versions;
- FastAPI and OpenTelemetry upgrades are rebuilt from current `development` with regenerated
  locks and pass release-sensitive validation;
- the independent `agent/` Neo4j upgrade remains explicitly deferred;
- the three obsolete manual branches are deleted without merging stale ancestry or cache data;
- Dependabot PRs #2 through #10 are closed only after their replacement or deferral is recorded;
- `development`, `production`, and `main` are never force-pushed or rewritten;
- final reporting identifies every new pull request, every deleted ref, every closed stale pull
  request, and any validation or GitHub check that remains outstanding.
