from __future__ import annotations

import pytest
from pydantic import ValidationError

from scripts.integration_gate.models import (
    DEFAULT_POLICY_PATH,
    IntegrationGateSettings,
    load_integration_policy,
)


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


def test_policy_rejects_duplicate_ids_and_non_positive_limits() -> None:
    policy = load_integration_policy(DEFAULT_POLICY_PATH)
    payload = policy.model_dump(mode="json")
    payload["live_cases"][1]["case_id"] = payload["live_cases"][0]["case_id"]
    payload["timeouts"]["probe_seconds"] = 0

    with pytest.raises(ValidationError):
        type(policy).model_validate(payload)


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
        "api_host": "localhost",
        "neo4j_host": "localhost",
        "milvus_host": "localhost",
    }

    environment.pop("NEO4J_PASSWORD")
    with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
        IntegrationGateSettings.from_environ(environment)


def test_safe_target_identity_strips_sensitive_url_parts_and_token() -> None:
    environment = {
        "INTEGRATION_GATE_API_URL": "https://api_user:api_pass@example.com:8443/v1?token=secret/",
        "INTEGRATION_GATE_API_TOKEN": "super-secret-token",
        "NEO4J_URI": "bolt://neo4j_user:neo4j_pass@graph.internal:7687/db?x=y",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password",
        "NEO4J_DATABASE": "neo4j",
        "MILVUS_HOST": "user:pass@milvus.internal/path?token=s",
        "MILVUS_PORT": "19530",
        "MILVUS_COLLECTION_NAME": "cooking_knowledge",
    }
    settings = IntegrationGateSettings.from_environ(environment)

    assert settings.api_token == "super-secret-token"
    assert settings.safe_target_identity() == {
        "api_host": "example.com",
        "neo4j_host": "graph.internal",
        "milvus_host": "milvus.internal",
    }
