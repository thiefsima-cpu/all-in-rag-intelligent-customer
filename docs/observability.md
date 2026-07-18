# Observability

The serving runtime exposes Prometheus metrics at `GET /metrics` and creates
OpenTelemetry spans around answer, retrieval, and generation execution.

## Prometheus

Prometheus export is enabled by default:

```text
ENABLE_PROMETHEUS=true
```

That registers `GET /metrics`. The endpoint requires the configured API
credentials by default:

```text
PROMETHEUS_METRICS_PUBLIC=false
```

Set `ENABLE_PROMETHEUS=false` to leave `/metrics` unregistered. Set
`PROMETHEUS_METRICS_PUBLIC=true` only when ingress, network policy, or a
service mesh already restricts scraper access to trusted infrastructure.

Key metrics:

- `graphrag_queries_total`
- `graphrag_query_latency_seconds`
- `graphrag_retrieved_documents`
- `graphrag_generation_provider_latency_seconds`
- `graphrag_generation_first_token_latency_seconds`
- `graphrag_generation_tokens_total`
- `graphrag_generation_cost_usd_total`
- `graphrag_admission_wait_seconds`
- `graphrag_admission_rejected_total`
- `graphrag_sse_executor_active`
- `graphrag_sse_executor_queued`
- `graphrag_sse_executor_rejected_total`
- `graphrag_sse_queue_wait_seconds`
- `graphrag_retrieval_degradation_total`
- `graphrag_circuit_breaker_state`
- `graphrag_cache_access_total`
- `graphrag_hot_refresh_total`
- `graphrag_readiness_state`
- `graphrag_readiness_transitions_total`
- `graphrag_build_leases_active`
- `graphrag_build_lease_events_total`

The SSE executor gauges report currently running tasks and accepted tasks that
have not started. The rejection counter increments when
`stream_executor_max_outstanding` is full and a stream is immediately returned
as `RATE_LIMITED`; it does not include answer-admission rejection after a task
has started.

Operational labels are deliberately bounded: admission outcomes, cache results,
hot-refresh outcomes, readiness states, circuit states, build backends/events,
and internal degradation reasons. Request IDs, queries, job IDs, paths, and raw
exception text must never become metric labels. The first-token histogram is
populated only for streamed model output; non-streaming provider latency remains
in `graphrag_generation_provider_latency_seconds`.

## OpenTelemetry

OTLP export is opt-in:

```text
ENABLE_OPENTELEMETRY=true
OTEL_SERVICE_NAME=graphrag
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_TRACE_SAMPLE_RATIO=1.0
```

The configured endpoint is treated as the OTLP HTTP base endpoint; the runtime
appends `/v1/traces` when needed.

## Token Cost

Set the active model price in USD per one million tokens:

```text
LLM_INPUT_COST_PER_MILLION_TOKENS=0
LLM_OUTPUT_COST_PER_MILLION_TOKENS=0
```

Provider-reported usage is preferred. When an OpenAI-compatible provider omits
usage, the runtime records a local estimate and sets
`token_usage_source=estimated`.

## Trace Privacy

Structured query traces never persist raw queries, prompts, answers, errors,
credentials, or extracted user terms. These values are replaced before the
sink boundary with a salted SHA-256 fingerprint and character count. This
applies to JSONL, asynchronous, and injected trace sinks.

Use a deployment-specific secret when fingerprints need to correlate across
process restarts:

```text
QUERY_TRACE_FINGERPRINT_SALT=replace-with-a-random-secret
```

When the value is empty, the process generates an ephemeral random salt. Raw
trace content cannot be enabled through configuration.
