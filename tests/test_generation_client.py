from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag_modules.contracts import RequestCancelled, RequestControl
from rag_modules.generation.clients import (
    GenerationClientAdapter,
    GenerationLatencyBudgetExceeded,
    GenerationProviderResponseError,
)


class _FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.completions = _FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


class _CircuitBreaker:
    def __init__(self, before_error: Exception | None = None) -> None:
        self.before_error = before_error
        self.successes = 0
        self.failures = 0

    def call(self, func, *args, **kwargs):
        return func(*args, **kwargs)

    def before_call(self) -> None:
        if self.before_error:
            raise self.before_error

    def record_success(self) -> None:
        self.successes += 1

    def record_failure(self) -> None:
        self.failures += 1


class _FailingStream:
    def __iter__(self):
        yield _stream_chunk("partial")
        raise TimeoutError("stream interrupted")


def _stream_chunk(content=None, *, include_choice: bool = True):
    choices = [SimpleNamespace(delta=SimpleNamespace(content=content))] if include_choice else []
    return SimpleNamespace(choices=choices)


class GenerationClientAdapterTests(unittest.TestCase):
    def test_generation_package_exports_client_construction_surface(self) -> None:
        from rag_modules import generation
        from rag_modules.generation import clients

        for name in (
            "GenerationClientAdapter",
            "build_openai_client",
            "resolve_api_key",
        ):
            self.assertIs(getattr(generation, name), getattr(clients, name))

    def test_completion_captures_provider_token_usage(self) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(
                prompt_tokens=12,
                completion_tokens=4,
                total_tokens=16,
            ),
        )
        adapter = GenerationClientAdapter(
            client=_FakeClient([response]),
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
        )

        adapter.create_completion(
            prompt="test",
            temperature=0.0,
            max_tokens=10,
            timeout=2,
        )

        self.assertEqual(
            adapter.consume_token_usage(),
            {
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "total_tokens": 16,
                "token_usage_source": "provider",
            },
        )
        self.assertNotIn("extra_body", adapter.client.completions.calls[0])

    def test_completion_forwards_explicit_thinking_mode_setting(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
        client = _FakeClient([response])
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            enable_thinking=False,
        )

        adapter.create_completion(
            prompt="test",
            temperature=0.0,
            max_tokens=10,
            timeout=2,
        )

        self.assertEqual(
            {"enable_thinking": False},
            client.completions.calls[0]["extra_body"],
        )

    def test_completion_timeout_is_capped_by_request_control(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
        client = _FakeClient([response])
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
        )
        control = RequestControl.for_timeout(2.0, scope="generation")

        adapter.create_completion(
            prompt="test",
            temperature=0.0,
            max_tokens=10,
            timeout=30,
            control=control,
        )

        self.assertGreater(client.completions.calls[0]["timeout"], 0)
        self.assertLessEqual(client.completions.calls[0]["timeout"], 2.0)

    def test_response_text_rejects_empty_choices_with_stable_code(self) -> None:
        with self.assertRaises(GenerationProviderResponseError) as raised:
            GenerationClientAdapter.response_text(SimpleNamespace(choices=[]))

        self.assertEqual(
            raised.exception.failure_code,
            "generation_provider_empty_choices",
        )

    def test_stream_skips_empty_choice_events(self) -> None:
        client = _FakeClient(
            [
                [
                    _stream_chunk(include_choice=False),
                    _stream_chunk("hello"),
                    _stream_chunk(include_choice=False),
                ]
            ]
        )
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
        )

        chunks = list(
            adapter.stream_prompt(
                prompt="test",
                max_tokens=10,
                retries=1,
                timeout_seconds=2,
            )
        )

        self.assertEqual(chunks, ["hello"])
        self.assertEqual(len(client.completions.calls), 1)

    def test_stream_forwards_explicit_thinking_mode_setting(self) -> None:
        client = _FakeClient([[_stream_chunk("hello")]])
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            enable_thinking=False,
        )

        chunks = list(
            adapter.stream_prompt(
                prompt="test",
                max_tokens=10,
                retries=1,
                timeout_seconds=2,
            )
        )

        self.assertEqual(chunks, ["hello"])
        self.assertEqual(
            {"enable_thinking": False},
            client.completions.calls[0]["extra_body"],
        )

    def test_stream_stops_when_control_cancelled_between_chunks(self) -> None:
        control = RequestControl.for_timeout(5.0, scope="generation")
        client = _FakeClient([[_stream_chunk("hello"), _stream_chunk("world")]])
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
        )

        stream = adapter.stream_prompt(
            prompt="test",
            max_tokens=10,
            retries=1,
            timeout_seconds=5,
            control=control,
        )
        self.assertEqual(next(stream), "hello")
        control.cancel("client_disconnect")

        with self.assertRaises(RequestCancelled):
            next(stream)

    def test_stream_with_only_empty_events_fails_without_retry(self) -> None:
        client = _FakeClient(
            [
                [_stream_chunk(include_choice=False)],
                [_stream_chunk("must not be requested")],
            ]
        )
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=2,
            stream_timeout_seconds=5,
        )

        with self.assertRaises(GenerationProviderResponseError) as raised:
            list(
                adapter.stream_prompt(
                    prompt="test",
                    max_tokens=10,
                    retries=2,
                    timeout_seconds=2,
                )
            )

        self.assertEqual(
            raised.exception.failure_code,
            "generation_provider_empty_content",
        )
        self.assertEqual(len(client.completions.calls), 1)

    def test_completion_estimates_usage_when_provider_omits_usage(self) -> None:
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="estimated completion"))]
        )
        adapter = GenerationClientAdapter(
            client=_FakeClient([response]),
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
        )

        result = adapter.create_completion(
            prompt="estimated prompt",
            temperature=0.0,
            max_tokens=10,
            timeout=2,
        )

        self.assertEqual(GenerationClientAdapter.response_text(result), "estimated completion")
        usage = adapter.consume_token_usage()
        self.assertEqual(usage["token_usage_source"], "estimated")
        self.assertGreater(usage["total_tokens"], 0)

    def test_consume_retry_count_resets_after_provider_retry(self) -> None:
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])
        adapter = GenerationClientAdapter(
            client=_FakeClient([TimeoutError("transient"), response]),
            model_name="test-model",
            default_temperature=0.0,
            request_retries=2,
            stream_timeout_seconds=5,
        )

        with patch("rag_modules.generation.clients.adapter.time.sleep"):
            adapter.create_completion(
                prompt="retry",
                temperature=0.0,
                max_tokens=10,
                timeout=3,
            )

        self.assertEqual(adapter.consume_retry_count(), 1)
        self.assertEqual(adapter.consume_retry_count(), 0)

    def test_completion_propagates_cancel_and_stops_retry_when_deadline_expires(self) -> None:
        control = RequestControl.for_timeout(5.0, scope="generation")
        control.cancel("client_disconnect")
        cancelled = GenerationClientAdapter(
            client=_FakeClient([]),
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            circuit_breaker=_CircuitBreaker(),
        )
        with self.assertRaises(RequestCancelled):
            cancelled.create_completion(
                prompt="cancelled", temperature=0.0, max_tokens=10, timeout=2, control=control
            )

        expired = GenerationClientAdapter(
            client=_FakeClient([TimeoutError("transient")]),
            model_name="test-model",
            default_temperature=0.0,
            request_retries=2,
            stream_timeout_seconds=5,
            circuit_breaker=_CircuitBreaker(),
        )
        with (
            patch(
                "rag_modules.generation.clients.adapter.time.perf_counter",
                side_effect=[0.0, 0.0, 2.0],
            ),
            self.assertRaises(TimeoutError),
        ):
            expired.create_completion(prompt="deadline", temperature=0.0, max_tokens=10, timeout=1)

    def test_stream_retries_before_content_and_records_provider_usage(self) -> None:
        usage_chunk = SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=1, total_tokens=3),
        )
        breaker = _CircuitBreaker()
        adapter = GenerationClientAdapter(
            client=_FakeClient([TimeoutError("transient"), [usage_chunk]]),
            model_name="test-model",
            default_temperature=0.2,
            request_retries=1,
            stream_timeout_seconds=3,
            circuit_breaker=breaker,
        )

        with patch("rag_modules.generation.clients.adapter.time.sleep"):
            chunks = list(adapter.stream_prompt(prompt="retry", max_tokens=10, retries=2))

        self.assertEqual(chunks, ["ok"])
        self.assertEqual(breaker.failures, 1)
        self.assertEqual(breaker.successes, 1)
        self.assertEqual(adapter.consume_token_usage()["token_usage_source"], "provider")

    def test_stream_does_not_retry_after_partial_content_or_preflight_failure(self) -> None:
        breaker = _CircuitBreaker()
        partial_client = _FakeClient([_FailingStream(), [_stream_chunk("unexpected")]])
        partial = GenerationClientAdapter(
            client=partial_client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            circuit_breaker=breaker,
        )

        stream = partial.stream_prompt(prompt="partial", max_tokens=10, retries=2)
        self.assertEqual(next(stream), "partial")
        with self.assertRaises(TimeoutError):
            next(stream)
        self.assertEqual(len(partial_client.completions.calls), 1)
        self.assertEqual(breaker.failures, 1)

        preflight_breaker = _CircuitBreaker(before_error=RuntimeError("circuit open"))
        preflight_client = _FakeClient([[_stream_chunk("unexpected")]])
        preflight = GenerationClientAdapter(
            client=preflight_client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            circuit_breaker=preflight_breaker,
        )
        with self.assertRaises(RuntimeError):
            list(preflight.stream_prompt(prompt="open", max_tokens=10, retries=1))
        self.assertEqual(preflight_breaker.failures, 0)
        self.assertEqual(preflight_client.completions.calls, [])

    def test_stream_rejects_exhausted_deadline_before_provider_call(self) -> None:
        client = _FakeClient([[_stream_chunk("unexpected")]])
        adapter = GenerationClientAdapter(
            client=client,
            model_name="test-model",
            default_temperature=0.0,
            request_retries=1,
            stream_timeout_seconds=5,
            circuit_breaker=_CircuitBreaker(),
        )

        with (
            patch(
                "rag_modules.generation.clients.adapter.time.perf_counter",
                side_effect=[0.0, 2.0],
            ),
            self.assertRaises(GenerationLatencyBudgetExceeded),
        ):
            list(
                adapter.stream_prompt(
                    prompt="expired", max_tokens=10, retries=1, timeout_seconds=0.1
                )
            )
        self.assertEqual(client.completions.calls, [])


if __name__ == "__main__":
    unittest.main()
