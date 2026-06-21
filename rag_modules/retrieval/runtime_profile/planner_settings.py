"""Planner runtime profile settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .shared import _PLANNER_DEFAULTS, _as_float, _as_int


@dataclass
class QueryPlannerRuntimeSettings:
    model_name: str = str(_PLANNER_DEFAULTS.get("model_name", "qwen3.7-plus"))
    cache_size: int = int(_PLANNER_DEFAULTS.get("cache_size", 128))
    timeout_seconds: int = int(_PLANNER_DEFAULTS.get("timeout_seconds", 20))
    fast_rule_planning: bool = bool(_PLANNER_DEFAULTS.get("fast_rule_planning", True))
    llm_temperature: float = float(_PLANNER_DEFAULTS.get("llm_temperature", 0.0))
    llm_max_tokens: int = int(_PLANNER_DEFAULTS.get("llm_max_tokens", 1200))

    def __post_init__(self) -> None:
        self.model_name = str(
            self.model_name or _PLANNER_DEFAULTS.get("model_name", "qwen3.7-plus")
        )
        self.cache_size = _as_int(
            self.cache_size, int(_PLANNER_DEFAULTS.get("cache_size", 128)), minimum=0
        )
        self.timeout_seconds = _as_int(
            self.timeout_seconds,
            int(_PLANNER_DEFAULTS.get("timeout_seconds", 20)),
            minimum=1,
        )
        self.fast_rule_planning = bool(self.fast_rule_planning)
        self.llm_temperature = _as_float(
            self.llm_temperature,
            float(_PLANNER_DEFAULTS.get("llm_temperature", 0.0)),
            minimum=0.0,
            maximum=2.0,
        )
        self.llm_max_tokens = _as_int(
            self.llm_max_tokens,
            int(_PLANNER_DEFAULTS.get("llm_max_tokens", 1200)),
            minimum=128,
        )

    @classmethod
    def from_config(cls, config) -> "QueryPlannerRuntimeSettings":
        defaults = _PLANNER_DEFAULTS
        models = config.models
        planner = config.query_understanding.planner
        return cls(
            model_name=models.llm_model or defaults.get("model_name", "qwen3.7-plus"),
            cache_size=planner.cache_size,
            timeout_seconds=models.llm_timeout_seconds,
            fast_rule_planning=planner.fast_rule_planning,
            llm_temperature=planner.llm_temperature,
            llm_max_tokens=planner.llm_max_tokens,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_name": self.model_name,
            "cache_size": self.cache_size,
            "timeout_seconds": self.timeout_seconds,
            "fast_rule_planning": self.fast_rule_planning,
            "llm_temperature": self.llm_temperature,
            "llm_max_tokens": self.llm_max_tokens,
        }


__all__ = ["QueryPlannerRuntimeSettings"]
