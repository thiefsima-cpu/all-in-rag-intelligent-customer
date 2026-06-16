"""Shared models for answer generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
                    "citations": [str(c).strip() for c in item.get("citations", []) if str(c).strip()],
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
    mode: str
    reason: str
    evidence_limit: int


@dataclass
class GenerationTrace:
    mode: str
    decision_reason: str
    total_evidence_items: int
    selected_evidence_items: int
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    total_latency_ms: float = 0.0
    request_retries: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "decision_reason": self.decision_reason,
            "total_evidence_items": self.total_evidence_items,
            "selected_evidence_items": self.selected_evidence_items,
            "plan_latency_ms": round(self.plan_latency_ms, 2),
            "compose_latency_ms": round(self.compose_latency_ms, 2),
            "direct_latency_ms": round(self.direct_latency_ms, 2),
            "fallback_used": self.fallback_used,
            "fallback_reason": self.fallback_reason,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "request_retries": self.request_retries,
        }


@dataclass
class GenerationSettings:
    model_name: str = "qwen3.7-plus"
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout_seconds: int = 45
    stream_timeout_seconds: int = 45
    planner_max_tokens: int = 600
    composer_max_tokens: int = 1100
    planner_temperature: float = 0.0
    planner_mode: str = "rule"
    max_retries: int = 2
    request_retries: int = 1
    stream_retries: int = 2
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

    def __post_init__(self) -> None:
        self.temperature = float(self.temperature)
        self.max_tokens = max(256, int(self.max_tokens or 2048))
        self.timeout_seconds = max(1, int(self.timeout_seconds or 45))
        self.stream_timeout_seconds = max(1, int(self.stream_timeout_seconds or 45))
        self.planner_max_tokens = max(256, int(self.planner_max_tokens or 900))
        self.composer_max_tokens = max(256, int(self.composer_max_tokens or self.max_tokens or 1400))
        self.planner_temperature = float(self.planner_temperature)
        self.planner_mode = str(self.planner_mode or "rule").strip().lower()
        self.max_retries = max(1, int(self.max_retries or 2))
        self.request_retries = max(1, int(self.request_retries or 1))
        self.stream_retries = max(1, int(self.stream_retries or 2))
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
