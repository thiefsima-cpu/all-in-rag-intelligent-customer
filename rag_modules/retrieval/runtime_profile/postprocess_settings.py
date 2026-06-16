"""Post-process runtime settings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .shared import _POSTPROCESS_DEFAULTS, _as_int


@dataclass
class RetrievalPostProcessSettings:
    enable_rerank: bool = bool(_POSTPROCESS_DEFAULTS.get("enable_rerank", True))
    rerank_model: str = str(_POSTPROCESS_DEFAULTS.get("rerank_model", "qwen3-vl-rerank"))
    rerank_base_url: str = str(_POSTPROCESS_DEFAULTS.get("rerank_base_url", ""))
    rerank_timeout_seconds: int = int(_POSTPROCESS_DEFAULTS.get("rerank_timeout_seconds", 20))
    preserve_graph_evidence: bool = bool(_POSTPROCESS_DEFAULTS.get("preserve_graph_evidence", True))
    graph_preservation_strategies: tuple[str, ...] = field(
        default_factory=lambda: tuple(_POSTPROCESS_DEFAULTS.get("graph_preservation_strategies", ("graph_rag", "combined")))
    )

    def __post_init__(self) -> None:
        self.enable_rerank = bool(self.enable_rerank)
        self.rerank_model = str(self.rerank_model or _POSTPROCESS_DEFAULTS.get("rerank_model", "qwen3-vl-rerank"))
        self.rerank_base_url = str(self.rerank_base_url or _POSTPROCESS_DEFAULTS.get("rerank_base_url", ""))
        self.rerank_timeout_seconds = _as_int(
            self.rerank_timeout_seconds,
            int(_POSTPROCESS_DEFAULTS.get("rerank_timeout_seconds", 20)),
            minimum=1,
        )
        self.preserve_graph_evidence = bool(self.preserve_graph_evidence)
        self.graph_preservation_strategies = tuple(
            str(item).strip()
            for item in (self.graph_preservation_strategies or ())
            if str(item).strip()
        ) or tuple(_POSTPROCESS_DEFAULTS.get("graph_preservation_strategies", ("graph_rag", "combined")))

    @classmethod
    def from_config(cls, config) -> "RetrievalPostProcessSettings":
        defaults = _POSTPROCESS_DEFAULTS
        models = config.models
        retrieval = config.retrieval
        return cls(
            enable_rerank=models.enable_rerank,
            rerank_model=models.rerank_model or defaults.get("rerank_model", "qwen3-vl-rerank"),
            rerank_base_url=models.rerank_base_url or defaults.get("rerank_base_url", ""),
            rerank_timeout_seconds=models.rerank_timeout_seconds,
            preserve_graph_evidence=retrieval.retrieval_preserve_graph_evidence,
        )

    def should_preserve_graph_evidence(self, strategy: str) -> bool:
        if not self.preserve_graph_evidence:
            return False
        return str(strategy or "") in self.graph_preservation_strategies

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enable_rerank": self.enable_rerank,
            "rerank_model": self.rerank_model,
            "rerank_base_url": self.rerank_base_url,
            "rerank_timeout_seconds": self.rerank_timeout_seconds,
            "preserve_graph_evidence": self.preserve_graph_evidence,
            "graph_preservation_strategies": list(self.graph_preservation_strategies),
        }


__all__ = ["RetrievalPostProcessSettings"]
