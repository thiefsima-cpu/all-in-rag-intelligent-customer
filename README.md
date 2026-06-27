# GraphRAG C9

This repository keeps the serving API, build API, offline gate, and local
pressure tooling in one place.

## Setup

Install Miniconda or Anaconda, make sure `conda` is available in PowerShell,
then use the repository bootstrap script on Windows:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

The script creates or reuses the global conda environment `graphrag-c9-dev`.
Activate it before running local engineering commands:

```powershell
conda activate graphrag-c9-dev
```

Install the repository Git hook once from the activated development
environment:

```powershell
python -m pre_commit install
```

Copy the committed environment template to your private local `.env` file before
running services:

```powershell
Copy-Item .env.example .env
```

Keep real API keys, tokens, and customer-specific values in `.env`. The
committed `.env.example` file is documentation for required variables and should
only contain placeholders or safe defaults.

`pyproject.toml` is the dependency source of truth. Runtime direct dependencies
live in `[project.dependencies]`; development tools live in the `dev` optional
dependency group. `requirements.txt` and `requirements-dev.txt` are generated
lock files consumed by Docker and the bootstrap script.

Regenerate locks with Python 3.11:

```powershell
python -m piptools compile pyproject.toml --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
python -m piptools compile pyproject.toml --extra dev --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
```

## Engineering Entry

Install the repo in editable mode and use the console commands from
`pyproject.toml`:

```powershell
graph-rag-api
graph-rag-build-api
graph-rag-release-gate
graph-rag-pressure
graph-rag-verify-env
```

## Common Commands

```powershell
python -m pytest -q
python -m pre_commit run --all-files
python scripts/release_gate.py
python scripts/pressure_api_service.py --json
```

The default release-gate command runs only the fast deterministic offline
smoke gate. To include quality, generation, latency, and cost thresholds in
the same gate, explicitly run:

```powershell
python scripts/release_gate.py --include-quality-eval
```

Alternatively, set `RELEASE_GATE_INCLUDE_QUALITY_EVAL=true` before running the
default command.

## Docker

The root `docker-compose.yml` now keeps infrastructure and the API surface
separate. Start the API profile with:

```powershell
docker compose --profile api up --build
```

The API profile starts both app surfaces:

- serving API: <http://localhost:8000/docs>
- build API: <http://localhost:8001/docs>

The API containers are built from `Dockerfile.api` and join the Milvus and Neo4j
services declared in the same compose file. Define `DASHSCOPE_API_KEY` in the
project `.env` file before starting the API profile; Compose forwards that
value into the API containers. `OPENAI_API_KEY` and `MOONSHOT_API_KEY` are also
forwarded as fallback provider keys. The serving API validates this lightweight
model-provider requirement during startup so a missing key fails fast with a
clear error instead of surfacing as the first `/answers` request.

On a fresh `storage/` and `volumes/` state, load the graph and build artifacts
before sending `/answers` requests:

```powershell
python scripts/import_neo4j.py

$job = Invoke-RestMethod -Method Post http://localhost:8001/jobs/build
$job.job.job_id

Invoke-RestMethod http://localhost:8001/jobs/$($job.job.job_id)
Invoke-RestMethod -Method Post http://localhost:8000/runtime/serving/refresh
Invoke-RestMethod http://localhost:8000/health/ready
```

`/answers` returns `409 Conflict` until the build API has produced a ready
artifact manifest, cached documents, and a Milvus vector collection.

