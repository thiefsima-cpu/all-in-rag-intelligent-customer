# Dependency management

Runtime and development dependencies are declared in `pyproject.toml`.
`[project.dependencies]` is the runtime direct dependency list. The
`[project.optional-dependencies].dev` group contains test and local engineering
tools such as `pytest`, `pip-tools`, `ruff`, `mypy`, and `pre-commit`.

`requirements.txt` and `requirements-dev.txt` are resolver-generated lock files
and must not be edited by hand. `requirements.in` and `requirements-dev.in` are
retired; do not recreate them.

After changing `pyproject.toml`, regenerate both locks with Python 3.11:

```powershell
.\scripts\compile_locks.ps1
```

The script runs `piptools compile` for the runtime lock and the `dev` extra.
Pass `-IndexUrl` only when a release process intentionally uses a different
package index.

When a security update must replace a version already retained in the lock
files, request only those resolver upgrades explicitly:

```powershell
.\scripts\compile_locks.ps1 -UpgradePackage "package-a==1.2.3","package-b==4.5.6"
```

Direct dependencies must still be updated in `pyproject.toml` first. Avoid a
repository-wide resolver upgrade when a targeted security update is sufficient.

Create an isolated Miniconda-backed development environment:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

The script creates or reuses the global conda environment `graphrag-c9-dev`,
installs `requirements-dev.txt`, installs the current repository in editable
mode without resolving dependencies again, rejects the base/global interpreter,
checks that the runtime lock contains no development-only tools declared by
`pyproject.toml`, and runs `pip check`.

Activate the development environment before running local commands:

```powershell
conda activate graphrag-c9-dev
```

Install the repository Git hook once from the activated development
environment:

```powershell
python -m pre_commit install
```

The hook uses the local development environment and runs the same pinned tools
declared by this project: Ruff check with fixes, Ruff format, and mypy with
`pyproject.toml`.

Create a production-parity runtime environment or isolate the legacy agent:

```powershell
.\scripts\bootstrap_env.ps1 -Profile runtime
.\scripts\bootstrap_env.ps1 -Profile agent
```

These profiles use the global conda environments `graphrag-c9-runtime` and
`graphrag-c9-agent` respectively. Do not install the legacy agent requirements
into the main environment.

Override the default environment name when needed:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev -CondaEnvName my-graphrag-dev
```

Verify an existing development environment:

```powershell
conda run --name graphrag-c9-dev python scripts\verify_environment.py --expected-conda-env graphrag-c9-dev
```

Dependency updates must change `pyproject.toml`, run
`.\scripts\compile_locks.ps1`, bootstrap a clean conda environment, and run the
complete test suite. Direct global `pip install` commands outside the selected
conda environment are not a supported project setup.

## Lifecycle warning controls

The dependency lifecycle warnings that were accepted during short-term
development are now handled by dependency replacement instead of broad warning
filters:

- `jieba-py==0.46.12` replaces `jieba==0.42.1`. It is the maintained Python
  3.10+ distribution, keeps the existing `jieba` import and API, and no longer
  imports the deprecated `pkg_resources` module. The main bootstrap profiles
  remove the obsolete `jieba` distribution before installing the new lock so a
  reused environment cannot retain both packages.
- `fastapi.testclient` uses Starlette's new `httpx2` path in the development
  environment. Keep `httpx2` in the `dev` extra and `requirements-dev.txt`; keep
  it out of the runtime lock unless production code starts importing it.

Do not add broad warning filters for these items. If either warning returns,
fix the dependency declaration or lock file and rerun the API test suite.
