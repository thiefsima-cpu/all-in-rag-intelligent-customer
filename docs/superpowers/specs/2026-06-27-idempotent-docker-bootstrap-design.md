# Idempotent Docker Bootstrap Design

## Goal

Make `docker compose --profile api up --build` start a locally usable GraphRAG stack while
preserving separate serving and build API ownership.

## Selected Approach

Add a one-shot `bootstrap` Compose service between infrastructure/build API startup and serving
API startup. The service imports the CSV graph only when Neo4j has no recipe data, then submits a
normal build job through the build API and waits for it to finish. The existing build workflow
decides whether artifacts can be reused or must be rebuilt.

## Runtime Flow

1. Compose starts Neo4j, Milvus, and their dependencies.
2. Health checks prove Neo4j, Milvus, and the build API are reachable.
3. The one-shot bootstrap service exits successfully without side effects when
   `AUTO_BOOTSTRAP=false`.
4. Otherwise it imports `cypher/nodes.csv` and `cypher/relationships.csv` only when Neo4j has no
   `Recipe` nodes.
5. It submits `/jobs/build`, or `/jobs/rebuild` when `FORCE_REBUILD=true`, and polls the returned
   job until it succeeds or fails.
6. Compose starts the serving API only after bootstrap succeeds. The serving API initializes its
   retrieval runtime during startup so `/health/ready` reflects the built artifacts immediately.

## Failure Handling

- Infrastructure health-check failure prevents bootstrap from starting.
- Build API unavailability, malformed responses, timeout, or a failed build job makes bootstrap
  exit nonzero.
- A nonzero bootstrap exit prevents the serving API from starting in the local API profile.
- Existing graph data is never automatically deleted or reimported.

## Configuration

- `AUTO_BOOTSTRAP=true` enables local one-command initialization.
- `FORCE_REBUILD=false` uses the reusable build path by default.
- `BOOTSTRAP_BUILD_TIMEOUT_SECONDS` bounds build-job polling.
- Production deployments can set `AUTO_BOOTSTRAP=false` and run build jobs separately.

## Testing

- Unit tests cover graph import skip/import decisions and bootstrap build-job success, failure,
  conflict, timeout, disabled, and forced-rebuild paths.
- Compose tests cover health checks, bootstrap dependencies, environment switches, shared
  storage, and serving startup ordering.
- Existing API contract tests remain unchanged.

