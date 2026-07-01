"""Shared models for answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from ..runtime.generation_models import (
    GenerationMode,
    generation_mode_value,
    normalize_generation_mode,
)


@dataclass
class AnswerPlan:
    answer_type: str = "direct_answer"
    reasoning_mode: str = "grounded"
    outline: List[str] = field(default_factory=list)
    key_points: List[dict] = field(default_factory=list)
    cautions: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "AnswerPlan":
        return cls(
            answer_type=str(data.get("answer_type") or "direct_answer"),
            reasoning_mode=str(data.get("reasoning_mode") or "grounded"),
            outline=[str(item).strip() for item in data.get("outline", []) if str(item).strip()],
            key_points=[
                {
                    "title": str(item.get("title") or "").strip(),
                    "claim": str(item.get("claim") or "").strip(),
                    "citations": [
                        str(c).strip() for c in item.get("citations", []) if str(c).strip()
                    ],
                    "use_graph_evidence": bool(item.get("use_graph_evidence")),
                }
                for item in data.get("key_points", [])
                if isinstance(item, dict) and (item.get("title") or item.get("claim"))
            ],
            cautions=[str(item).strip() for item in data.get("cautions", []) if str(item).strip()],
            missing_information=[
                str(item).strip()
                for item in data.get("missing_information", [])
                if str(item).strip()
            ],
        )

    def to_dict(self) -> dict:
        return {
            "answer_type": self.answer_type,
            "reasoning_mode": self.reasoning_mode,
            "outline": self.outline,
            "key_points": self.key_points,
            "cautions": self.cautions,
            "missing_information": self.missing_information,
        }


@dataclass
class GenerationDecision:
    mode: GenerationMode | str
    reason: str
    evidence_limit: int

    def __post_init__(self) -> None:
        self.mode = normalize_generation_mode(self.mode)
        self.reason = str(self.reason or "")
        self.evidence_limit = max(1, int(self.evidence_limit or 1))

    @property
    def mode_value(self) -> str:
        return generation_mode_value(self.mode)


class GenerationPlannerMode(str, Enum):
    RULE = "rule"
    HYBRID = "hybrid"
    LLM = "llm"


def _generation_planner_mode(value: "GenerationPlannerMode | str") -> GenerationPlannerMode:
    if isinstance(value, GenerationPlannerMode):
        return value
    normalized = str(value or GenerationPlannerMode.RULE.value).strip().lower()
    try:
        return GenerationPlannerMode(normalized)
    except ValueError:
        supported = ", ".join(mode.value for mode in GenerationPlannerMode)
        raise ValueError(f"planner_mode must be one of: {supported}") from None


@dataclass
class RenderedPrompt:
    prompt_type: str
    question: str
    text: str
    evidence_citations: List[str] = field(default_factory=list)
    evidence_item_count: int = 0
    plan: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.prompt_type = str(self.prompt_type or "").strip()
        self.question = str(self.question or "")
        self.text = str(self.text or "")
        self.evidence_citations = [
            str(item).strip() for item in (self.evidence_citations or []) if str(item).strip()
        ]
        self.evidence_item_count = max(0, int(self.evidence_item_count or 0))
        self.plan = dict(self.plan or {})
        self.metadata = dict(self.metadata or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prompt_type": self.prompt_type,
            "question": self.question,
            "text": self.text,
            "evidence_citations": list(self.evidence_citations or []),
            "evidence_item_count": self.evidence_item_count,
            "plan": dict(self.plan or {}),
            "metadata": dict(self.metadata or {}),
        }


@dataclass
class GenerationTrace:
    mode: GenerationMode | str
    decision_reason: str
    total_evidence_items: int
    selected_evidence_items: int
    status: str = ""
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
        self.mode = normalize_generation_mode(self.mode)

    @property
    def mode_value(self) -> str:
        return generation_mode_value(self.mode)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode_value,
            "decision_reason": self.decision_reason,
            "total_evidence_items": self.total_evidence_items,
            "selected_evidence_items": self.selected_evidence_items,
            "plan_latency_ms": round(self.plan_latency_ms, 2),
            "compose_latency_ms": round(self.compose_latency_ms, 2),
            "direct_latency_ms": round(self.direct_latency_ms, 2),
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "failure_code": self.failure_code,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "provider_latency_ms": round(self.provider_latency_ms, 2),
            "request_retries": self.request_retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 8),
            "token_usage_source": self.token_usage_source,
        }


@dataclass
class GenerationSettings:
    model_name: str = "qwen3.7-plus"
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout_seconds: int = 45
    stream_timeout_seconds: int = 45
    latency_budget_seconds: int = 24
    planner_max_tokens: int = 600
    composer_max_tokens: int = 1100
    planner_temperature: float = 0.0
    planner_mode: GenerationPlannerMode | str = GenerationPlannerMode.RULE
    max_retries: int = 1
    request_retries: int = 1
    stream_retries: int = 1
    direct_max_tokens: int = 700
    enable_two_stage: bool = True
    two_stage_complexity_threshold: float = 0.68
    two_stage_relationship_threshold: float = 0.58
    direct_max_evidence_items: int = 2
    two_stage_max_evidence_items: int = 3
    plan_max_evidence_items: int = 2
    max_graph_paths_per_item: int = 1
    max_evidence_units_per_item: int = 4
    include_document_evidence: bool = False
    compose_include_content: bool = False
    fallback_on_timeout: bool = False
    input_cost_per_million_tokens: float = 0.0
    output_cost_per_million_tokens: float = 0.0

    def __post_init__(self) -> None:
        self.temperature = float(self.temperature)
        self.max_tokens = max(256, int(self.max_tokens or 2048))
        self.timeout_seconds = max(1, int(self.timeout_seconds or 45))
        self.stream_timeout_seconds = max(1, int(self.stream_timeout_seconds or 45))
        self.latency_budget_seconds = max(1, int(self.latency_budget_seconds or 24))
        self.planner_max_tokens = max(256, int(self.planner_max_tokens or 900))
        self.composer_max_tokens = max(
            256, int(self.composer_max_tokens or self.max_tokens or 1400)
        )
        self.planner_temperature = float(self.planner_temperature)
        self.planner_mode = _generation_planner_mode(self.planner_mode)
        self.max_retries = max(1, int(self.max_retries or 1))
        self.request_retries = max(1, int(self.request_retries or 1))
        self.stream_retries = max(1, int(self.stream_retries or 1))
        self.direct_max_tokens = max(256, int(self.direct_max_tokens or 900))
        self.enable_two_stage = bool(self.enable_two_stage)
        self.two_stage_complexity_threshold = float(self.two_stage_complexity_threshold)
        self.two_stage_relationship_threshold = float(self.two_stage_relationship_threshold)
        self.direct_max_evidence_items = max(1, int(self.direct_max_evidence_items or 2))
        self.two_stage_max_evidence_items = max(1, int(self.two_stage_max_evidence_items or 3))
        self.plan_max_evidence_items = max(1, int(self.plan_max_evidence_items or 3))
        self.max_graph_paths_per_item = max(0, int(self.max_graph_paths_per_item or 2))
        self.max_evidence_units_per_item = max(1, int(self.max_evidence_units_per_item or 6))
        self.include_document_evidence = bool(self.include_document_evidence)
        self.compose_include_content = bool(self.compose_include_content)
        self.fallback_on_timeout = bool(self.fallback_on_timeout)
        self.input_cost_per_million_tokens = max(
            0.0,
            float(self.input_cost_per_million_tokens or 0.0),
        )
        self.output_cost_per_million_tokens = max(
            0.0,
            float(self.output_cost_per_million_tokens or 0.0),
        )
