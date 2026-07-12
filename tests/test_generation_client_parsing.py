from __future__ import annotations

from types import SimpleNamespace

import pytest

from rag_modules.generation.clients.errors import GenerationProviderResponseError
from rag_modules.generation.clients.parsing import (
    estimate_tokens,
    load_json_payload,
    response_content,
    response_text,
    strip_code_fence,
)


def test_response_content_accepts_mapping_and_object_provider_shapes() -> None:
    assert response_content({"choices": [{"message": {"content": "mapped"}}]}) == "mapped"
    assert (
        response_content(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="object"))])
        )
        == "object"
    )
    assert response_content({"choices": []}) == ""
    assert response_content({"choices": [{"message": None}]}) == ""
    assert response_content({"choices": [{"message": {"content": None}}]}) == ""


def test_response_text_validates_choices_and_nonempty_content() -> None:
    assert (
        response_text(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=" ok "))])
        )
        == "ok"
    )
    with pytest.raises(GenerationProviderResponseError, match="empty content") as empty_content:
        response_text(
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="  "))])
        )
    assert empty_content.value.failure_code == "generation_provider_empty_content"


def test_token_estimation_and_code_fence_stripping_cover_text_shapes() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("菜谱ab") == 3
    assert strip_code_fence('```json\n{"ok": true}\n```') == '{"ok": true}'
    assert strip_code_fence("```json") == "```json"
    assert strip_code_fence(" plain ") == "plain"


def test_json_loader_accepts_direct_and_embedded_objects_and_rejects_other_payloads() -> None:
    assert load_json_payload('{"ok": true}') == {"ok": True}
    assert load_json_payload('prefix {"value": 2} suffix') == {"value": 2}
    assert load_json_payload('```json\n{"fenced": true}\n```') == {"fenced": True}
    with pytest.raises(ValueError, match="valid JSON object"):
        load_json_payload("[1, 2]")
    with pytest.raises(ValueError, match="valid JSON object"):
        load_json_payload("no json here")
