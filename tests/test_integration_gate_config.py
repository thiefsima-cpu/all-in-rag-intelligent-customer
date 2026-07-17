from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from scripts.integration_gate.models import (
    DEFAULT_POLICY_PATH,
    IntegrationGatePolicy,
    IntegrationGateSettings,
    load_integration_policy,
)


def _default_policy_payload() -> dict[str, Any]:
    return load_integration_policy(DEFAULT_POLICY_PATH).model_dump(mode="json")


def _set_payload_path(payload: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    target: Any = payload
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value


def test_default_policy_has_three_unique_dependency_covering_cases() -> None:
    policy = load_integration_policy(DEFAULT_POLICY_PATH)

    assert [case.case_id for case in policy.live_cases] == [
        "vector_recipe_lookup",
        "graph_relationship_reasoning",
        "combined_constrained_recommendation",
    ]
    assert {source for case in policy.live_cases for source in case.required_sources} >= {
        "vector",
        "graph_rag",
    }
    assert all(case.generation_required for case in policy.live_cases)

    combined_case = next(
        case for case in policy.live_cases if case.case_id == "combined_constrained_recommendation"
    )
    assert combined_case.required_sources == ["traditional", "graph_rag"]

    combined_case = next(
        case for case in policy.live_cases if case.case_id == "combined_constrained_recommendation"
    )
    assert combined_case.required_sources == ["traditional", "graph_rag"]


def test_policy_rejects_duplicate_live_case_ids() -> None:
    payload = _default_policy_payload()
    payload["live_cases"][1]["case_id"] = payload["live_cases"][0]["case_id"]

    with pytest.raises(
        ValidationError, match="Duplicate integration gate live case IDs"
    ) as exc_info:
        IntegrationGatePolicy.model_validate(payload)

    assert payload["live_cases"][0]["case_id"] in str(exc_info.value)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("live_cases", 0, "case_id"), "Bad Case?/secret"),
        (("live_cases", 0, "allowed_strategies"), ["combined", "bad strategy"]),
        (("live_cases", 0, "required_sources"), ["vector", "graph/rag"]),
        (("live_cases", 0, "allowed_strategies"), ["combined", "combined"]),
    ],
)
def test_policy_rejects_noncanonical_live_case_identifiers(
    path: tuple[str | int, ...],
    invalid_value: Any,
) -> None:
    payload = _default_policy_payload()
    _set_payload_path(payload, path, invalid_value)

    with pytest.raises(ValidationError) as exc_info:
        IntegrationGatePolicy.model_validate(payload)

    assert str(path[-1]) in str(exc_info.value)


@pytest.mark.parametrize(
    "path",
    [
        ("dependency_minimums", "neo4j_recipe_count"),
        ("dependency_minimums", "milvus_entity_count"),
        ("timeouts", "probe_seconds"),
        ("timeouts", "request_seconds"),
        ("live_cases", 0, "minimum_evidence_count"),
        ("live_cases", 0, "timeout_seconds"),
        ("thresholds", "maximum_p95_latency_ms"),
    ],
)
def test_policy_rejects_non_positive_timeouts_and_limits(path: tuple[str | int, ...]) -> None:
    payload = _default_policy_payload()
    _set_payload_path(payload, path, 0)

    with pytest.raises(ValidationError) as exc_info:
        IntegrationGatePolicy.model_validate(payload)

    assert str(path[-1]) in str(exc_info.value)


@pytest.mark.parametrize(
    ("path", "invalid_value"),
    [
        (("dependency_minimums", "neo4j_recipe_count"), "1"),
        (("live_cases", 0, "generation_required"), "true"),
        (("thresholds", "maximum_fallback_rate"), float("nan")),
    ],
)
def test_policy_uses_strict_scalar_validation(
    path: tuple[str | int, ...], invalid_value: Any
) -> None:
    payload = _default_policy_payload()
    _set_payload_path(payload, path, invalid_value)

    with pytest.raises(ValidationError) as exc_info:
        IntegrationGatePolicy.model_validate(payload)

    assert str(path[-1]) in str(exc_info.value)


def test_policy_forbids_extra_fields() -> None:
    payload = _default_policy_payload()
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        IntegrationGatePolicy.model_validate(payload)


def test_settings_require_explicit_endpoints_and_keep_token_optional() -> None:
    environment = {
        "INTEGRATION_GATE_API_URL": "http://localhost:8000",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "localhost",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }
    settings = IntegrationGateSettings.from_environ(environment)

    assert settings.api_url == "http://localhost:8000"
    assert settings.api_token is None
    assert settings.safe_target_identity() == {
        "api_host": "localhost:8000",
        "neo4j_host": "localhost",
        "milvus_host": "localhost",
    }

    environment.pop("NEO4J_PASSWORD")
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        IntegrationGateSettings.from_environ(environment)


def test_safe_target_identity_uses_only_validated_host_parts() -> None:
    environment = {
        "INTEGRATION_GATE_API_URL": "https://example.com:8443",
        "INTEGRATION_GATE_API_TOKEN": "super-secret-token",
        "NEO4J_URI": "bolt://graph.internal:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "milvus.internal",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }
    settings = IntegrationGateSettings.from_environ(environment)

    assert settings.api_token == "super-secret-token"
    assert settings.safe_target_identity() == {
        "api_host": "example.com:8443",
        "neo4j_host": "graph.internal",
        "milvus_host": "milvus.internal",
    }


def test_safe_target_identity_preserves_bracketed_ipv6_api_port() -> None:
    settings = IntegrationGateSettings.from_environ(
        {
            "INTEGRATION_GATE_API_URL": "https://[2001:0DB8::1]:8443",
            "NEO4J_URI": "bolt://graph.internal:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": "password",
            "NEO4J_DATABASE": "neo4j",
            "MILVUS_HOST": "milvus.internal",
            "MILVUS_PORT": "19530",
            "MILVUS_COLLECTION_NAME": "cooking_knowledge",
        }
    )

    assert settings.safe_target_identity()["api_host"] == "[2001:db8::1]:8443"


@pytest.mark.parametrize(
    ("name", "invalid_value"),
    [
        (
            "INTEGRATION_GATE_API_URL",
            "https://api_user:api_pass@example.com:8443/v1?token=secret",
        ),
        ("INTEGRATION_GATE_API_URL", "https://example.com:"),
        ("INTEGRATION_GATE_API_URL", "https://example.com:0"),
        ("INTEGRATION_GATE_API_URL", "ftp://example.com"),
        ("INTEGRATION_GATE_API_TOKEN", "Bearer raw secret"),
        ("INTEGRATION_GATE_API_TOKEN", "token with spaces"),
        ("NEO4J_URI", "bolt://neo4j_user:neo4j_pass@graph.internal:7687/db?x=y"),
        ("NEO4J_URI", "bolt://graph.internal:"),
        ("NEO4J_URI", "bolt://graph.internal:0"),
        ("NEO4J_URI", "http://graph.internal:7687"),
        ("NEO4J_DATABASE", "neo4j/default"),
        ("MILVUS_HOST", "user:pass@milvus.internal/path?token=s"),
        ("MILVUS_HOST", "milvus.internal:"),
        ("MILVUS_HOST", "milvus.internal:19530"),
        ("MILVUS_PORT", "not-a-port"),
        ("MILVUS_PORT", "0"),
        ("MILVUS_PORT", "65536"),
        ("MILVUS_COLLECTION_NAME", "collection/name"),
    ],
)
def test_settings_reject_noncanonical_environment_values(
    name: str,
    invalid_value: str,
) -> None:
    environment = {
        "INTEGRATION_GATE_API_URL": "http://localhost:8000",
        "INTEGRATION_GATE_API_TOKEN": "safe-token_123",
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "localhost",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }
    environment[name] = invalid_value

    with pytest.raises(ValueError, match=name):
        IntegrationGateSettings.from_environ(environment)
