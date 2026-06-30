"""Generation snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from .json_types import JsonObject, coerce_json_float, coerce_json_int
from .policy_models import PolicySnapshot


class GenerationMode(str, Enum):
    DIRECT = "direct"
    TWO_STAGE = "two_stage"
    EMPTY = "empty"


def normalize_generation_mode(
    value: GenerationMode | str | None,
    *,
    allow_unknown: bool = False,
) -> GenerationMode | str:
    if isinstance(value, GenerationMode):
        return value
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return GenerationMode(text)
    except ValueError:
        if allow_unknown:
            return text
        supported = ", ".join(mode.value for mode in GenerationMode)
        raise ValueError(f"generation mode must be one of: {supported}") from None


def generation_mode_value(value: GenerationMode | str) -> str:
    if isinstance(value, GenerationMode):
        return value.value
    return str(value or "")


@dataclass
class GenerationSnapshot:
    status: str = ""
    mode: GenerationMode | str = ""
    policy: PolicySnapshot = field(default_factory=PolicySnapshot)
    decision_reason: str = ""
    total_evidence_items: int = 0
    selected_evidence_items: int = 0
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    failure_code: str = ""
    total_latency_ms: float = 0.0
    provider_latency_ms: float = 0.0
    request_retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""

    def __post_init__(self) -> None:
        self.mode = normalize_generation_mode(self.mode, allow_unknown=True)
        if isinstance(self.policy, dict):
            self.policy = PolicySnapshot.from_dict(self.policy)
        elif not isinstance(self.policy, PolicySnapshot):
            self.policy = PolicySnapshot()

    @property
    def mode_value(self) -> str:
        return generation_mode_value(self.mode)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "GenerationSnapshot":
        payload = dict(data or {})
        return cls(
            status=str(payload.get("status") or ""),
            mode=str(payload.get("mode") or ""),
            policy=PolicySnapshot.from_dict(_mapping_or_none(payload.get("policy"))),
            decision_reason=str(payload.get("decision_reason") or ""),
            total_evidence_items=coerce_json_int(payload.get("total_evidence_items")),
            selected_evidence_items=coerce_json_int(payload.get("selected_evidence_items")),
            plan_latency_ms=coerce_json_float(payload.get("plan_latency_ms")),
            compose_latency_ms=coerce_json_float(payload.get("compose_latency_ms")),
            direct_latency_ms=coerce_json_float(payload.get("direct_latency_ms")),
            fallback_used=bool(payload.get("fallback_used")),
            fallback_reason=str(payload.get("fallback_reason") or ""),
            failure_code=str(payload.get("failure_code") or ""),
            total_latency_ms=coerce_json_float(payload.get("total_latency_ms")),
            provider_latency_ms=coerce_json_float(payload.get("provider_latency_ms")),
            request_retries=coerce_json_int(payload.get("request_retries")),
            prompt_tokens=coerce_json_int(payload.get("prompt_tokens")),
            completion_tokens=coerce_json_int(payload.get("completion_tokens")),
            total_tokens=coerce_json_int(payload.get("total_tokens")),
            estimated_cost_usd=coerce_json_float(payload.get("estimated_cost_usd")),
            token_usage_source=str(payload.get("token_usage_source") or ""),
        )

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "mode": self.mode_value,
            "policy": self.policy.to_dict(),
            "decision_reason": self.decision_reason,
            "total_evidence_items": self.total_evidence_items,
            "selected_evidence_items": self.selected_evidence_items,
            "plan_latency_ms": self.plan_latency_ms,
            "compose_latency_ms": self.compose_latency_ms,
            "direct_latency_ms": self.direct_latency_ms,
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "failure_code": self.failure_code,
            "total_latency_ms": self.total_latency_ms,
            "provider_latency_ms": self.provider_latency_ms,
            "request_retries": self.request_retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
            "token_usage_source": self.token_usage_source,
        }

    def is_recorded(self) -> bool:
        return any(
            (
                bool(self.status),
                bool(self.mode),
                self.policy.is_recorded(),
                bool(self.decision_reason),
                self.total_evidence_items != 0,
                self.selected_evidence_items != 0,
                self.plan_latency_ms != 0.0,
                self.compose_latency_ms != 0.0,
                self.direct_latency_ms != 0.0,
                bool(self.fallback_used),
                bool(self.fallback_reason),
                bool(self.failure_code),
                self.total_latency_ms != 0.0,
                self.provider_latency_ms != 0.0,
                self.request_retries != 0,
                self.prompt_tokens != 0,
                self.completion_tokens != 0,
                self.total_tokens != 0,
                self.estimated_cost_usd != 0.0,
                bool(self.token_usage_source),
            )
        )


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
