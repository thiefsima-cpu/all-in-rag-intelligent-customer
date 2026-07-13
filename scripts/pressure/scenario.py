from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PressureScenario:
    name: str
    requests: int
    workers: int
    answer_delay_ms: float
    trace_delay_ms: float
    trace_queue_size: int
    max_concurrent_answers: int
    answer_acquire_timeout_seconds: float
    synthetic_model_latency_ms: float = 0.0
    synthetic_input_tokens_per_request: int = 0
    synthetic_output_tokens_per_request: int = 0
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0
    retrieval_degraded_every: int = 0
    retrieval_degraded_source: str = "vector"

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "requests": self.requests,
            "workers": self.workers,
            "answer_delay_ms": round(self.answer_delay_ms, 2),
            "trace_delay_ms": round(self.trace_delay_ms, 2),
            "trace_queue_size": self.trace_queue_size,
            "max_concurrent_answers": self.max_concurrent_answers,
            "answer_acquire_timeout_seconds": round(
                self.answer_acquire_timeout_seconds,
                4,
            ),
            "synthetic_model_latency_ms": round(self.synthetic_model_latency_ms, 2),
            "synthetic_input_tokens_per_request": self.synthetic_input_tokens_per_request,
            "synthetic_output_tokens_per_request": self.synthetic_output_tokens_per_request,
            "input_cost_per_million_tokens": self.input_cost_per_million_tokens,
            "output_cost_per_million_tokens": self.output_cost_per_million_tokens,
            "retrieval_degraded_every": self.retrieval_degraded_every,
            "retrieval_degraded_source": self.retrieval_degraded_source,
        }


DEFAULT_PRESSURE_SCENARIO = PressureScenario(
    name="api_concurrency_baseline",
    requests=200,
    workers=4,
    answer_delay_ms=20.0,
    trace_delay_ms=0.0,
    trace_queue_size=32,
    max_concurrent_answers=4,
    answer_acquire_timeout_seconds=0.25,
)


def default_pressure_scenario(
    *,
    scenario_name: str | None = None,
    requests: int | None = None,
    workers: int | None = None,
    answer_delay_ms: float | None = None,
    trace_delay_ms: float | None = None,
    trace_queue_size: int | None = None,
    max_concurrent_answers: int | None = None,
    answer_acquire_timeout_seconds: float | None = None,
    synthetic_model_latency_ms: float | None = None,
    synthetic_input_tokens_per_request: int | None = None,
    synthetic_output_tokens_per_request: int | None = None,
    input_cost_per_million_tokens: float | None = None,
    output_cost_per_million_tokens: float | None = None,
    retrieval_degraded_every: int | None = None,
    retrieval_degraded_source: str | None = None,
) -> PressureScenario:
    defaults = DEFAULT_PRESSURE_SCENARIO
    return PressureScenario(
        name=str(scenario_name or defaults.name),
        requests=max(1, int(defaults.requests if requests is None else requests)),
        workers=max(1, int(defaults.workers if workers is None else workers)),
        answer_delay_ms=max(
            0.0,
            float(defaults.answer_delay_ms if answer_delay_ms is None else answer_delay_ms),
        ),
        trace_delay_ms=max(
            0.0,
            float(defaults.trace_delay_ms if trace_delay_ms is None else trace_delay_ms),
        ),
        trace_queue_size=max(
            0,
            int(defaults.trace_queue_size if trace_queue_size is None else trace_queue_size),
        ),
        max_concurrent_answers=max(
            1,
            int(
                defaults.max_concurrent_answers
                if max_concurrent_answers is None
                else max_concurrent_answers
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            float(
                defaults.answer_acquire_timeout_seconds
                if answer_acquire_timeout_seconds is None
                else answer_acquire_timeout_seconds
            ),
        ),
        synthetic_model_latency_ms=max(
            0.0,
            float(
                defaults.synthetic_model_latency_ms
                if synthetic_model_latency_ms is None
                else synthetic_model_latency_ms
            ),
        ),
        synthetic_input_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_input_tokens_per_request
                if synthetic_input_tokens_per_request is None
                else synthetic_input_tokens_per_request
            ),
        ),
        synthetic_output_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_output_tokens_per_request
                if synthetic_output_tokens_per_request is None
                else synthetic_output_tokens_per_request
            ),
        ),
        input_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.input_cost_per_million_tokens
                if input_cost_per_million_tokens is None
                else input_cost_per_million_tokens
            ),
        ),
        output_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.output_cost_per_million_tokens
                if output_cost_per_million_tokens is None
                else output_cost_per_million_tokens
            ),
        ),
        retrieval_degraded_every=max(
            0,
            int(
                defaults.retrieval_degraded_every
                if retrieval_degraded_every is None
                else retrieval_degraded_every
            ),
        ),
        retrieval_degraded_source=str(
            retrieval_degraded_source or defaults.retrieval_degraded_source
        ),
    )
