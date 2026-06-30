"""Router snapshots and diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from ..contracts import RetrievalRequest
from .json_types import JsonObject, coerce_json_float, coerce_json_int, coerce_json_object
from .policy_models import PolicySnapshot

CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN = "CANDIDATE_SOURCE_CIRCUIT_OPEN"


@dataclass
class RouteStageSnapshot:
    latency_ms: float = 0.0
    doc_count: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    details: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.latency_ms = round(float(self.latency_ms or 0.0), 2)
        self.doc_count = max(0, int(self.doc_count or 0))
        self.sources = {str(key): int(value) for key, value in dict(self.sources or {}).items()}
        self.details = coerce_json_object(self.details)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RouteStageSnapshot":
        payload = dict(data or {})
        details = {
            key: value
            for key, value in payload.items()
            if key not in {"latency_ms", "doc_count", "sources"}
        }
        return cls(
            latency_ms=coerce_json_float(payload.get("latency_ms")),
            doc_count=coerce_json_int(payload.get("doc_count")),
            sources=_int_mapping(payload.get("sources")),
            details=coerce_json_object(details),
        )

    def to_dict(self) -> JsonObject:
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
    planner_used_cache: bool | None = None
    graph_doc_count: int = 0
    hybrid_doc_count: int = 0
    post_process_doc_count: int = 0
    retrieval_degraded: bool = False
    degraded_sources: list[str] = field(default_factory=list)
    degraded_candidates: list[JsonObject] = field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.used_fallback = bool(self.used_fallback)
        self.fallback_count = max(0, int(self.fallback_count or 0))
        self.graph_doc_count = max(0, int(self.graph_doc_count or 0))
        self.hybrid_doc_count = max(0, int(self.hybrid_doc_count or 0))
        self.post_process_doc_count = max(0, int(self.post_process_doc_count or 0))
        self.retrieval_degraded = bool(self.retrieval_degraded)
        self.degraded_sources = _unique_strings(self.degraded_sources)
        self.degraded_candidates = [
            coerce_json_object(item)
            for item in (self.degraded_candidates or [])
            if isinstance(item, Mapping)
        ]
        self.circuit_breaker_triggered = bool(self.circuit_breaker_triggered)
        self.answer_impacted = bool(self.answer_impacted)
        self.failure_reasons = [
            str(item).strip() for item in (self.failure_reasons or []) if str(item).strip()
        ]

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "RouteDiagnostics":
        payload = dict(data or {})
        raw_candidates = payload.get("degraded_candidates")
        degraded_candidates = (
            [coerce_json_object(item) for item in raw_candidates]
            if isinstance(raw_candidates, list)
            else []
        )
        return cls(
            used_fallback=bool(payload.get("used_fallback", False)),
            fallback_count=coerce_json_int(payload.get("fallback_count")),
            planner_used_cache=_optional_bool(payload.get("planner_used_cache")),
            graph_doc_count=coerce_json_int(payload.get("graph_doc_count")),
            hybrid_doc_count=coerce_json_int(payload.get("hybrid_doc_count")),
            post_process_doc_count=coerce_json_int(payload.get("post_process_doc_count")),
            retrieval_degraded=bool(payload.get("retrieval_degraded", False)),
            degraded_sources=_string_list(payload.get("degraded_sources")),
            degraded_candidates=degraded_candidates,
            circuit_breaker_triggered=bool(payload.get("circuit_breaker_triggered", False)),
            answer_impacted=bool(payload.get("answer_impacted", False)),
            failure_reasons=_string_list(payload.get("failure_reasons")),
        )

    def to_dict(self) -> JsonObject:
        return {
            "used_fallback": self.used_fallback,
            "fallback_count": self.fallback_count,
            "planner_used_cache": self.planner_used_cache,
            "graph_doc_count": self.graph_doc_count,
            "hybrid_doc_count": self.hybrid_doc_count,
            "post_process_doc_count": self.post_process_doc_count,
            "retrieval_degraded": self.retrieval_degraded,
            "degraded_sources": list(self.degraded_sources or []),
            "degraded_candidates": [dict(item) for item in self.degraded_candidates],
            "circuit_breaker_triggered": self.circuit_breaker_triggered,
            "answer_impacted": self.answer_impacted,
            "failure_reasons": list(self.failure_reasons or []),
        }


@dataclass
class RouteSnapshot:
    query: str = ""
    strategy: str = ""
    requested_top_k: int = 0
    policy: PolicySnapshot = field(default_factory=PolicySnapshot)
    retrieval_request: RetrievalRequest | Mapping[str, object] | None = None
    stages: dict[str, RouteStageSnapshot] = field(default_factory=dict)
    fallbacks: list[str] = field(default_factory=list)
    diagnostics: RouteDiagnostics = field(default_factory=RouteDiagnostics)
    total_latency_ms: float = 0.0
    final_doc_count: int = 0
    error: str = ""

    def __post_init__(self) -> None:
        self.query = str(self.query or "")
        self.strategy = str(self.strategy or "")
        self.requested_top_k = max(0, int(self.requested_top_k or 0))
        if isinstance(self.policy, dict):
            self.policy = PolicySnapshot.from_dict(self.policy)
        elif not isinstance(self.policy, PolicySnapshot):
            self.policy = PolicySnapshot()
        if isinstance(self.retrieval_request, Mapping):
            self.retrieval_request = RetrievalRequest.from_dict(dict(self.retrieval_request))
        elif self.retrieval_request and not isinstance(self.retrieval_request, RetrievalRequest):
            self.retrieval_request = None
        self.stages = {
            str(name): (
                stage
                if isinstance(stage, RouteStageSnapshot)
                else RouteStageSnapshot.from_dict(stage)
            )
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
    def from_dict(cls, data: Mapping[str, object] | None) -> "RouteSnapshot":
        payload = dict(data or {})
        return cls(
            query=str(payload.get("query") or ""),
            strategy=str(payload.get("strategy") or ""),
            requested_top_k=coerce_json_int(payload.get("requested_top_k")),
            policy=PolicySnapshot.from_dict(_mapping_or_none(payload.get("policy"))),
            retrieval_request=_retrieval_request_payload(payload.get("retrieval_request")),
            stages=_stage_mapping(payload.get("stages")),
            fallbacks=_string_list(payload.get("fallbacks")),
            diagnostics=RouteDiagnostics.from_dict(_mapping_or_none(payload.get("diagnostics"))),
            total_latency_ms=coerce_json_float(payload.get("total_latency_ms")),
            final_doc_count=coerce_json_int(payload.get("final_doc_count")),
            error=str(payload.get("error") or ""),
        )

    def add_stage(self, name: str, stage: RouteStageSnapshot | Mapping[str, object]) -> None:
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

        failure_reasons: list[str] = []
        if self.error:
            failure_reasons.append("router_error")
        failure_reasons.extend(self.fallbacks)
        graph_doc_count = 0
        if graph_stage:
            graph_doc_count = graph_stage.doc_count
        elif combined_stage:
            graph_doc_count = max(
                0,
                coerce_json_int((combined_stage.details or {}).get("graph_doc_count")),
            )
        if (graph_stage or combined_stage) and graph_doc_count == 0:
            failure_reasons.append("graph_empty")
        hybrid_doc_count = max((stage.doc_count for stage in hybrid_candidates if stage), default=0)
        if hybrid_doc_count == 0 and any(stage is not None for stage in hybrid_candidates):
            failure_reasons.append("hybrid_empty")
        if self.final_doc_count == 0 and (self.stages or self.error):
            failure_reasons.append("no_final_documents")
        degradation = _summarize_stage_degradation(self.stages)
        if degradation["retrieval_degraded"]:
            failure_reasons.append("retrieval_degraded")
        if degradation["circuit_breaker_triggered"]:
            failure_reasons.append("circuit_breaker_open")
        answer_impacted = bool(self.error) or (
            self.final_doc_count == 0 and bool(self.stages or self.error)
        )

        self.diagnostics = RouteDiagnostics(
            used_fallback=bool(self.fallbacks),
            fallback_count=len(self.fallbacks),
            planner_used_cache=(
                _optional_bool(plan_stage.details.get("used_cache")) if plan_stage else None
            ),
            graph_doc_count=graph_doc_count,
            hybrid_doc_count=hybrid_doc_count,
            post_process_doc_count=post_stage.doc_count if post_stage else 0,
            retrieval_degraded=bool(degradation["retrieval_degraded"]),
            degraded_sources=_unique_strings(_list_or_empty(degradation.get("degraded_sources"))),
            degraded_candidates=[
                coerce_json_object(item)
                for item in _list_or_empty(degradation.get("degraded_candidates"))
            ],
            circuit_breaker_triggered=bool(degradation["circuit_breaker_triggered"]),
            answer_impacted=answer_impacted,
            failure_reasons=list(dict.fromkeys(failure_reasons)),
        )
        return self.diagnostics

    def to_dict(self) -> JsonObject:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "requested_top_k": self.requested_top_k,
            "policy": self.policy.to_dict(),
            "retrieval_request": (
                coerce_json_object(self.retrieval_request.to_dict())
                if isinstance(self.retrieval_request, RetrievalRequest)
                else {}
            ),
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
                self.policy.is_recorded(),
                bool(self.stages),
                bool(self.fallbacks),
                self.total_latency_ms != 0.0,
                self.final_doc_count != 0,
                bool(self.error),
            )
        )


def _unique_strings(values: Iterable[object]) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _summarize_stage_degradation(
    stages: dict[str, RouteStageSnapshot],
) -> JsonObject:
    degraded_candidates: list[JsonObject] = []
    degraded_sources: list[str] = []
    retrieval_degraded = False
    circuit_breaker_triggered = False
    for stage in (stages or {}).values():
        details = dict(stage.details or {})
        if details.get("retrieval_degraded"):
            retrieval_degraded = True
        degraded_sources.extend(_unique_strings(_list_or_empty(details.get("degraded_sources"))))
        for candidate in _list_or_empty(details.get("degraded_candidates")):
            item = coerce_json_object(candidate)
            if not item:
                continue
            degraded_candidates.append(item)
            degraded_sources.append(str(item.get("source") or ""))
            if (
                item.get("error_code") == CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN
                or item.get("reason") == "circuit_open"
                or item.get("circuit_state") == "open"
            ):
                circuit_breaker_triggered = True
        if details.get("circuit_breaker_triggered"):
            circuit_breaker_triggered = True
    if degraded_candidates or degraded_sources:
        retrieval_degraded = True
    return coerce_json_object(
        {
            "retrieval_degraded": retrieval_degraded,
            "degraded_sources": _unique_strings(degraded_sources),
            "degraded_candidates": degraded_candidates,
            "circuit_breaker_triggered": circuit_breaker_triggered,
        }
    )


def _int_mapping(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): coerce_json_int(item) for key, item in value.items()}


def _list_or_empty(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [str(item).strip() for item in _list_or_empty(value) if str(item).strip()]


def _optional_bool(value: object) -> bool | None:
    return None if value is None else bool(value)


def _mapping_or_none(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _retrieval_request_payload(value: object) -> RetrievalRequest | Mapping[str, object] | None:
    if isinstance(value, RetrievalRequest):
        return value
    if isinstance(value, Mapping):
        return value
    return None


def _stage_mapping(value: object) -> dict[str, RouteStageSnapshot]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(name): (
            stage
            if isinstance(stage, RouteStageSnapshot)
            else RouteStageSnapshot.from_dict(_mapping_or_none(stage))
        )
        for name, stage in value.items()
    }
