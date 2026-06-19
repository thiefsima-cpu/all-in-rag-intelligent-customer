# Dependency management

Runtime and development dependencies are declared in `pyproject.toml`.
`[project.dependencies]` is the runtime direct dependency list. The
`[project.optional-dependencies].dev` group contains test and local engineering
tools such as `pytest`, `pip-tools`, `ruff`, `mypy`, and `pre-commit`.

`requirements.txt` and `requirements-dev.txt` are resolver-generated lock files
and must not be edited by hand. `requirements.in` and `requirements-dev.in` are
retired; do not recreate them.

After changing `pyproject.toml`, regenerate the locks with Python 3.11:

```powershell
python -m piptools compile pyproject.toml --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
python -m piptools compile pyproject.toml --extra dev --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
```

Create an isolated Miniconda-backed development environment:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

The script creates or reuses the global conda environment `graphrag-c9-dev`,
installs `requirements-dev.txt`, rejects the base/global interpreter, checks
that the runtime lock contains no development-only tools declared by
`pyproject.toml`, and runs `pip check`.

Activate the development environment before running local commands:

```powershell
conda activate graphrag-c9-dev
```

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

Dependency updates must change `pyproject.toml`, regenerate both locks,
bootstrap a clean conda environment, and run the complete test suite. Direct
global `pip install` commands outside the selected conda environment are not a
supported project setup.

## Known lifecycle tasks

The current test suite has two third-party deprecation warnings that are
accepted for short-term development, but must be tracked during dependency
upgrade cycles:

- `jieba==0.42.1` imports `pkg_resources`, which setuptools has deprecated and
  scheduled for removal. Evaluate a maintained jieba release, an alternative
  tokenizer, or a temporary setuptools compatibility pin before raising the
  runtime lock or bootstrap `setuptools` pin.
- `fastapi.testclient` emits Starlette's `httpx2` migration warning. Upgrade
  FastAPI, Starlette, and `httpx` together, then rerun the API test suite before
  removing the warning from the accepted list.

Do not add broad warning filters for these items unless the warning noise starts
to hide new project warnings. The preferred resolution is an intentional
dependency upgrade with regenerated locks and full test verification.
