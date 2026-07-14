# Repository Hygiene and Facade Retirement Design

Status: approved

Date: 2026-07-14

## Goal

Make the repository root and internal package layout easier to understand by removing proven
generated state, stale packaging metadata, an obsolete linked worktree directory, and six thin
forwarding modules that do not own behavior.

The cleanup must preserve runtime behavior, formal public entrypoints, local developer state that
the user explicitly protected, and the repository's historical architecture record.

## Confirmed Scope

The cleanup uses a hard cutover. Removed internal import paths fail instead of being retained as
aliases, compatibility shims, or replacement forwarding modules.

The following content is protected and must not be deleted:

- `.env`
- `.venv/`
- `storage/`
- `volumes/`
- `agent/`
- `docs/superpowers/`
- the console, Docker, and Python entrypoints declared by `pyproject.toml`
- `main.py`, `main_build_service.py`, and `main_build_worker.py`
- canonical public exports declared by `rag_modules/public_surface_manifest.py`
- tracked fixtures, Cypher assets, release evidence, and profile configuration

The active `.worktrees/performance-hotspot-ratchet` directory is the single exception to the
protected-worktree rule: the user explicitly requested its removal. Its Git branch and committed
history must remain available.

## Cleanup Categories

### Workspace-generated state

Remove repository-local generated artifacts that can be recreated:

- `.pytest_baseline_p0_20260713/`
- `.pytest_p0_full_20260713/`
- `.pytest_p0_localgate_20260713/`
- `.pytest_cache/` and `.pytest_tmp/`
- `.mypy_cache/` and `.ruff_cache/`
- repository `__pycache__/` directories and `.pyc` files
- `.coverage`, `coverage.json`, `coverage.xml`, and other ignored coverage outputs
- `.superpowers/`, which contains generated SDD briefs, reports, patches, and review diffs rather
  than source-of-truth design documents
- `eval/reports/` and generated log files, without touching tracked evaluation configuration

Do not use a broad deletion command over the whole repository. Each deletion target must first be
resolved under the repository root and classified as generated state.

### Stale tracked packaging metadata

Delete the tracked `graph_rag_c9.egg-info/` directory. It is setuptools output, duplicates
information generated from `pyproject.toml`, and currently reports package version `0.3.0` while
the source of truth reports `0.4.0.dev0`.

Add repository ignore rules for `*.egg-info/`, root-level pytest basetemp directories, and the
workspace `.superpowers/` scratch directory so the same pollution does not recur. Existing
specific ignore rules may be consolidated only when the resulting rule is equally narrow.

### Linked worktree cleanup

Remove `.worktrees/performance-hotspot-ratchet` through `git worktree remove`, not raw recursive
filesystem deletion, so Git metadata and the directory stay consistent.

Before removal:

1. confirm the worktree status is clean;
2. record the branch name and tip commit;
3. confirm the branch reference exists outside the worktree.

After removal:

1. confirm the directory no longer exists;
2. confirm `refs/heads/codex/performance-hotspot-ratchet` still resolves to the recorded commit;
3. prune only stale worktree metadata;
4. do not delete, reset, or rewrite the branch.

## Thin Forwarding Module Retirement

Delete these modules after migrating every repository consumer to the owning implementation
module:

| Retired module | Canonical owner modules | Current repository use |
| --- | --- | --- |
| `rag_modules.graph.cache` | `cache_stats`, `cache_warmup` | one test import |
| `rag_modules.graph.evidence` | `evidence_builder`, `evidence_orchestrator`, `path_ranker` | none |
| `rag_modules.graph.query` | `query_executor`, `query_intent`, `query_resolution` | none |
| `rag_modules.graph.reasoning` | `reasoning_strategy` | none |
| `rag_modules.graph.retrieval` | `rag_retrieval`, `retrieval_components`, `retrieval_executor`, `retrieval_plan`, `retrieval_postprocess`, `retrieval_runtime` | two test imports |
| `rag_modules.interfaces.api.routes` | `build_routes`, `serving_routes` | API application assembly and one structure test |

These modules contain imports and `__all__` declarations only. They own no algorithms, state,
configuration, error handling, or data models.

`rag_modules/interfaces/api/app.py` must import `register_build_routes` and
`register_serving_routes` directly from their owner modules in the same change that deletes
`routes.py`. Deleting `routes.py` without this migration would break API startup.

The lazy public exports in `rag_modules.graph.__init__` already resolve graph symbols to their
owner modules. They must remain intact. This preserves supported imports such as
`from rag_modules.graph import GraphQueryExecutor` while intentionally retiring exact imports
through the six deleted submodules.

## Contract and Documentation Updates

Update focused tests to import graph collaborators from their owner modules. Replace the API
compatibility-facade assertion with a structural assertion that application assembly imports the
two route owner modules directly.

Extend the existing retired-facade boundary data so all six deleted module paths are prohibited
from being recreated or imported by repository code. Do not add replacement aliases.

Update `docs/public_surface_retirement_plan.md` to record the internal hard cutover and canonical
owner modules. Keep historical design and plan documents unchanged except for this new design and
its implementation plan.

Add a focused repository-hygiene assertion that tracked setuptools metadata is forbidden and the
required ignore rules exist. The assertion must inspect tracked paths or repository policy, not
depend on a developer's current ignored files.

## Behavior and Compatibility

No serving, build, retrieval, graph, generation, policy, configuration, or evaluation behavior
changes are intended.

Repository-internal consumers are migrated atomically. External callers that import one of the
six exact retired module paths receive `ModuleNotFoundError`; this is the approved hard-cutover
behavior. Formal console commands, Docker commands, root package exports, and canonical graph
package exports remain unchanged.

## Validation

Run validation from narrowest to broadest:

1. focused graph cache, graph retrieval, API route-structure, public-surface, packaging, and
   entrypoint tests;
2. the complete API test slice named in `AGENTS.md`;
3. Ruff check and format verification without relying on a shared cache;
4. mypy using the repository configuration and a writable local cache path;
5. the full pytest suite with a unique repository-local basetemp;
6. `python scripts/release_gate.py` with generated output kept outside tracked source paths;
7. `git diff --check`, an exact reference scan for the retired modules, and final tracked/ignored
   status classification.

If a Windows cache or pytest cleanup operation reports access denied, narrow the failing target
and retry only that verified generated path. Do not reinterpret an ACL failure as a product
regression.

## Success Criteria

- all six thin forwarding modules are absent;
- all repository consumers import canonical owner modules;
- no compatibility alias or forwarding replacement exists;
- `graph_rag_c9.egg-info/` is untracked and ignored when regenerated;
- generated root pollution is removed and prevented from recurring;
- `.worktrees/performance-hotspot-ratchet` is removed while its branch tip is preserved;
- every protected path remains present and unchanged by the cleanup;
- focused, full, and release-sensitive validation passes, or any environmental blocker is
  reported with its exact command and evidence.
