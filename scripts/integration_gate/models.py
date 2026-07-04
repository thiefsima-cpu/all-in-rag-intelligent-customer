"""Strict policy and runtime settings for the live dependency integration gate."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.gates import GateCheckResult

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT_DIR / "eval" / "integration_gate.json"


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

        api_url = _required_env(source, "INTEGRATION_GATE_API_URL").rstrip("/")
        raw_api_token = source.get("INTEGRATION_GATE_API_TOKEN", "").strip()

        return cls(
            api_url=api_url,
            api_token=raw_api_token or None,
            neo4j_uri=_required_env(source, "NEO4J_URI"),
            neo4j_user=_required_env(source, "NEO4J_USER"),
            neo4j_password=_required_env(source, "NEO4J_PASSWORD"),
            neo4j_database=_required_env(source, "NEO4J_DATABASE"),
            milvus_host=_required_env(source, "MILVUS_HOST"),
            milvus_port=_required_env(source, "MILVUS_PORT"),
            milvus_collection_name=_required_env(source, "MILVUS_COLLECTION_NAME"),
        )

    def safe_target_identity(self) -> dict[str, str]:
        return {
            "api_host": _safe_host_identity(self.api_url),
            "neo4j_host": _safe_host_identity(self.neo4j_uri),
            "milvus_host": _safe_host_identity(self.milvus_host),
        }


def _safe_host_identity(value: str) -> str:
    parsed_value = urlsplit(value)
    if parsed_value.hostname:
        return parsed_value.hostname

    return urlsplit(f"//{value}").hostname or ""


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
