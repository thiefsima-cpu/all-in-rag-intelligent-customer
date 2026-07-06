"""Post-process runtime settings."""

from __future__ import annotations

from dataclasses import dataclass

from .shared import _as_int


@dataclass
class RetrievalPostProcessSettings:
    enable_rerank: bool
    rerank_model: str
    rerank_base_url: str
    rerank_timeout_seconds: int
    preserve_graph_evidence: bool
    graph_preservation_strategies: tuple[str, ...]

    def __post_init__(self) -> None:
        self.enable_rerank = bool(self.enable_rerank)
        self.rerank_model = str(self.rerank_model or "")
        self.rerank_base_url = str(self.rerank_base_url or "")
        self.rerank_timeout_seconds = _as_int(
            self.rerank_timeout_seconds,
            1,
            minimum=1,
        )
        self.preserve_graph_evidence = bool(self.preserve_graph_evidence)
        self.graph_preservation_strategies = tuple(
            str(item).strip()
            for item in (self.graph_preservation_strategies or ())
            if str(item).strip()
        )

    @classmethod
    def from_config(cls, config) -> "RetrievalPostProcessSettings":
        models = config.models
        retrieval = config.retrieval
        return cls(
            enable_rerank=models.enable_rerank,
            rerank_model=models.rerank_model,
            rerank_base_url=models.rerank_base_url,
            rerank_timeout_seconds=models.rerank_timeout_seconds,
            preserve_graph_evidence=retrieval.retrieval_preserve_graph_evidence,
            graph_preservation_strategies=tuple(retrieval.retrieval_graph_preservation_strategies),
        )

    def should_preserve_graph_evidence(self, strategy: str) -> bool:
        if not self.preserve_graph_evidence:
            return False
        return str(strategy or "") in self.graph_preservation_strategies

    def to_dict(self) -> dict[str, object]:
        return {
            "enable_rerank": self.enable_rerank,
            "rerank_model": self.rerank_model,
            "rerank_base_url": self.rerank_base_url,
            "rerank_timeout_seconds": self.rerank_timeout_seconds,
            "preserve_graph_evidence": self.preserve_graph_evidence,
            "graph_preservation_strategies": list(self.graph_preservation_strategies),
        }


__all__ = ["RetrievalPostProcessSettings"]
