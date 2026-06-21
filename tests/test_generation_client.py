from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.generation.client import (
    GenerationClientAdapter,
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


def _stream_chunk(content=None, *, include_choice: bool = True):
    choices = [SimpleNamespace(delta=SimpleNamespace(content=content))] if include_choice else []
    return SimpleNamespace(choices=choices)


class GenerationClientAdapterTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
