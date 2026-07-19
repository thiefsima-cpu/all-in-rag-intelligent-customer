"""Live dependency probes for the integration gate."""

from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any, Protocol

import requests
from pymilvus import MilvusClient

from rag_modules.infra.neo4j import create_neo4j_driver
from scripts.gates import GateCheckResult, GateFailureType

from .models import IntegrationGatePolicy, IntegrationGateSettings

_ENTITY_COUNT_QUERY = """
MATCH (entity)
WHERE entity.domain = $domain_name
   OR ($domain_name = 'recipe' AND entity:Recipe)
RETURN count(entity) AS entity_count
"""


class Neo4jDriverFactory(Protocol):
    def __call__(self, uri: str, user: str, password: str) -> Any: ...


class MilvusClientFactory(Protocol):
    def __call__(self, *, uri: str) -> Any: ...


def run_dependency_probes(
    *,
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
    neo4j_driver_factory: Neo4jDriverFactory = create_neo4j_driver,
    milvus_client_factory: MilvusClientFactory = MilvusClient,
    http_session: requests.Session | None = None,
) -> tuple[GateCheckResult, ...]:
    owns_session = http_session is None
    session = http_session if http_session is not None else requests.Session()
    try:
        return (
            probe_neo4j(
                settings=settings,
                minimum_count=policy.dependency_minimums.neo4j_entity_count,
                driver_factory=neo4j_driver_factory,
            ),
            probe_milvus(
                settings=settings,
                minimum_count=policy.dependency_minimums.milvus_entity_count,
                client_factory=milvus_client_factory,
            ),
            probe_serving(
                settings=settings,
                timeout_seconds=policy.timeouts.probe_seconds,
                http_session=session,
            ),
        )
    finally:
        if owns_session:
            _close_quietly(session)


def probe_neo4j(
    *,
    settings: IntegrationGateSettings,
    minimum_count: int,
    driver_factory: Neo4jDriverFactory,
) -> GateCheckResult:
    start_time = perf_counter()
    driver: Any | None = None

    try:
        driver = driver_factory(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
        )
        try:
            session_context = driver.session(database=settings.neo4j_database)
        except TypeError:
            session_context = driver.session()

        with session_context as session:
            result = session.run(_ENTITY_COUNT_QUERY, {"domain_name": settings.domain_name})
            record = result.single()
        entity_count = _safe_int(_record_value(record, "entity_count"))
    except Exception:
        return _dependency_failure(
            "dependency.neo4j.entity_count",
            code="NEO4J_UNAVAILABLE",
            expected={"minimum": minimum_count},
            actual=None,
            start_time=start_time,
        )
    finally:
        _close_quietly(driver)

    if entity_count is None or entity_count < minimum_count:
        return _dependency_failure(
            "dependency.neo4j.entity_count",
            code="NEO4J_UNAVAILABLE",
            expected={"minimum": minimum_count},
            actual=entity_count,
            start_time=start_time,
        )

    return GateCheckResult.pass_check(
        "dependency.neo4j.entity_count",
        code="NEO4J_READY",
        expected={"minimum": minimum_count},
        actual=entity_count,
        duration_ms=_elapsed_ms(start_time),
    )


def probe_milvus(
    *,
    settings: IntegrationGateSettings,
    minimum_count: int,
    client_factory: MilvusClientFactory,
) -> GateCheckResult:
    start_time = perf_counter()
    client: Any | None = None

    try:
        client = client_factory(uri=f"http://{settings.milvus_host}:{settings.milvus_port}")
        collections = set(client.list_collections())
    except Exception:
        _close_quietly(client)
        return _dependency_failure(
            "dependency.milvus.entity_count",
            code="MILVUS_UNAVAILABLE",
            expected={"minimum": minimum_count},
            actual=None,
            start_time=start_time,
        )

    try:
        target_collection = _resolve_milvus_collection(
            client,
            configured_name=settings.milvus_collection_name,
            collections=collections,
        )
        if target_collection is None:
            return _dependency_failure(
                "dependency.milvus.entity_count",
                code="MILVUS_COLLECTION_MISSING",
                expected=settings.milvus_collection_name,
                actual=False,
                start_time=start_time,
            )

        load_collection = getattr(client, "load_collection", None)
        if callable(load_collection):
            load_collection(target_collection)

        stats = client.get_collection_stats(target_collection)
        row_count = _safe_int(_mapping_value(stats, "row_count"))
    except Exception:
        return _dependency_failure(
            "dependency.milvus.entity_count",
            code="MILVUS_UNAVAILABLE",
            expected={"minimum": minimum_count},
            actual=None,
            start_time=start_time,
        )
    finally:
        _close_quietly(client)

    if row_count is None:
        return _dependency_failure(
            "dependency.milvus.entity_count",
            code="MILVUS_UNAVAILABLE",
            expected={"minimum": minimum_count},
            actual=None,
            start_time=start_time,
        )

    if row_count < minimum_count:
        return _dependency_failure(
            "dependency.milvus.entity_count",
            code="MILVUS_COLLECTION_EMPTY",
            expected={"minimum": minimum_count},
            actual=row_count,
            start_time=start_time,
        )

    return GateCheckResult.pass_check(
        "dependency.milvus.entity_count",
        code="MILVUS_READY",
        expected={"minimum": minimum_count},
        actual=row_count,
        duration_ms=_elapsed_ms(start_time),
    )


def probe_serving(
    *,
    settings: IntegrationGateSettings,
    timeout_seconds: float,
    http_session: requests.Session,
) -> GateCheckResult:
    start_time = perf_counter()
    headers = {}
    if settings.api_token:
        headers["Authorization"] = f"Bearer {settings.api_token}"

    try:
        ready_payload = _get_json(
            http_session,
            url=f"{settings.api_url.rstrip('/')}/v1/health/ready",
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
        diagnostics_payload = _get_json(
            http_session,
            url=f"{settings.api_url.rstrip('/')}/v1/diagnostics",
            headers=headers,
            timeout_seconds=timeout_seconds,
        )
    except Exception:
        return _dependency_failure(
            "dependency.serving.ready",
            code="SERVING_API_UNAVAILABLE",
            expected=True,
            actual=False,
            start_time=start_time,
        )

    if not _readiness_ready(ready_payload) or not _diagnostics_ready(
        diagnostics_payload,
        expected_domain=settings.domain_name,
    ):
        return _dependency_failure(
            "dependency.serving.ready",
            code="SERVING_API_NOT_READY",
            expected=True,
            actual=False,
            start_time=start_time,
        )

    return GateCheckResult.pass_check(
        "dependency.serving.ready",
        code="SERVING_API_READY",
        expected=True,
        actual=True,
        duration_ms=_elapsed_ms(start_time),
    )


def _resolve_milvus_collection(
    client: Any,
    *,
    configured_name: str,
    collections: set[str],
) -> str | None:
    if configured_name in collections:
        return configured_name

    describe_alias = getattr(client, "describe_alias", None)
    if not callable(describe_alias):
        return None

    try:
        alias_description = describe_alias(configured_name)
    except Exception:
        return None

    resolved_name = _alias_collection_name(alias_description)
    if resolved_name in collections:
        return resolved_name
    return None


def _alias_collection_name(alias_description: Any) -> str | None:
    if isinstance(alias_description, Mapping):
        value = alias_description.get("collection_name") or alias_description.get("collection")
        return value if isinstance(value, str) else None

    value = getattr(alias_description, "collection_name", None) or getattr(
        alias_description, "collection", None
    )
    return value if isinstance(value, str) else None


def _get_json(
    http_session: requests.Session,
    *,
    url: str,
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    response = http_session.get(url, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Response JSON payload is not an object")
    return payload


def _diagnostics_ready(
    payload: Mapping[str, Any],
    *,
    expected_domain: str,
) -> bool:
    diagnostics = payload.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        return False

    return (
        diagnostics.get("domain_name") == expected_domain
        and diagnostics.get("artifacts_ready") is True
        and diagnostics.get("retrieval_engines_initialized") is True
        and diagnostics.get("system_ready") is True
    )


def _readiness_ready(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("status") == "ok"
        and payload.get("artifacts_ready") is True
        and payload.get("retrieval_engines_initialized") is True
        and payload.get("system_ready") is True
    )


def _record_value(record: Any, key: str) -> Any:
    if record is None:
        return None
    try:
        return record[key]
    except Exception:
        return getattr(record, key, None)


def _mapping_value(value: Any, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _dependency_failure(
    name: str,
    *,
    code: str,
    expected: Any,
    actual: Any,
    start_time: float,
) -> GateCheckResult:
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
        code=code,
        expected=expected,
        actual=actual,
        duration_ms=_elapsed_ms(start_time),
    )


def _elapsed_ms(start_time: float) -> float:
    return (perf_counter() - start_time) * 1000


def _close_quietly(resource: Any | None) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
