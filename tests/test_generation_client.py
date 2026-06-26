from __future__ import annotations

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.generation.client import (
    GenerationClientAdapter,
    GenerationProviderResponseError,
)

ROOT = Path(__file__).resolve().parents[1]


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
    def test_canonical_generation_clients_package_exports_existing_surface(self) -> None:
        from rag_modules.generation import client as legacy
        from rag_modules.generation import clients

        for name in (
            "GenerationClientAdapter",
            "GenerationLatencyBudgetExceeded",
            "GenerationProviderResponseError",
            "build_openai_client",
            "generation_failure_code",
            "is_retryable_generation_error",
            "resolve_api_key",
        ):
            self.assertIs(getattr(clients, name), getattr(legacy, name))

    def test_legacy_generation_client_module_is_thin_export(self) -> None:
        path = ROOT / "rag_modules" / "generation" / "client.py"
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        allowed_import_modules = {
            "__future__",
            "rag_modules.generation.clients",
        }
        imported_modules: set[str] = set()
        violations: list[str] = []

        for index, node in enumerate(tree.body):
            if (
                index == 0
                and isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                continue
            if isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                if node.level:
                    module_name = f"rag_modules.generation.{module_name.lstrip('.')}"
                imported_modules.add(module_name)
                if module_name not in allowed_import_modules:
                    violations.append(
                        f"{path.name}:{node.lineno}: unexpected import {module_name!r}"
                    )
                if any(alias.name == "*" for alias in node.names):
                    violations.append(
                        f"{path.name}:{node.lineno}: star import is not a thin export"
                    )
                continue
            if isinstance(node, ast.Assign) and all(
                isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
            ):
                continue
            violations.append(f"{path.name}:{node.lineno}: local logic remains")

        self.assertIn("rag_modules.generation.clients", imported_modules)
        self.assertFalse(violations, "\n".join(violations))

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
