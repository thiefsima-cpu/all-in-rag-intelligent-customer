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
- `graphrag_generation_tokens_total`
- `graphrag_generation_cost_usd_total`

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
