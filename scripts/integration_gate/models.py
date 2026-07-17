"""Strict policy and runtime settings for the live dependency integration gate."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import Literal, Mapping, Self
from urllib.parse import SplitResult, urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scripts.gates import GateCheckResult, GateCheckStatus

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT_DIR / "eval" / "integration_gate.json"
_POLICY_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SETTING_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_BEARER_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/-]+={0,}$")
_HTTP_SCHEMES = frozenset({"http", "https"})
_NEO4J_SCHEMES = frozenset({"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"})


class StrictPolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class DependencyMinimums(StrictPolicyModel):
    neo4j_recipe_count: int = Field(ge=1)
    milvus_entity_count: int = Field(ge=1)


class GateTimeouts(StrictPolicyModel):
    probe_seconds: float = Field(gt=0)
    request_seconds: float = Field(gt=0)


class LiveCasePolicy(StrictPolicyModel):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    allowed_strategies: list[str] = Field(min_length=1)
    required_sources: list[str] = Field(min_length=1)
    minimum_evidence_count: int = Field(ge=1)
    generation_required: bool
    timeout_seconds: float = Field(gt=0)

    @field_validator("case_id")
    @classmethod
    def reject_noncanonical_case_id(cls, value: str) -> str:
        return _canonical_policy_identifier(value, "case_id")

    @field_validator("allowed_strategies", "required_sources")
    @classmethod
    def reject_noncanonical_identifier_lists(cls, values: list[str]) -> list[str]:
        seen_values: set[str] = set()
        for value in values:
            canonical_value = _canonical_policy_identifier(value, "live case identifier")
            if canonical_value in seen_values:
                raise ValueError("Duplicate live case identifier")
            seen_values.add(canonical_value)
        return values


class IntegrationThresholds(StrictPolicyModel):
    maximum_fallback_rate: float = Field(ge=0, le=1)
    maximum_retrieval_degradation_rate: float = Field(ge=0, le=1)
    maximum_p95_latency_ms: float = Field(gt=0)
    maximum_estimated_cost_usd: float = Field(ge=0)


class IntegrationGatePolicy(StrictPolicyModel):
    schema_version: Literal[1]
    dependency_minimums: DependencyMinimums
    timeouts: GateTimeouts
    thresholds: IntegrationThresholds
    live_cases: list[LiveCasePolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_case_ids(self) -> Self:
        seen_case_ids: set[str] = set()
        duplicate_case_ids: set[str] = set()
        for live_case in self.live_cases:
            if live_case.case_id in seen_case_ids:
                duplicate_case_ids.add(live_case.case_id)
            seen_case_ids.add(live_case.case_id)

        if duplicate_case_ids:
            joined_case_ids = ", ".join(sorted(duplicate_case_ids))
            raise ValueError(f"Duplicate integration gate live case IDs: {joined_case_ids}")

        return self


def load_integration_policy(path: str | Path = DEFAULT_POLICY_PATH) -> IntegrationGatePolicy:
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return IntegrationGatePolicy.model_validate(payload)


@dataclass(frozen=True)
class IntegrationGateSettings:
    api_url: str
    api_token: str | None
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    milvus_host: str
    milvus_port: str
    milvus_collection_name: str

    @classmethod
    def from_environ(cls, environment: Mapping[str, str] | None = None) -> IntegrationGateSettings:
        source = os.environ if environment is None else environment

        api_url = _canonical_http_origin(
            _required_env(source, "INTEGRATION_GATE_API_URL"),
            "INTEGRATION_GATE_API_URL",
        )
        api_token = _optional_bearer_token(
            source.get("INTEGRATION_GATE_API_TOKEN", ""),
            "INTEGRATION_GATE_API_TOKEN",
        )

        return cls(
            api_url=api_url,
            api_token=api_token,
            neo4j_uri=_canonical_neo4j_uri(_required_env(source, "NEO4J_URI"), "NEO4J_URI"),
            neo4j_user=_required_env(source, "NEO4J_USER"),
            neo4j_password=_required_env(source, "NEO4J_PASSWORD"),
            neo4j_database=_canonical_setting_identifier(
                _required_env(source, "NEO4J_DATABASE"),
                "NEO4J_DATABASE",
            ),
            milvus_host=_canonical_host(_required_env(source, "MILVUS_HOST"), "MILVUS_HOST"),
            milvus_port=_canonical_port(_required_env(source, "MILVUS_PORT"), "MILVUS_PORT"),
            milvus_collection_name=_canonical_setting_identifier(
                _required_env(source, "MILVUS_COLLECTION_NAME"),
                "MILVUS_COLLECTION_NAME",
            ),
        )

    def safe_target_identity(self) -> dict[str, str]:
        return {
            "api_host": _safe_api_host_identity(self.api_url),
            "neo4j_host": _safe_host_identity(self.neo4j_uri),
            "milvus_host": _safe_host_identity(self.milvus_host),
        }


def _safe_api_host_identity(value: str) -> str:
    parsed_value = urlsplit(value)
    host = parsed_value.hostname or ""
    port = parsed_value.port
    if port is None:
        port = 80 if parsed_value.scheme.casefold() == "http" else 443
    try:
        address = ip_address(host)
    except ValueError:
        pass
    else:
        if isinstance(address, IPv6Address):
            return f"[{address}]:{port}"
    return f"{host}:{port}"


def _safe_host_identity(value: str) -> str:
    parsed_value = urlsplit(value)
    if parsed_value.hostname:
        return parsed_value.hostname

    return urlsplit(f"//{value}").hostname or ""


def _canonical_policy_identifier(value: str, field_name: str) -> str:
    if not _POLICY_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid integration gate policy identifier: {field_name}")
    return value


def _canonical_setting_identifier(value: str, name: str) -> str:
    if not _SETTING_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid integration gate environment variable: {name}")
    return value


def _canonical_http_origin(value: str, name: str) -> str:
    parsed_value = _split_url(value, name)
    _require_url_port_is_valid(parsed_value, name)

    if (
        parsed_value.scheme not in _HTTP_SCHEMES
        or not parsed_value.hostname
        or parsed_value.username is not None
        or parsed_value.password is not None
        or parsed_value.path.rstrip("/")
        or parsed_value.query
        or parsed_value.fragment
    ):
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    return f"{parsed_value.scheme}://{parsed_value.netloc}"


def _canonical_neo4j_uri(value: str, name: str) -> str:
    parsed_value = _split_url(value, name)
    _require_url_port_is_valid(parsed_value, name)

    if (
        parsed_value.scheme not in _NEO4J_SCHEMES
        or not parsed_value.hostname
        or parsed_value.username is not None
        or parsed_value.password is not None
        or parsed_value.path.rstrip("/")
        or parsed_value.query
        or parsed_value.fragment
    ):
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    return f"{parsed_value.scheme}://{parsed_value.netloc}"


def _canonical_host(value: str, name: str) -> str:
    if "://" in value:
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    parsed_value = _split_url(f"//{value}", name)
    _require_url_port_is_valid(parsed_value, name)

    if (
        not parsed_value.hostname
        or parsed_value.username is not None
        or parsed_value.password is not None
        or parsed_value.port is not None
        or parsed_value.path
        or parsed_value.query
        or parsed_value.fragment
    ):
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    return value


def _canonical_port(value: str, name: str) -> str:
    if not value.isdecimal():
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    port = int(value)
    if not 1 <= port <= 65535 or str(port) != value:
        raise ValueError(f"Invalid integration gate environment variable: {name}")
    return value


def _optional_bearer_token(value: str, name: str) -> str | None:
    token = value.strip()
    if not token:
        return None

    if token.lower().startswith("bearer ") or not _BEARER_TOKEN_RE.fullmatch(token):
        raise ValueError(f"Invalid integration gate environment variable: {name}")
    return token


def _split_url(value: str, name: str) -> SplitResult:
    try:
        return urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"Invalid integration gate environment variable: {name}") from exc


def _require_url_port_is_valid(parsed_value: SplitResult, name: str) -> None:
    if parsed_value.netloc.endswith(":"):
        raise ValueError(f"Invalid integration gate environment variable: {name}")

    try:
        port = parsed_value.port
    except ValueError as exc:
        raise ValueError(f"Invalid integration gate environment variable: {name}") from exc

    if port == 0:
        raise ValueError(f"Invalid integration gate environment variable: {name}")


def _required_env(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required integration gate environment variable: {name}")
    return value.strip()


@dataclass(frozen=True)
class LiveCaseObservation:
    case_id: str
    strategy: str
    sources: frozenset[str]
    evidence_count: int
    fallback_used: bool
    retrieval_degraded: bool
    latency_ms: float
    total_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class LiveCaseRunResult:
    case_id: str
    observation: LiveCaseObservation | None
    checks: tuple[GateCheckResult, ...]


@dataclass(frozen=True)
class IntegrationCaseSummary:
    case_id: str
    executed: bool
    status: GateCheckStatus
    observation: LiveCaseObservation | None
    check_codes: tuple[str, ...]
