# Retrieval Candidate Source Resilience Design

## Goal

Strengthen hybrid retrieval tolerance so one candidate source cannot break the
whole candidate generation pass. Each candidate source will fail and recover
independently, degraded behavior will be visible in trace details, and
fallback retrieval paths will not immediately call a source that already
failed in the same query workflow.

## Scope

This design covers the hybrid candidate generation layer:

- Candidate source execution in `RetrievalCandidateGenerator`.
- Independent in-process circuit breakers per candidate source.
- Degraded candidate metadata that can be logged and attached to route stage
  details.
- Same-query skip propagation so fallback and supplement requests avoid known
  failed sources.

It does not change graph retrieval internals, RRF ranking, parent document
enrichment, query planning, generation behavior, or external provider clients.

## Architecture

`RetrievalCandidateGenerator` becomes the single control point for candidate
source resilience. It owns a small source-state registry keyed by
`CandidateSourceSpec.name`. Each source state contains one `CircuitBreaker`.

For each `generate(request)` call, the generator:

- Applies the existing request calibration rules.
- Reads skip-source metadata from the request.
- Skips any source listed in the request metadata.
- Uses the source's circuit breaker before calling `source.retrieve(...)`.
- Records an empty result plus degraded detail when a source fails or is skipped
  because its circuit is open.
- Continues executing the remaining candidate sources.

The default source implementations remain thin adapters over their
runtime dependencies. Vector-specific exception swallowing will be removed so
all source failures follow the same generator-level policy.

## Data Flow

Initial hybrid retrieval:

1. `HybridSearchService` prepares a `RetrievalRequest`.
2. `RetrievalCandidateGenerator.generate(...)` executes candidate sources under
   independent circuit breakers.
3. Failed, open, or skipped sources produce degraded details and empty document
   lists.
4. Successful source results continue into RRF merge as they do today.
5. `HybridSearchService` stores the latest candidate diagnostics for the route
   stage and logs source counts plus degraded source names.

Fallback or supplement retrieval in the same query workflow:

1. Route execution sees degraded source details from the first hybrid stage.
2. It builds fallback or supplement `RetrievalRequest` metadata containing
   `skip_candidate_sources`.
3. The next hybrid retrieval call skips those sources before touching their
   adapters.
4. Other healthy candidate sources can still contribute evidence.

## Components

### Candidate Source State

Add a focused internal state helper to `candidate_generator.py`:

- Holds a `CircuitBreaker`.
- Exposes snapshots needed for degraded details.
- Is keyed by source name, not by rank name or search method.

Default breaker settings are conservative and deterministic in tests:

- `failure_threshold=1` for candidate-source adapter failures.
- `recovery_timeout_seconds=30.0`.

The threshold can remain constructor-configurable for tests and future tuning.

### Degraded Candidate Details

Add a serializable detail object or dict shape with:

- `source`: candidate source spec name.
- `rank_name`: source rank list name.
- `reason`: one of `exception`, `circuit_open`, or `request_skip`.
- `error_type`: exception class name when available.
- `message`: short exception message when available.
- `circuit_state`: breaker state after the decision.
- `failure_count`: breaker failure count after the decision.

`CandidateSet` exposes:

- `degraded_sources`: list of source names.
- `degraded_details`: list of serializable details.
- `to_stage_details()`: candidate counts plus degraded details for route trace
  stages.

### Request Skip Metadata

Use existing `RetrievalRequest.metadata` to carry skip decisions. The metadata
key is `skip_candidate_sources`, and its value is a list of candidate source
names.

Generator behavior:

- Request-skipped sources are not passed through the circuit breaker and do not
  call their adapter.
- Request-skipped sources are included in degraded details with reason
  `request_skip`.

Route behavior:

- Hybrid stages expose candidate diagnostics through route stage details.
- Graph fallback and supplement paths reuse degraded source names from earlier
  route stages when building follow-up hybrid requests.
- Exception fallback also uses known degraded source names when available.

## Error Handling

- Candidate source exceptions never leave `RetrievalCandidateGenerator`.
- A failed source records breaker failure and produces a degraded detail.
- A source with an open circuit produces a degraded detail without calling its
  adapter.
- Healthy sources continue normally.
- If every source is degraded or empty, existing empty-result diagnostics still
  apply through route trace failure reasons.

## Trace And Observability

Route stage details include:

- `candidate_counts`: per-source document counts.
- `degraded_sources`: list of degraded candidate source names.
- `degraded_candidates`: detailed degraded records.

The query trace already carries route stage details through
`RouteSnapshot.to_dict()`, so no new top-level trace model is required.

Logs remain concise:

- Candidate generation logs counts and degraded source names.
- Source failures log warning-level messages with the source name and exception.

## Testing

Add focused tests:

- A failing source returns an empty result, records degraded detail, and does not
  prevent later sources from running.
- Circuit state is independent per source: one failed source opens its circuit
  while another source continues to run.
- A second generate call while a source circuit is open does not call that
  source and records `circuit_open`.
- `skip_candidate_sources` metadata prevents the skipped source from being
  called and records `request_skip`.
- `CandidateSet.to_stage_details()` returns counts and degraded details.
- `HybridSearchService` captures candidate diagnostics for route stage details.
- Route fallback or supplement requests pass degraded source names through
  `skip_candidate_sources`.

## Acceptance Criteria

- One candidate source failure no longer fails the full hybrid retrieval pass.
- Each candidate source has independent circuit state.
- Degraded candidate source decisions are visible in route trace details.
- Same-query fallback and supplement retrieval do not call a source that already
  failed earlier in that workflow.
- Existing hybrid retrieval behavior remains unchanged when all sources are
  healthy.
