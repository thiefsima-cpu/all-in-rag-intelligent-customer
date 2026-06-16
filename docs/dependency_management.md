# Dependency management

Runtime and development dependencies are declared in `requirements.in` and
`requirements-dev.in`. The corresponding `requirements.txt` files are
resolver-generated lock files and must not be edited by hand.

Regenerate the locks with Python 3.11:

```powershell
python -m piptools compile requirements.in --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
python -m piptools compile requirements-dev.in --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
```

Create an isolated development environment:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

The script creates `.venv`, installs `requirements-dev.txt`, rejects a global
interpreter, checks that the runtime lock contains no development-only tools,
and runs `pip check`.

Create a production-parity runtime environment or isolate the legacy agent:

```powershell
.\scripts\bootstrap_env.ps1 -Profile runtime
.\scripts\bootstrap_env.ps1 -Profile agent
```

These profiles use `.venv-runtime` and `.venv-agent` respectively. Do not
install the legacy agent requirements into the main environment.

Verify an existing development environment:

```powershell
.\.venv\Scripts\python scripts\verify_environment.py
```

Dependency updates must change the relevant `.in` file, regenerate both locks,
bootstrap a clean environment, and run the complete test suite. Direct global
`pip install` commands are not a supported project setup.

## Known lifecycle tasks

The current test suite has two third-party deprecation warnings that are
accepted for short-term development, but must be tracked during dependency
upgrade cycles:

- `jieba==0.42.1` imports `pkg_resources`, which setuptools has deprecated and
  scheduled for removal. Evaluate a maintained jieba release, an alternative
  tokenizer, or a temporary setuptools compatibility pin before raising
  setuptools beyond the current lock.
- `fastapi.testclient` emits Starlette's `httpx2` migration warning. Upgrade
  FastAPI, Starlette, and `httpx` together, then rerun the API test suite before
  removing the warning from the accepted list.

Do not add broad warning filters for these items unless the warning noise starts
to hide new project warnings. The preferred resolution is an intentional
dependency upgrade with regenerated locks and full test verification.
