# Real-Dependency Integration Gate

The real-dependency integration gate is an explicitly invoked, end-to-end check
for a prepared environment. It probes Neo4j, Milvus, and the serving API, then
runs curated requests through the real model provider. It complements the
deterministic offline release gate; it does not replace it.

It is the live dependency participation layer. Use
`graph-rag-live-quality-gate` separately when the release question is live AI
quality proof: real retrieval, real generation, deterministic ranking metrics,
an independent LLM judge, manual review samples, and slice metrics.

## Prerequisites

Before running the gate:

- finish repository bootstrap and the build/bootstrap workflow;
- confirm that the serving API is ready and that `/v1/health/ready` and
  `/v1/diagnostics` are reachable;
- confirm that Neo4j and Milvus are reachable and contain graph and vector data built for the
  selected `DomainPack`;
- configure a provider key on the API service, such as `DASHSCOPE_API_KEY`,
  `OPENAI_API_KEY`, or `MOONSHOT_API_KEY`;
- configure non-zero, provider-accurate
  `LLM_INPUT_COST_PER_MILLION_TOKENS` and
  `LLM_OUTPUT_COST_PER_MILLION_TOKENS` values on the API service; otherwise
  estimated cost defaults to zero and the cost threshold has no operational
  meaning;
- explicitly set `INTEGRATION_GATE_API_URL`, and set
  `INTEGRATION_GATE_API_TOKEN` when the API requires bearer authentication;
- explicitly set `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
  `NEO4J_DATABASE`, `MILVUS_HOST`, `MILVUS_PORT`, and
  `MILVUS_COLLECTION_NAME` for the gate process;
- set `GRAPH_RAG_DOMAIN` to the policy domain. The gate rejects a policy/runtime mismatch and
  verifies that the serving API reports the same domain through `/v1/diagnostics`.

The provider key belongs to the API service. Do not pass a provider key to the
gate process or place credentials in `eval/integration_gate.json`.

For a local Compose environment, operators may prepare the stack separately:

```powershell
docker compose --profile api up --build
```

The gate does not start or stop infrastructure. It also does not build data,
rebuild artifacts, or mutate graph and vector stores. Operators and CI jobs own
the lifecycle of the target environment.

## Run

After the environment is ready, run the installed console command:

```powershell
graph-rag-integration-gate
```

Emit the safe JSON report to standard output for CI processing:

```powershell
graph-rag-integration-gate --json
```

Run the module directly with an explicit policy when diagnosing locally:

```powershell
python -m scripts.integration_gate --policy eval/integration_gate.json
```

The supported CLI options are `--policy`, `--output-dir`, and `--json`.
Runtime endpoints and credentials always come from environment variables.

## Exit Codes and Reports

- Exit `0`: all dependency probes, live cases, and aggregate thresholds passed.
- Exit `1`: the gate ran successfully and reported one or more failed or
  blocked checks.
- Exit `2`: policy, environment configuration, or gate execution was invalid.

On normal completion, the gate writes allowlisted, credential-safe artifacts
to these default paths:

- `eval/reports/integration_gate/report.json`
- `eval/reports/integration_gate/summary.md`

Exit `2` can occur before report artifacts are created. In that case the CLI
writes only a safe JSON error object to standard error.

Reports contain stable check codes, aggregate metrics, case IDs, and sanitized
host identities. They do not contain questions, prompts, raw responses, raw
exceptions, credentials, authorization headers, or credential-bearing URLs.

The policy declares a top-level `domain_name`. Every live case also declares
`expected_entity_ids` and `must_include_facts`. A case passes only when the required retrieval
sources participate, all expected entities appear in evidence, all required facts appear in the
generated answer after width/case/whitespace normalization, and real model usage is recorded.
Reports retain only safe counts and stable check codes, never the answer or evidence text.

`required_sources` uses the public route-stage vocabulary. A combined request
therefore proves participation with `traditional` and `graph_rag`; the
traditional branch may internally fuse vector, BM25, and graph-derived
candidates. A normal hybrid supplement after a non-empty graph result remains
visible as a `hybrid_supplement` stage but is not counted as a fallback. Only a
graph miss or execution/generation recovery contributes to the fallback rate.

## Failure Types

- `dependency-unavailable`: Neo4j, Milvus, the serving API, authentication, or
  required data is unavailable. Live cases are blocked, so no model calls are
  made after a failed dependency probe.
- `contract-regression`: the API response, route trace, evidence shape, or model
  participation contract changed unexpectedly.
- `quality-regression`: a case used fallback, retrieval degraded, required
  evidence was absent, or a live semantic contract failed.
- `budget-regression`: latency or estimated cost exceeded the policy threshold.
- `gate-error`: policy/configuration is invalid or the gate itself failed.

Use the stable code beside the failure type for diagnosis. The gate never
classifies failures by exposing or searching raw exception messages.

## Cost and CI Scheduling

Successful probes trigger live generation requests, so each run consumes model
tokens and can incur provider cost. The maximum estimated-cost threshold is a
post-execution gate evaluated after all live requests have run. It is not a
preauthorization or hard spending cap. It cannot prevent charges already incurred.
The policy also bounds latency, but neither threshold makes repeated invocations
free.

Run this gate in a dedicated integration or pre-deployment job against a known,
isolated environment. Serialize jobs that share the same dependency stack,
apply CI timeouts, restrict credentials to that job, and avoid running it on
every unit-test shard or untrusted pull request. Keep the deterministic
`graph-rag-release-gate` as the required offline release check, and run
`graph-rag-live-quality-gate` separately when a prepared environment must prove
live AI quality.
