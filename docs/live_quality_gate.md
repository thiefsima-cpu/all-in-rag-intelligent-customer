# Live Quality Gate

The live quality gate is the third quality layer for GraphRAG C9.

- `graph-rag-release-gate`: deterministic contract regression.
- `graph-rag-integration-gate`: live dependency participation.
- `graph-rag-live-quality-gate`: live AI quality proof.

The gate calls the real serving API, evaluates real ranked evidence and generated
answers, and uses an independent LLM judge. It is explicitly invoked and is not
part of default pytest, pre-commit, `scripts/local_gate.py`, or the offline
release gate.

## Prerequisites

- The serving API is running and `/v1/debug/answers/stream` is available.
- Neo4j and Milvus contain graph and vector data built for the selected `DomainPack`.
- The serving API has its normal model-provider credentials.
- The judge model has separate credentials from the serving API.
- The business-owned golden policy has been reviewed for the target release.

The gate does not start or stop infrastructure, rebuild data, or mutate graph
and vector stores. Operators and CI jobs own the lifecycle of the target
environment.

## Environment

The live quality gate process reads:

- `LIVE_QUALITY_API_URL`
- optional `LIVE_QUALITY_API_TOKEN`
- `LIVE_QUALITY_JUDGE_API_URL`
- `LIVE_QUALITY_JUDGE_API_KEY`
- `LIVE_QUALITY_JUDGE_MODEL`
- optional `LIVE_QUALITY_JUDGE_TIMEOUT_SECONDS`
- optional `LIVE_QUALITY_JUDGE_ENABLE_THINKING` (`true` or `false`)

Do not put provider keys, API tokens, customer data, raw prompts, or raw
responses in `eval/live_quality_gate.json`.

## Run

Run the installed console command after the target environment is ready:

```powershell
graph-rag-live-quality-gate
```

Emit the safe JSON report to standard output for CI processing:

```powershell
graph-rag-live-quality-gate --json
```

Run the module directly with an explicit policy when diagnosing locally:

```powershell
python -m scripts.live_quality_gate --policy eval/live_quality_gate.json
```

`--deterministic-only` is for diagnostics with a policy that does not require a
judge. A release-quality run must keep the judge enabled.

## Release Evidence

The `Release Quality Evidence` workflow turns a successful integration run and
live-quality run into machine-traceable release evidence. Its capture job must
run at the exact `evaluated_commit`: dispatch the workflow from that same commit
and pass the identical full commit SHA. A later code, profile, policy, prompt,
dependency, or corpus change requires a new capture.

Capture is restricted to a prepared **self-hosted Linux** runner that can reach
the target environment. Configure the repository/environment variable with an
absolute mounted path, for example:

```dotenv
RELEASE_EVIDENCE_ARTIFACT_MANIFEST_PATH=/srv/graph-rag/release-evidence/artifact_manifest.json
```

The path must resolve outside `GITHUB_WORKSPACE`. It must name the manifest for
the exact active ready knowledge base used by the serving API during the gates;
do not point it at a repository fixture, a stale build, or a manifest for an
inactive index. Hosted capture is rejected until a trusted
preparation-artifact handoff is implemented. Verify mode may run on a hosted
runner because it checks committed provenance and the selected immutable
Actions artifact without accessing the prepared live environment.

The workflow runs the real-dependency integration gate and live quality gate,
then invokes the release-evidence CLI. The supported command surfaces can be
inspected without reproducing the workflow's arguments manually:

```powershell
graph-rag-release-evidence capture --help
graph-rag-release-evidence finalize --help
graph-rag-release-evidence verify --help
```

Capture fails closed unless both source reports are successful, non-empty, and
consistent with their policies. In particular, `case_count=0` cannot create a
success manifest. The capture job uploads the complete deterministic quality
evidence ZIP, finalizes its Actions artifact identity into a compact
`evidence-manifest.json`, and uploads that compact manifest for the release pull
request. Only the compact manifest is committed at
`quality-evidence/releases/<package-version>/evidence-manifest.json`; the
complete ZIP remains an Actions artifact and later becomes a GitHub Release
asset.

Before tagging, commit the finalized compact manifest and run the workflow in
`verify` mode with the manifest commit as `release_commit`, the original
`evaluated_commit`, package version, and planned tag. Verification downloads the
recorded artifact and validates Git provenance, release identity, artifact
metadata, ZIP digest and members, profile, policies, dataset, knowledge-base
summary, and gate semantics. A green pre-tag verification is required; a
historical narrative or a standalone report is not a substitute.

## Exit Codes and Reports

- Exit `0`: live quality gate evaluated, all aggregate/slice thresholds passed,
  and no dependency, request, or judge-protocol check blocked release.
- Exit `1`: the gate ran successfully and reported one or more failed checks.
- Exit `2`: policy, environment configuration, or gate execution was invalid.

Reports are written to:

- `eval/reports/live_quality_gate/report.json`
- `eval/reports/live_quality_gate/summary.md`
- `eval/reports/live_quality_gate/manual_review_sample.jsonl`

Reports contain safe host identities, stable check codes, aggregate metrics,
case summaries, and manual review samples. They do not contain API tokens,
judge keys, authorization headers, raw exceptions, or credential-bearing URLs.

## Metrics

The gate reports deterministic metrics and judge metrics side by side:

- Recall@K, MRR, and nDCG@K from real ranked evidence;
- response-mode accuracy through deterministic case checks;
- fallback and retrieval-degradation rates;
- judge scores such as faithfulness, answer relevance, safety, and
  completeness;
- latency, token usage, and estimated cost;
- slice metrics by query type, cuisine, constraint type, risk tag, response
  mode, and strategy.

## Interaction SLOs and schema v2

The canonical `eval/live_quality_gate.json` policy is schema version 2 and the
gate report is schema version 2. The baseline is exactly 52 cases, including
exactly five `customer_service` cases whose expected response mode is
`grounded_answer`. Every case is evaluated with one debug SSE request to
`/v1/debug/answers/stream`; the gate does not make a second non-streaming
request to measure interaction latency.

TTFT is the client-observed elapsed time from starting that request to the
first non-empty `chunk` event. Full-response latency is the client-observed
elapsed time to the SSE `result` event, not to connection close. The response
must then finish with `done`, and the concatenated chunks must match the result
answer. The gate obtains retrieval latency from
`response.traces.route_trace.total_latency_ms` and generation latency from
`response.traces.generation_trace.total_latency_ms`. Rerank latency applies
only to cases where `post_process.rerank_attempted` is true.

The default policy has these release-blocking interaction thresholds:

- at least 1 rerank observation;
- p95 TTFT at most 5,000 ms;
- p95 retrieval latency at most 3,000 ms;
- applicable-only p95 rerank latency at most 2,000 ms;
- p95 generation latency at most 20,000 ms; and
- p95 full-response latency at most 25,000 ms.

Missing rerank coverage is a `coverage-regression`; any of the five latency
budget violations is a `budget-regression`. Existing quality thresholds remain
`quality-regression` failures. Invalid SSE or required trace data is a
dependency/request failure, and invalid policy or report contracts remain
configuration or gate errors; those failures block a release rather than being
treated as a quality-rate miss.

`generation_trace.first_token_latency_ms` and its aggregate p95 remain
internal diagnostics. They are reported to help isolate model behavior, but
they are neither the client-observed TTFT metric nor a release-blocking
threshold, and are not projected into the compact release-evidence metrics.

Source requirements use route-stage identifiers. Combined cases require
`traditional` plus `graph_rag`; low-level vector participation is evaluated by
dedicated traditional/vector cases. A `hybrid_supplement` stage after valid
graph evidence is normal augmentation and does not increase the fallback rate.

The default policy enforces coverage for prompt injection, knowledge
pollution, no-evidence inducement, cross-language, typo, long-query,
constraint-heavy, real customer-service long-tail, temporal, conflicting
knowledge, ultra-long-context, and repeated regression-anchor scenarios. The
customer-service slice includes grounded order, refund, warranty, invoice, and policy-version
answers in addition to safe abstention controls and historical compatibility cases. The gate also keeps LLM judge scores and deterministic checks separate so
operators can see whether a failure is retrieval, generation, judge
availability, coverage, or budget related.

Valid per-case deterministic and judge quality misses remain visible in the
report and contribute to case, judge, and slice pass rates. They do not bypass
the policy by failing release individually; the configured aggregate and slice
thresholds make the release decision. Invalid judge responses, judge transport
failures, serving request failures, missing coverage, fallback/degradation
budget failures, and other non-quality execution failures remain immediately
release-blocking.

## Manual Review

Every policy case declares a business owner and whether it belongs in the manual
review sample. The JSONL sample is intentionally small and review-oriented: it
contains case IDs, slice labels, expected response mode, answer preview, evidence
snippets, judge scores, and failure codes.

Human review remains part of release judgment. The LLM judge is an independent
signal, not the sole authority for business correctness.
