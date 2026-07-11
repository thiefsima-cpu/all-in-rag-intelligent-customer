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

- The serving API is running and `/v1/debug/answers` is available.
- Neo4j and Milvus contain the prepared recipe graph and vector data.
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

Source requirements use route-stage identifiers. Combined cases require
`traditional` plus `graph_rag`; low-level vector participation is evaluated by
dedicated traditional/vector cases. A `hybrid_supplement` stage after valid
graph evidence is normal augmentation and does not increase the fallback rate.

The default policy enforces coverage for prompt injection, knowledge pollution,
no-evidence inducement, cross-language, typo, long-query, and constraint-heavy
scenarios. It also keeps LLM judge scores and deterministic checks separate so
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
