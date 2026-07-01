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

## Architecture

Start with [docs/architecture.md](docs/architecture.md) for the runtime
assembly, query-to-answer flow, and build workflow state machine diagrams.

## Common Commands

```powershell
python -m pytest -q
python -m pre_commit run --all-files
python scripts/release_gate.py
python scripts/pressure_api_service.py --json
```

The release-gate command now runs the deterministic offline smoke suites and
the curated offline quality evaluation required for release. It does not need
local Milvus, Neo4j, or model-provider services. The quality report covers
retrieval quality, generated-answer grounding, citation accuracy, fallback
rate, degraded retrieval sources, latency, and estimated cost.

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
clear error instead of surfacing as the first `/v1/answers` request.

With the default `AUTO_BOOTSTRAP=true`, the same Compose command also runs a
one-shot bootstrap service. On fresh state it imports the CSV graph and builds
the knowledge-base artifacts; on later starts it skips graph import when recipe
data already exists and lets the build workflow reuse valid artifacts. The
serving API starts only after bootstrap succeeds and initializes its retrieval
runtime automatically.

Check startup progress with:

```powershell
docker compose logs bootstrap
```

Set `FORCE_REBUILD=true` in `.env` to submit `/jobs/rebuild` during the next
bootstrap. Set `AUTO_BOOTSTRAP=false` for production-style deployments where
graph import and build jobs are managed separately. The build API remains
available for explicit operations:

```powershell
$job = Invoke-RestMethod -Method Post http://localhost:8001/v1/jobs/build
Invoke-RestMethod http://localhost:8001/v1/jobs/$($job.job.job_id)
```

### Build job retries and history

Build API submit routes accept `Idempotency-Key` on `/v1/jobs/build` and
`/v1/jobs/rebuild`. Reusing the same key for the same operation returns the
original job. Reusing a key for a different operation returns
`409 BUILD_JOB_CONFLICT`.

`GET /v1/jobs` returns a bounded page:

```powershell
curl.exe -H "Authorization: Bearer $env:API_ACCESS_TOKEN" `
  "http://localhost:8001/v1/jobs?limit=50"
```

Follow `next_cursor` until it is empty. Build job history is retained according
to `API_BUILD_JOB_RETENTION_LIMIT`; active jobs are never pruned. If local job
storage contains a corrupted record, `/v1/diagnostics` reports safe
`build_job_store.warning_count` and stable warning codes without exposing raw
file contents.

`/v1/answers` returns `409 Conflict` until the build API has produced a ready
artifact manifest, cached documents, and a Milvus vector collection.

### Error contract and request correlation

All HTTP failures use `{"ok": false, "error": {"code": "...", "message": "..."},
"request_id": "..."}`. Error codes are stable. Messages are safe for display and never contain raw
exceptions. Validation details include field paths and reasons only, never the rejected input.

Clients may provide `X-Request-ID` using 1–128 ASCII letters, digits, `.`, `_`, `:`, or `-`. When
the header is missing or invalid, the service generates a replacement. The resolved ID appears in
the `X-Request-ID` header of every response and in every error body. SSE error events use the same
payload.

Application logs exclude raw questions, query tokens, prompts, credentials, and exception
messages. Correlate support activity by `request_id` and stable error code.

Failed build-job resources contain a typed `error` object with a stable code, a catalog-controlled
message, and the submission request ID.

### Versioned API and debug traces

Use `/v1` for new API clients. Unversioned serving and build routes are retired;
callers should use the matching `/v1` path instead.

Public answer routes (`/v1/answers` and `/v1/answers/stream`) expose a
field-level public contract:

- `summary`: final answer, status, strategy, latency, evidence count, fallback,
  token, and cost summary fields.
- `grounding.evidence_documents`: public citation fields only: `content`,
  `recipe_name`, `score`, `source`, `evidence_type`, and `matched_terms`.
- `diagnostics`: stable health/degradation fields such as `overall_bucket`,
  `retrieval_degraded`, `degraded_sources`, and safe degraded-candidate codes.

Public responses do not expose route resolution, answer context, retrieval
outcome, query plans, semantic profiles, graph evidence maps, evidence units,
metadata bags, or trace snapshots. Full runtime details are available only
through explicit debug routes:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/v1/debug/answers -Body (@{question="..."} | ConvertTo-Json) -ContentType application/json
```

