from __future__ import annotations

from types import SimpleNamespace

from rag_modules.telemetry import RuntimeTelemetry, TelemetryIdentity


def _telemetry() -> RuntimeTelemetry:
    return RuntimeTelemetry(
        TelemetryIdentity(
            service_name="runtime-telemetry-test",
            model_name="test-model",
            opentelemetry_enabled=False,
            otlp_endpoint="",
            sample_ratio=0.0,
            prometheus_enabled=True,
            input_cost_per_million_tokens=0.0,
            output_cost_per_million_tokens=0.0,
        )
    )


def test_runtime_telemetry_exports_low_cardinality_operational_signals() -> None:
    telemetry = _telemetry()
    result = SimpleNamespace(
        strategy="combined",
        status="degraded",
        latency_ms=1_500.0,
        doc_count=2,
        generation_trace=SimpleNamespace(
            mode="direct",
            provider_latency_ms=800.0,
            first_token_latency_ms=125.0,
            prompt_tokens=10,
            completion_tokens=5,
            estimated_cost_usd=0.0,
        ),
        route_trace=SimpleNamespace(
            diagnostics=SimpleNamespace(
                planner_used_cache=True,
                degraded_sources=["vector"],
                degraded_candidates=[
                    {
                        "source": "vector",
                        "error": {
                            "code": "RETRIEVAL_FAILED",
                            "detail": "candidate_source_circuit_open",
                        },
                    }
                ],
            )
        ),
    )

    telemetry.record_answer(result)
    telemetry.record_admission(wait_seconds=0.02, accepted=True)
    telemetry.record_admission(wait_seconds=0.25, accepted=False)
    telemetry.record_sse_executor_state(queue_wait_seconds=0.05)
    telemetry.record_hot_refresh("refreshed")
    telemetry.record_readiness_state(component="serving", ready=False)
    telemetry.record_readiness_state(component="serving", ready=True)
    telemetry.record_build_lease_event(
        backend="external_worker",
        event="claimed",
        active_delta=1,
    )
    telemetry.record_build_lease_event(
        backend="external_worker",
        event="released",
        active_delta=-1,
    )

    metrics = telemetry.prometheus_payload().decode("utf-8")

    assert (
        'graphrag_generation_first_token_latency_seconds_sum{mode="direct",model="test-model"} '
        "0.125"
    ) in metrics
    assert 'graphrag_admission_wait_seconds_count{outcome="accepted"} 1.0' in metrics
    assert 'graphrag_admission_wait_seconds_count{outcome="rejected"} 1.0' in metrics
    assert "graphrag_admission_rejected_total 1.0" in metrics
    assert "graphrag_sse_queue_wait_seconds_sum 0.05" in metrics
    assert (
        'graphrag_retrieval_degradation_total{reason="circuit_open",source="vector"} 1.0' in metrics
    )
    assert 'graphrag_circuit_breaker_state{source="vector",state="open"} 1.0' in metrics
    assert 'graphrag_cache_access_total{cache="query_plan",result="hit"} 1.0' in metrics
    assert 'graphrag_hot_refresh_total{outcome="refreshed"} 1.0' in metrics
    assert (
        'graphrag_readiness_transitions_total{component="serving",from_state="not_ready",'
        'to_state="ready"} 1.0'
    ) in metrics
    assert 'graphrag_build_leases_active{backend="external_worker"} 0.0' in metrics
    assert (
        'graphrag_build_lease_events_total{backend="external_worker",event="claimed"} 1.0'
        in metrics
    )


def test_runtime_telemetry_drops_unbounded_metric_label_values() -> None:
    telemetry = _telemetry()

    telemetry.record_hot_refresh("customer/request/123456")
    telemetry.record_cache_access(cache="x" * 80, hit=False)

    metrics = telemetry.prometheus_payload().decode("utf-8")
    assert 'graphrag_hot_refresh_total{outcome="unknown"} 1.0' in metrics
    assert 'graphrag_cache_access_total{cache="unknown",result="miss"} 1.0' in metrics
