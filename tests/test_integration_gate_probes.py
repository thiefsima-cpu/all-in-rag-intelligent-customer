from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from scripts.gates import GateFailureType
from scripts.integration_gate import probes
from scripts.integration_gate.models import (
    DEFAULT_POLICY_PATH,
    IntegrationGateSettings,
    load_integration_policy,
)
from scripts.integration_gate.probes import run_dependency_probes

FORBIDDEN_FAILURE_SUBSTRINGS = ("secret", "password", "leaked", "token", "bearer")


def build_settings(*, api_token: str | None = "secret-token") -> IntegrationGateSettings:
    return IntegrationGateSettings(
        api_url="http://serving.local",
        api_token=api_token,
        neo4j_uri="bolt://neo4j.local:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        neo4j_database="neo4j",
        milvus_host="milvus.local",
        milvus_port="19530",
        milvus_collection_name="cooking_knowledge",
    )


class FakeNeo4jRecord:
    def __init__(self, recipe_count: int) -> None:
        self._recipe_count = recipe_count

    def __getitem__(self, key: str) -> int:
        if key != "recipe_count":
            raise KeyError(key)
        return self._recipe_count


class FakeNeo4jResult:
    def __init__(self, recipe_count: int) -> None:
        self._recipe_count = recipe_count

    def single(self) -> FakeNeo4jRecord:
        return FakeNeo4jRecord(self._recipe_count)


class FakeNeo4jSession:
    def __init__(self, driver: FakeNeo4jDriver) -> None:
        self._driver = driver

    def __enter__(self) -> FakeNeo4jSession:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def run(self, query: str) -> FakeNeo4jResult:
        self._driver.queries.append(query)
        if self._driver.run_error is not None:
            raise self._driver.run_error
        return FakeNeo4jResult(self._driver.recipe_count)


class FakeNeo4jDriver:
    def __init__(self, *, recipe_count: int = 1, run_error: Exception | None = None) -> None:
        self.recipe_count = recipe_count
        self.run_error = run_error
        self.closed = False
        self.queries: list[str] = []
        self.session_databases: list[str | None] = []

    def session(self, *, database: str | None = None) -> FakeNeo4jSession:
        self.session_databases.append(database)
        return FakeNeo4jSession(self)

    def close(self) -> None:
        self.closed = True


class FakeMilvusClient:
    def __init__(
        self,
        *,
        collections: list[str],
        row_count: int = 1,
        aliases: dict[str, str] | None = None,
        list_error: Exception | None = None,
        stats_error: Exception | None = None,
    ) -> None:
        self.collections = collections
        self.row_count = row_count
        self.aliases = aliases or {}
        self.list_error = list_error
        self.stats_error = stats_error
        self.loaded_collections: list[str] = []
        self.closed = False

    def list_collections(self) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        return self.collections

    def describe_alias(self, alias: str) -> dict[str, str]:
        if alias not in self.aliases:
            raise RuntimeError("alias lookup failed with secret details")
        return {"collection_name": self.aliases[alias]}

    def load_collection(self, collection_name: str) -> None:
        self.loaded_collections.append(collection_name)

    def get_collection_stats(self, collection_name: str) -> dict[str, int]:
        if self.stats_error is not None:
            raise self.stats_error
        assert collection_name in self.collections
        return {"row_count": self.row_count}

    def close(self) -> None:
        self.closed = True


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        http_error: Exception | None = None,
        json_error: Exception | None = None,
    ) -> None:
        self._payload = payload or {}
        self._http_error = http_error
        self._json_error = json_error

    def raise_for_status(self) -> None:
        if self._http_error is not None:
            raise self._http_error

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeHttpSession:
    def __init__(
        self,
        *,
        get_responses: dict[str, dict[str, Any] | FakeResponse],
        get_error: Exception | None = None,
    ) -> None:
        self._get_responses = get_responses
        self._get_error = get_error
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> FakeResponse:
        self.requests.append({"url": url, "headers": headers, "timeout": timeout})
        if self._get_error is not None:
            raise self._get_error

        path = url.removeprefix("http://serving.local")
        response = self._get_responses[path]
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)

    def close(self) -> None:
        self.closed = True


def health_ready_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ok",
        "build_initialized": True,
        "serving_initialized": True,
        "artifacts_ready": True,
        "system_ready": True,
        "retrieval_engines_initialized": True,
        "manifest_health": "ready",
    }
    payload.update(overrides)
    return payload


def ready_http_session() -> FakeHttpSession:
    return FakeHttpSession(
        get_responses={
            "/v1/health/ready": health_ready_payload(),
            "/v1/diagnostics": {
                "diagnostics": {
                    "artifacts_ready": True,
                    "retrieval_engines_initialized": True,
                    "system_ready": True,
                }
            },
        }
    )


def run_with_fakes(
    *,
    neo4j: FakeNeo4jDriver | None = None,
    milvus: FakeMilvusClient | None = None,
    http: FakeHttpSession | None = None,
    neo4j_factory: Callable[..., FakeNeo4jDriver] | None = None,
    milvus_factory: Callable[..., FakeMilvusClient] | None = None,
):
    neo4j = neo4j or FakeNeo4jDriver(recipe_count=12)
    milvus = milvus or FakeMilvusClient(collections=["cooking_knowledge"], row_count=20)
    http = http or ready_http_session()
    return run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=neo4j_factory or (lambda *_args, **_kwargs: neo4j),
        milvus_client_factory=milvus_factory or (lambda *_args, **_kwargs: milvus),
        http_session=http,
    )


def test_dependency_probes_return_counts_and_readiness_without_secrets() -> None:
    neo4j = FakeNeo4jDriver(recipe_count=12)
    milvus = FakeMilvusClient(collections=["cooking_knowledge"], row_count=20)
    http = FakeHttpSession(
        get_responses={
            "/v1/health/ready": health_ready_payload(),
            "/v1/diagnostics": {
                "diagnostics": {
                    "artifacts_ready": True,
                    "retrieval_engines_initialized": True,
                    "system_ready": True,
                }
            },
        }
    )

    results = run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=lambda *_args, **_kwargs: neo4j,
        milvus_client_factory=lambda *_args, **_kwargs: milvus,
        http_session=http,
    )

    assert all(result.passed for result in results)
    assert {result.name: result.actual for result in results} == {
        "dependency.neo4j.recipe_count": 12,
        "dependency.milvus.entity_count": 20,
        "dependency.serving.ready": True,
    }
    assert neo4j.closed is True


def test_neo4j_probe_uses_configured_query_database_and_auth() -> None:
    captured: dict[str, object] = {}
    neo4j = FakeNeo4jDriver(recipe_count=12)

    def driver_factory(*args: object, **kwargs: object) -> FakeNeo4jDriver:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return neo4j

    results = run_with_fakes(neo4j=neo4j, neo4j_factory=driver_factory)

    assert results[0].passed
    assert captured == {
        "args": ("bolt://neo4j.local:7687",),
        "kwargs": {"auth": ("neo4j", "password")},
    }
    assert neo4j.session_databases == ["neo4j"]
    assert neo4j.queries == ["MATCH (recipe:Recipe) RETURN count(recipe) AS recipe_count"]


def test_milvus_probe_accepts_configured_collection_alias() -> None:
    milvus = FakeMilvusClient(
        collections=["physical_cooking_knowledge"],
        row_count=20,
        aliases={"cooking_knowledge": "physical_cooking_knowledge"},
    )

    results = run_with_fakes(milvus=milvus)

    assert results[1].passed
    assert results[1].actual == 20
    assert milvus.loaded_collections == ["physical_cooking_knowledge"]
    assert milvus.closed is True


@pytest.mark.parametrize(
    ("factory", "expected_code"),
    [
        (
            lambda: {
                "neo4j_factory": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("bolt://secret-user:secret-password@neo4j.local failed")
                )
            },
            "NEO4J_UNAVAILABLE",
        ),
        (
            lambda: {"neo4j": FakeNeo4jDriver(run_error=RuntimeError("password leaked"))},
            "NEO4J_UNAVAILABLE",
        ),
        (
            lambda: {
                "milvus_factory": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("token leaked")
                )
            },
            "MILVUS_UNAVAILABLE",
        ),
        (
            lambda: {
                "milvus": FakeMilvusClient(
                    collections=["cooking_knowledge"],
                    stats_error=RuntimeError("stats secret"),
                )
            },
            "MILVUS_UNAVAILABLE",
        ),
        (
            lambda: {"milvus": FakeMilvusClient(collections=["other_collection"])},
            "MILVUS_COLLECTION_MISSING",
        ),
        (
            lambda: {"milvus": FakeMilvusClient(collections=["cooking_knowledge"], row_count=0)},
            "MILVUS_COLLECTION_EMPTY",
        ),
        (
            lambda: {
                "http": FakeHttpSession(
                    get_responses={},
                    get_error=RuntimeError("Bearer secret-token leaked"),
                )
            },
            "SERVING_API_UNAVAILABLE",
        ),
        (
            lambda: {
                "http": FakeHttpSession(
                    get_responses={
                        "/v1/health/ready": health_ready_payload(
                            status="not_ready",
                            system_ready=False,
                        ),
                        "/v1/diagnostics": {
                            "diagnostics": {
                                "artifacts_ready": True,
                                "retrieval_engines_initialized": True,
                                "system_ready": True,
                            }
                        },
                    }
                )
            },
            "SERVING_API_NOT_READY",
        ),
    ],
)
def test_dependency_probe_failures_use_stable_codes_without_exception_text(
    factory: Callable[[], dict[str, object]],
    expected_code: str,
) -> None:
    results = run_with_fakes(**factory())
    failures = [result for result in results if result.code == expected_code]

    assert len(failures) == 1
    failure = failures[0]
    assert failure.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert failure.actual in {False, 0, None}
    for value in (failure.code, failure.expected, failure.actual, failure.to_dict()):
        text = str(value).lower()
        assert not any(forbidden in text for forbidden in FORBIDDEN_FAILURE_SUBSTRINGS)


def test_neo4j_driver_closes_when_query_fails() -> None:
    neo4j = FakeNeo4jDriver(run_error=RuntimeError("query secret"))

    run_with_fakes(neo4j=neo4j)

    assert neo4j.closed is True


def test_milvus_client_closes_when_stats_fail() -> None:
    milvus = FakeMilvusClient(
        collections=["cooking_knowledge"],
        stats_error=RuntimeError("stats secret"),
    )

    run_with_fakes(milvus=milvus)

    assert milvus.closed is True


def test_milvus_client_closes_when_list_collections_fails_without_exception_text() -> None:
    milvus = FakeMilvusClient(
        collections=["cooking_knowledge"],
        list_error=RuntimeError("list secret"),
    )

    results = run_with_fakes(milvus=milvus)
    failure = results[1]

    assert failure.code == "MILVUS_UNAVAILABLE"
    assert failure.actual is None
    assert "list secret" not in str(failure.actual)
    assert milvus.closed is True


def test_serving_probe_sends_bearer_token_only_when_configured() -> None:
    settings_with_token = build_settings(api_token="secret-token")
    settings_without_token = build_settings(api_token=None)
    policy = load_integration_policy(DEFAULT_POLICY_PATH)
    with_token_http = ready_http_session()
    without_token_http = ready_http_session()

    run_dependency_probes(
        settings=settings_with_token,
        policy=policy,
        neo4j_driver_factory=lambda *_args, **_kwargs: FakeNeo4jDriver(),
        milvus_client_factory=lambda *_args, **_kwargs: FakeMilvusClient(
            collections=["cooking_knowledge"]
        ),
        http_session=with_token_http,
    )
    run_dependency_probes(
        settings=settings_without_token,
        policy=policy,
        neo4j_driver_factory=lambda *_args, **_kwargs: FakeNeo4jDriver(),
        milvus_client_factory=lambda *_args, **_kwargs: FakeMilvusClient(
            collections=["cooking_knowledge"]
        ),
        http_session=without_token_http,
    )

    assert with_token_http.requests[0]["headers"] == {"Authorization": "Bearer secret-token"}
    assert without_token_http.requests[0]["headers"] == {}


def test_run_dependency_probes_closes_owned_http_session(monkeypatch: pytest.MonkeyPatch) -> None:
    created_sessions: list[FakeHttpSession] = []

    class OwnedHttpSession(FakeHttpSession):
        def __init__(self) -> None:
            super().__init__(
                get_responses={
                    "/v1/health/ready": health_ready_payload(),
                    "/v1/diagnostics": {
                        "diagnostics": {
                            "artifacts_ready": True,
                            "retrieval_engines_initialized": True,
                            "system_ready": True,
                        }
                    },
                }
            )
            created_sessions.append(self)

    monkeypatch.setattr(probes.requests, "Session", OwnedHttpSession)

    results = run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=lambda *_args, **_kwargs: FakeNeo4jDriver(),
        milvus_client_factory=lambda *_args, **_kwargs: FakeMilvusClient(
            collections=["cooking_knowledge"]
        ),
        http_session=None,
    )

    assert all(result.passed for result in results)
    assert len(created_sessions) == 1
    assert created_sessions[0].closed is True


def test_run_dependency_probes_closes_owned_http_session_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_sessions: list[FakeHttpSession] = []

    class OwnedHttpSession(FakeHttpSession):
        def __init__(self) -> None:
            super().__init__(
                get_responses={},
                get_error=RuntimeError("Bearer secret-token leaked"),
            )
            created_sessions.append(self)

    monkeypatch.setattr(probes.requests, "Session", OwnedHttpSession)

    results = run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=lambda *_args, **_kwargs: FakeNeo4jDriver(),
        milvus_client_factory=lambda *_args, **_kwargs: FakeMilvusClient(
            collections=["cooking_knowledge"]
        ),
        http_session=None,
    )

    assert results[2].code == "SERVING_API_UNAVAILABLE"
    assert len(created_sessions) == 1
    assert created_sessions[0].closed is True


def test_run_dependency_probes_does_not_close_external_http_session() -> None:
    http = ready_http_session()

    results = run_dependency_probes(
        settings=build_settings(),
        policy=load_integration_policy(DEFAULT_POLICY_PATH),
        neo4j_driver_factory=lambda *_args, **_kwargs: FakeNeo4jDriver(),
        milvus_client_factory=lambda *_args, **_kwargs: FakeMilvusClient(
            collections=["cooking_knowledge"]
        ),
        http_session=http,
    )

    assert all(result.passed for result in results)
    assert http.closed is False
