# GraphRAG C9

This repository keeps the serving API, build API, offline gate, and local
pressure tooling in one place.

## Setup

Use the repository bootstrap script on Windows:

```powershell
.\scripts\bootstrap_env.ps1 -Profile dev
```

The dependency workflow stays split between:

- `requirements.in` and `requirements.txt`
- `requirements-dev.in` and `requirements-dev.txt`
- `scripts/verify_environment.py`

Regenerate locks with Python 3.11:

```powershell
python -m piptools compile requirements.in --output-file requirements.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
python -m piptools compile requirements-dev.in --output-file requirements-dev.txt --strip-extras --allow-unsafe --pip-args="--index-url https://pypi.org/simple"
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
pre-commit run --all-files
python scripts/release_gate.py
python scripts/pressure_api_service.py --json
```

## Docker

The root `docker-compose.yml` now keeps infrastructure and the API surface
separate. Start the API profile with:

```powershell
docker compose --profile api up --build
```

The API container is built from `Dockerfile.api` and joins the Milvus and Neo4j
services declared in the same compose file.

