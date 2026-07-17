"""Strict policy and settings models for the live quality gate."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from enum import StrEnum
from ipaddress import IPv6Address, ip_address
from pathlib import Path
from typing import Annotated, Literal, Mapping, Self
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT_DIR / "eval" / "live_quality_gate.json"
_HTTP_SCHEMES = frozenset({"http", "https"})
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_BEARER_TOKEN_RE = re.compile(r"^[A-Za-z0-9._~+/-]+={0,}$")
PositiveInt = Annotated[int, Field(ge=1)]
RelevanceGrade = Annotated[float, Field(ge=0)]


class StrictLiveQualityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class LiveQualityResponseMode(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    NO_EVIDENCE = "no_evidence"
    CLARIFICATION = "clarification"
    CONSTRAINT_CONFLICT = "constraint_conflict"

    @property
    def is_abstention(self) -> bool:
        return self is not LiveQualityResponseMode.GROUNDED_ANSWER


_RESPONSE_MODE_VALUES = frozenset(mode.value for mode in LiveQualityResponseMode)


class LiveQualityTimeouts(StrictLiveQualityModel):
    request_seconds: float = Field(gt=0)
    judge_seconds: float = Field(gt=0)


class LiveQualityThresholds(StrictLiveQualityModel):
    minimum_case_count: int = Field(ge=1)
    minimum_pass_rate: float = Field(ge=0, le=1)
    minimum_deterministic_pass_rate: float = Field(ge=0, le=1)
    minimum_judge_pass_rate: float = Field(ge=0, le=1)
    minimum_recall_at_k: float = Field(ge=0, le=1)
    minimum_mrr: float = Field(ge=0, le=1)
    minimum_ndcg_at_k: float = Field(ge=0, le=1)
    maximum_fallback_rate: float = Field(ge=0, le=1)
    maximum_retrieval_degradation_rate: float = Field(ge=0, le=1)
    maximum_p95_latency_ms: float = Field(gt=0)
    maximum_estimated_cost_usd: float = Field(ge=0)


class SliceThreshold(StrictLiveQualityModel):
    minimum_case_count: int = Field(ge=1)
    minimum_pass_rate: float = Field(ge=0, le=1)


class RequiredSliceCoverage(StrictLiveQualityModel):
    risk_tags: dict[str, PositiveInt] = Field(default_factory=dict)
    query_types: dict[str, PositiveInt] = Field(default_factory=dict)
    cuisines: dict[str, PositiveInt] = Field(default_factory=dict)
    constraint_types: dict[str, PositiveInt] = Field(default_factory=dict)
    response_modes: dict[str, PositiveInt] = Field(default_factory=dict)

    @field_validator("*")
    @classmethod
    def validate_labels(cls, value: dict[str, PositiveInt]) -> dict[str, PositiveInt]:
        for key in value:
            _canonical_identifier(key, "slice coverage label")
        return value

    @field_validator("response_modes")
    @classmethod
    def validate_response_modes(cls, value: dict[str, PositiveInt]) -> dict[str, PositiveInt]:
        _validate_response_mode_keys(value, "slice coverage response mode")
        return value


class LiveQualitySliceThresholds(StrictLiveQualityModel):
    risk_tags: dict[str, SliceThreshold] = Field(default_factory=dict)
    query_types: dict[str, SliceThreshold] = Field(default_factory=dict)
    cuisines: dict[str, SliceThreshold] = Field(default_factory=dict)
    constraint_types: dict[str, SliceThreshold] = Field(default_factory=dict)
    response_modes: dict[str, SliceThreshold] = Field(default_factory=dict)
    strategies: dict[str, SliceThreshold] = Field(default_factory=dict)

    @field_validator("*")
    @classmethod
    def validate_labels(cls, value: dict[str, SliceThreshold]) -> dict[str, SliceThreshold]:
        for key in value:
            _canonical_identifier(key, "slice threshold label")
        return value

    @field_validator("response_modes")
    @classmethod
    def validate_response_modes(cls, value: dict[str, SliceThreshold]) -> dict[str, SliceThreshold]:
        _validate_response_mode_keys(value, "slice threshold response mode")
        return value


class LiveQualityJudgePolicy(StrictLiveQualityModel):
    required: bool
    score_names: list[str] = Field(min_length=1)
    minimum_score: float = Field(ge=0, le=1)

    @field_validator("score_names")
    @classmethod
    def validate_score_names(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        for value in values:
            _canonical_identifier(value, "judge score name")
            if value in seen:
                raise ValueError("duplicate judge score name")
            seen.add(value)
        return values


class ManualReviewPolicy(StrictLiveQualityModel):
    owner: str = Field(min_length=1)
    sample: bool

    @field_validator("owner")
    @classmethod
    def reject_blank_owner(cls, value: str) -> str:
        return _require_non_blank(value, "manual review owner")


class LiveQualityCasePolicy(StrictLiveQualityModel):
    case_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    query_type: str = Field(min_length=1)
    cuisine: str = Field(min_length=1)
    constraint_types: list[str] = Field(default_factory=list)
    risk_tags: list[str] = Field(default_factory=list)
    expected_response_mode: LiveQualityResponseMode
    allowed_strategies: list[str] = Field(min_length=1)
    required_sources: list[str] = Field(default_factory=list)
    relevant_recipes: dict[str, RelevanceGrade] = Field(default_factory=dict)
    must_include_facts: list[str] = Field(default_factory=list)
    must_not_claim: list[str] = Field(default_factory=list)
    judge_rubric: dict[str, str] = Field(min_length=1)
    manual_review: ManualReviewPolicy

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_expected_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            legacy = sorted(
                str(key)
                for key in value
                if str(key).startswith("expected_") and key != "expected_response_mode"
            )
            if legacy:
                raise ValueError(f"legacy fields are not allowed: {legacy}")
        return value

    @field_validator("expected_response_mode", mode="before")
    @classmethod
    def validate_response_mode(cls, value: object) -> object:
        if isinstance(value, LiveQualityResponseMode):
            return value
        if isinstance(value, str):
            return LiveQualityResponseMode(value)
        return value

    @field_validator("case_id", "query_type", "cuisine")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _canonical_identifier(value, "case identifier")

    @field_validator("query")
    @classmethod
    def reject_blank_query(cls, value: str) -> str:
        return _require_non_blank(value, "case query")

    @field_validator("constraint_types", "risk_tags", "allowed_strategies", "required_sources")
    @classmethod
    def validate_identifier_list(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        for value in values:
            _canonical_identifier(value, "case label")
            if value in seen:
                raise ValueError("duplicate case label")
            seen.add(value)
        return values

    @field_validator("must_include_facts", "must_not_claim")
    @classmethod
    def validate_expectation_list(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        for value in values:
            _require_non_blank(value, "case expectation")
            if value in seen:
                raise ValueError("duplicate case expectation")
            seen.add(value)
        return values

    @field_validator("relevant_recipes")
    @classmethod
    def reject_blank_mapping_entries(cls, value: dict[str, float]) -> dict[str, float]:
        for key in value:
            _require_non_blank(key, "case mapping key")
        return value

    @field_validator("judge_rubric")
    @classmethod
    def validate_judge_rubric(cls, value: dict[str, str]) -> dict[str, str]:
        for key, prose in value.items():
            _canonical_identifier(key, "judge rubric score name")
            _require_non_blank(prose, "judge rubric prose")
        return value

    @model_validator(mode="after")
    def validate_response_mode_relevance(self) -> Self:
        has_positive_relevance = any(grade > 0 for grade in self.relevant_recipes.values())
        if self.expected_response_mode is LiveQualityResponseMode.GROUNDED_ANSWER:
            if not has_positive_relevance:
                raise ValueError("grounded_answer cases require positive relevance")
        elif has_positive_relevance:
            raise ValueError("non-grounded cases must not define relevance")
        if not self.must_include_facts and not self.must_not_claim:
            raise ValueError("cases require must_include_facts or must_not_claim")
        return self


class LiveQualityGatePolicy(StrictLiveQualityModel):
    schema_version: Literal[1]
    top_k: int = Field(ge=1)
    timeouts: LiveQualityTimeouts
    judge: LiveQualityJudgePolicy
    thresholds: LiveQualityThresholds
    required_slice_coverage: RequiredSliceCoverage
    slice_thresholds: LiveQualitySliceThresholds
    cases: list[LiveQualityCasePolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_duplicate_case_ids(self) -> Self:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for case in self.cases:
            if case.case_id in seen:
                duplicates.add(case.case_id)
            seen.add(case.case_id)
        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"Duplicate live quality case IDs: {joined}")
        return self

    @model_validator(mode="after")
    def validate_case_judge_rubrics(self) -> Self:
        expected_scores = set(self.judge.score_names)
        for case in self.cases:
            actual_scores = set(case.judge_rubric)
            missing = sorted(expected_scores - actual_scores)
            extra = sorted(actual_scores - expected_scores)
            if missing or extra:
                raise ValueError(
                    "Live quality judge rubric mismatch for "
                    f"{case.case_id}: missing={missing}; extra={extra}"
                )
        return self


@dataclass(frozen=True)
class JudgeSettings:
    api_url: str = field(repr=False)
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float
    enable_thinking: bool | None = None


@dataclass(frozen=True)
class LiveQualityGateSettings:
    api_url: str = field(repr=False)
    api_token: str | None = field(repr=False)
    judge: JudgeSettings

    @classmethod
    def from_environ(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> LiveQualityGateSettings:
        env = os.environ if environment is None else environment
        judge = JudgeSettings(
            api_url=_canonical_http_url(
                _required_env(env, "LIVE_QUALITY_JUDGE_API_URL"),
                "LIVE_QUALITY_JUDGE_API_URL",
            ),
            api_key=_required_env(env, "LIVE_QUALITY_JUDGE_API_KEY"),
            model=_canonical_label(
                _required_env(env, "LIVE_QUALITY_JUDGE_MODEL"),
                "LIVE_QUALITY_JUDGE_MODEL",
            ),
            timeout_seconds=_optional_positive_float(
                env.get("LIVE_QUALITY_JUDGE_TIMEOUT_SECONDS"),
                default=45.0,
                name="LIVE_QUALITY_JUDGE_TIMEOUT_SECONDS",
            ),
            enable_thinking=_optional_bool(
                env.get("LIVE_QUALITY_JUDGE_ENABLE_THINKING"),
                name="LIVE_QUALITY_JUDGE_ENABLE_THINKING",
            ),
        )

        return cls(
            api_url=_canonical_http_url(
                _required_env(env, "LIVE_QUALITY_API_URL"),
                "LIVE_QUALITY_API_URL",
            ),
            api_token=_optional_bearer_token(env.get("LIVE_QUALITY_API_TOKEN")),
            judge=judge,
        )

    def safe_target_identity(self) -> dict[str, str]:
        return {
            "api_host": _safe_host_identity(self.api_url),
            "judge_host": _safe_host_identity(self.judge.api_url),
        }


def load_live_quality_policy(path: str | Path = DEFAULT_POLICY_PATH) -> LiveQualityGatePolicy:
    policy_path = Path(path)
    with policy_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return LiveQualityGatePolicy.model_validate(payload)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"Blank live quality value: {field_name}")
    return value


def _canonical_identifier(value: str, field_name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"Invalid live quality identifier: {field_name}")
    return value


def _validate_response_mode_keys(value: Mapping[str, object], field_name: str) -> None:
    invalid = sorted(key for key in value if key not in _RESPONSE_MODE_VALUES)
    if invalid:
        raise ValueError(f"Invalid live quality response mode: {field_name}={invalid}")


def _canonical_label(value: str, name: str) -> str:
    if not _LABEL_RE.fullmatch(value):
        raise ValueError(f"Invalid live quality environment variable: {name}")
    return value


def _required_env(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Missing required live quality environment variable: {name}")
    return value.strip()


def _optional_bearer_token(value: str | None) -> str | None:
    if value is None:
        return None
    token = value.strip()
    if not token:
        return None
    if token.lower().startswith("bearer ") or not _BEARER_TOKEN_RE.fullmatch(token):
        raise ValueError("Invalid live quality environment variable: LIVE_QUALITY_API_TOKEN")
    return token


def _optional_positive_float(value: str | None, *, default: float, name: str) -> float:
    if value is None:
        return default
    trimmed = value.strip()
    if not trimmed:
        raise ValueError(f"Invalid live quality environment variable: {name}")
    try:
        parsed = float(trimmed)
    except ValueError as exc:
        raise ValueError(f"Invalid live quality environment variable: {name}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"Invalid live quality environment variable: {name}")
    return parsed


def _optional_bool(value: str | None, *, name: str) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"Invalid live quality environment variable: {name}")


def _canonical_http_url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in _HTTP_SCHEMES
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"Invalid live quality environment variable: {name}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid live quality environment variable: {name}") from exc
    if port == 0 or parsed.netloc.endswith(":"):
        raise ValueError(f"Invalid live quality environment variable: {name}")
    canonical_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, canonical_path, parsed.query, parsed.fragment))


def _safe_host_identity(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port is not None:
        try:
            address = ip_address(host)
        except ValueError:
            pass
        else:
            if isinstance(address, IPv6Address):
                return f"[{address}]:{parsed.port}"
        return f"{host}:{parsed.port}"
    return host
