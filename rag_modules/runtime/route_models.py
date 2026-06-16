"""Router snapshots and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..retrieval.contracts import RetrievalRequest


@dataclass
class RouteStageSnapshot:
    latency_ms: float = 0.0
    doc_count: int = 0
    sources: Dict[str, int] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.latency_ms = round(float(self.latency_ms or 0.0), 2)
        self.doc_count = max(0, int(self.doc_count or 0))
        self.sources = {str(key): int(value) for key, value in dict(self.sources or {}).items()}
        self.details = dict(self.details or {})

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RouteStageSnapshot":
        payload = dict(data or {})
        details = {
            key: value
            for key, value in payload.items()
            if key not in {"latency_ms", "doc_count", "sources"}
        }
        return cls(
            latency_ms=payload.get("latency_ms", 0.0),
            doc_count=payload.get("doc_count", 0),
            sources=payload.get("sources") or {},
            details=details,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "latency_ms": self.latency_ms,
            "doc_count": self.doc_count,
            "sources": dict(self.sources or {}),
            **dict(self.details or {}),
        }


@dataclass
class RouteDiagnostics:
    used_fallback: bool = False
    fallback_count: int = 0
    planner_used_cache: Optional[bool] = None
    graph_doc_count: int = 0
    hybrid_doc_count: int = 0
    post_process_doc_count: int = 0
    failure_reasons: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.used_fallback = bool(self.used_fallback)
        self.fallback_count = max(0, int(self.fallback_count or 0))
        self.graph_doc_count = max(0, int(self.graph_doc_count or 0))
        self.hybrid_doc_count = max(0, int(self.hybrid_doc_count or 0))
        self.post_process_doc_count = max(0, int(self.post_process_doc_count or 0))
        self.failure_reasons = [
            str(item).strip() for item in (self.failure_reasons or []) if str(item).strip()
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RouteDiagnostics":
        payload = dict(data or {})
        return cls(
            used_fallback=payload.get("used_fallback", False),
            fallback_count=payload.get("fallback_count", 0),
            planner_used_cache=payload.get("planner_used_cache"),
            graph_doc_count=payload.get("graph_doc_count", 0),
            hybrid_doc_count=payload.get("hybrid_doc_count", 0),
            post_process_doc_count=payload.get("post_process_doc_count", 0),
            failure_reasons=payload.get("failure_reasons") or [],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "used_fallback": self.used_fallback,
            "fallback_count": self.fallback_count,
            "planner_used_cache": self.planner_used_cache,
            "graph_doc_count": self.graph_doc_count,
            "hybrid_doc_count": self.hybrid_doc_count,
            "post_process_doc_count": self.post_process_doc_count,
            "failure_reasons": list(self.failure_reasons or []),
        }


@dataclass
class RouteSnapshot:
    query: str = ""
    strategy: str = ""
    requested_top_k: int = 0
    retrieval_request: Optional[RetrievalRequest] = None
    stages: Dict[str, RouteStageSnapshot] = field(default_factory=dict)
    fallbacks: List[str] = field(default_factory=list)
    diagnostics: RouteDiagnostics = field(default_factory=RouteDiagnostics)
    total_latency_ms: float = 0.0
    final_doc_count: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.query = str(self.query or "")
        self.strategy = str(self.strategy or "")
        self.requested_top_k = max(0, int(self.requested_top_k or 0))
        if isinstance(self.retrieval_request, dict):
            self.retrieval_request = RetrievalRequest.from_dict(self.retrieval_request)
        elif self.retrieval_request and not isinstance(self.retrieval_request, RetrievalRequest):
            self.retrieval_request = RetrievalRequest.from_dict(dict(self.retrieval_request))
        self.stages = {
            str(name): stage if isinstance(stage, RouteStageSnapshot) else RouteStageSnapshot.from_dict(stage)
            for name, stage in dict(self.stages or {}).items()
        }
        self.fallbacks = [str(item).strip() for item in (self.fallbacks or []) if str(item).strip()]
        if isinstance(self.diagnostics, dict):
            self.diagnostics = RouteDiagnostics.from_dict(self.diagnostics)
        elif not isinstance(self.diagnostics, RouteDiagnostics):
            self.diagnostics = RouteDiagnostics()
        self.total_latency_ms = round(float(self.total_latency_ms or 0.0), 2)
        self.final_doc_count = max(0, int(self.final_doc_count or 0))
        self.error = str(self.error or "")
        self.refresh_diagnostics()

    @classmethod
    def from_dict(cls, data: Dict[str, Any] | None) -> "RouteSnapshot":
        payload = dict(data or {})
        return cls(
            query=payload.get("query", ""),
            strategy=payload.get("strategy", ""),
            requested_top_k=payload.get("requested_top_k", 0),
            retrieval_request=payload.get("retrieval_request"),
            stages=payload.get("stages") or {},
            fallbacks=payload.get("fallbacks") or [],
            diagnostics=payload.get("diagnostics") or {},
            total_latency_ms=payload.get("total_latency_ms", 0.0),
            final_doc_count=payload.get("final_doc_count", 0),
            error=payload.get("error", ""),
        )

    def add_stage(self, name: str, stage: RouteStageSnapshot | Dict[str, Any]) -> None:
        self.stages[str(name)] = (
            stage if isinstance(stage, RouteStageSnapshot) else RouteStageSnapshot.from_dict(stage)
        )
        self.refresh_diagnostics()

    def add_fallback(self, reason: str) -> None:
        normalized = str(reason or "").strip()
        if normalized:
            self.fallbacks.append(normalized)
            self.refresh_diagnostics()

    def finalize(self, *, total_latency_ms: float, final_doc_count: int, error: str = "") -> None:
        self.total_latency_ms = round(float(total_latency_ms or 0.0), 2)
        self.final_doc_count = max(0, int(final_doc_count or 0))
        if error:
            self.error = str(error)
        self.refresh_diagnostics()

    def refresh_diagnostics(self) -> RouteDiagnostics:
        plan_stage = self.stages.get("plan")
        graph_stage = self.stages.get("graph_rag")
        combined_stage = self.stages.get("combined")
        hybrid_candidates = [
            self.stages.get(name)
            for name in (
                "hybrid",
                "hybrid_fallback",
                "hybrid_supplement",
                "hybrid_exception_fallback",
                "combined",
            )
        ]
        post_stage = self.stages.get("post_process")

        failure_reasons: List[str] = []
        if self.error:
            failure_reasons.append("router_error")
        failure_reasons.extend(self.fallbacks)
        graph_doc_count = 0
        if graph_stage:
            graph_doc_count = graph_stage.doc_count
        elif combined_stage:
            graph_doc_count = max(
                0,
                int((combined_stage.details or {}).get("graph_doc_count") or 0),
            )
        if (graph_stage or combined_stage) and graph_doc_count == 0:
            failure_reasons.append("graph_empty")
        hybrid_doc_count = max((stage.doc_count for stage in hybrid_candidates if stage), default=0)
        if hybrid_doc_count == 0 and any(stage is not None for stage in hybrid_candidates):
            failure_reasons.append("hybrid_empty")
        if self.final_doc_count == 0 and (self.stages or self.error):
            failure_reasons.append("no_final_documents")

        self.diagnostics = RouteDiagnostics(
            used_fallback=bool(self.fallbacks),
            fallback_count=len(self.fallbacks),
            planner_used_cache=plan_stage.details.get("used_cache") if plan_stage else None,
            graph_doc_count=graph_doc_count,
            hybrid_doc_count=hybrid_doc_count,
            post_process_doc_count=post_stage.doc_count if post_stage else 0,
            failure_reasons=list(dict.fromkeys(failure_reasons)),
        )
        return self.diagnostics

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "requested_top_k": self.requested_top_k,
            "retrieval_request": self.retrieval_request.to_dict() if self.retrieval_request else {},
            "stages": {name: stage.to_dict() for name, stage in self.stages.items()},
            "fallbacks": list(self.fallbacks or []),
            "diagnostics": self.diagnostics.to_dict(),
            "total_latency_ms": self.total_latency_ms,
            "final_doc_count": self.final_doc_count,
            "error": self.error,
        }

    def has_content(self) -> bool:
        return any(
            (
                bool(self.query),
                bool(self.strategy),
                bool(self.stages),
                bool(self.fallbacks),
                self.total_latency_ms != 0.0,
                self.final_doc_count != 0,
                bool(self.error),
            )
        )
