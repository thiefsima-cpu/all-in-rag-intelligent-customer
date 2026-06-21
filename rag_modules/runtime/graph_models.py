"""Graph retrieval snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..retrieval.contracts import RetrievalRequest


@dataclass
class GraphTraceEventSnapshot:
    name: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = str(self.name or "")
        self.status = str(self.status or "ok")
        self.latency_ms = round(float(self.latency_ms or 0.0), 2)
        self.details = dict(self.details or {})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "GraphTraceEventSnapshot":
        payload = dict(data or {})
        return cls(
            name=payload.get("name", ""),
            status=payload.get("status", "ok"),
            latency_ms=payload.get("latency_ms", 0.0),
            details=payload.get("details") or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "details": dict(self.details or {}),
        }


@dataclass
class GraphRetrievalSnapshot:
    query: str = ""
    strategy: str = "graph_rag"
    requested_top_k: int = 0
    retrieval_request: Optional[RetrievalRequest] = None
    query_type: str = ""
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    sub_questions: List[str] = field(default_factory=list)
    path_count: int = 0
    subgraph_count: int = 0
    reasoning_patterns: List[str] = field(default_factory=list)
    reasoning_chain_count: int = 0
    evidence_unit_count: int = 0
    doc_count: int = 0
    retrieval_plan: Dict[str, Any] = field(default_factory=dict)
    events: List[GraphTraceEventSnapshot] = field(default_factory=list)
    total_latency_ms: float = 0.0
    error: str = ""

    def __post_init__(self) -> None:
        self.query = str(self.query or "")
        self.strategy = str(self.strategy or "graph_rag")
        self.requested_top_k = max(0, int(self.requested_top_k or 0))
        if isinstance(self.retrieval_request, dict):
            self.retrieval_request = RetrievalRequest.from_dict(self.retrieval_request)
        elif self.retrieval_request and not isinstance(self.retrieval_request, RetrievalRequest):
            self.retrieval_request = RetrievalRequest.from_dict(dict(self.retrieval_request))
        self.query_type = str(self.query_type or "")
        self.source_entities = [
            str(item).strip() for item in (self.source_entities or []) if str(item).strip()
        ]
        self.target_entities = [
            str(item).strip() for item in (self.target_entities or []) if str(item).strip()
        ]
        self.relation_types = [
            str(item).strip() for item in (self.relation_types or []) if str(item).strip()
        ]
        self.sub_questions = [
            str(item).strip() for item in (self.sub_questions or []) if str(item).strip()
        ]
        self.path_count = max(0, int(self.path_count or 0))
        self.subgraph_count = max(0, int(self.subgraph_count or 0))
        self.reasoning_patterns = [
            str(item).strip() for item in (self.reasoning_patterns or []) if str(item).strip()
        ]
        self.reasoning_chain_count = max(0, int(self.reasoning_chain_count or 0))
        self.evidence_unit_count = max(0, int(self.evidence_unit_count or 0))
        self.doc_count = max(0, int(self.doc_count or 0))
        self.retrieval_plan = dict(self.retrieval_plan or {})
        self.events = [
            event
            if isinstance(event, GraphTraceEventSnapshot)
            else GraphTraceEventSnapshot.from_dict(event)
            for event in (self.events or [])
        ]
        self.total_latency_ms = round(float(self.total_latency_ms or 0.0), 2)
        self.error = str(self.error or "")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "GraphRetrievalSnapshot":
        payload = dict(data or {})
        return cls(
            query=payload.get("query", ""),
            strategy=payload.get("strategy", "graph_rag"),
            requested_top_k=payload.get("requested_top_k", 0),
            retrieval_request=payload.get("retrieval_request"),
            query_type=payload.get("query_type", ""),
            source_entities=payload.get("source_entities") or [],
            target_entities=payload.get("target_entities") or [],
            relation_types=payload.get("relation_types") or [],
            sub_questions=payload.get("sub_questions") or [],
            path_count=payload.get("path_count", 0),
            subgraph_count=payload.get("subgraph_count", 0),
            reasoning_patterns=payload.get("reasoning_patterns") or [],
            reasoning_chain_count=payload.get("reasoning_chain_count", 0),
            evidence_unit_count=payload.get("evidence_unit_count", 0),
            doc_count=payload.get("doc_count", 0),
            retrieval_plan=payload.get("retrieval_plan") or {},
            events=payload.get("events") or [],
            total_latency_ms=payload.get("total_latency_ms", payload.get("latency_ms", 0.0)),
            error=payload.get("error", ""),
        )

    def add_event(
        self,
        name: str,
        *,
        status: str = "ok",
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not str(name or "").strip():
            return
        self.events.append(
            GraphTraceEventSnapshot(
                name=name,
                status=status,
                latency_ms=latency_ms,
                details=details or {},
            )
        )

    def to_stage_details(self) -> Dict[str, Any]:
        details = {
            "query_type": self.query_type,
            "source_entities": list(self.source_entities or []),
            "target_entities": list(self.target_entities or []),
            "relation_types": list(self.relation_types or []),
            "sub_questions": list(self.sub_questions or []),
            "graph_doc_count": self.doc_count,
            "path_count": self.path_count,
            "subgraph_count": self.subgraph_count,
            "reasoning_patterns": list(self.reasoning_patterns or []),
            "reasoning_chain_count": self.reasoning_chain_count,
            "evidence_unit_count": self.evidence_unit_count,
            "retrieval_plan": dict(self.retrieval_plan or {}),
            "retrieval_request": (
                self.retrieval_request.to_dict() if self.retrieval_request else {}
            ),
            "event_count": len(self.events or []),
            "events": [event.to_dict() for event in self.events],
            "graph_strategy": self.strategy,
            "graph_requested_top_k": self.requested_top_k,
        }
        if self.error:
            details["graph_error"] = self.error
        return details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "requested_top_k": self.requested_top_k,
            "retrieval_request": self.retrieval_request.to_dict() if self.retrieval_request else {},
            "query_type": self.query_type,
            "source_entities": list(self.source_entities or []),
            "target_entities": list(self.target_entities or []),
            "relation_types": list(self.relation_types or []),
            "sub_questions": list(self.sub_questions or []),
            "path_count": self.path_count,
            "subgraph_count": self.subgraph_count,
            "reasoning_patterns": list(self.reasoning_patterns or []),
            "reasoning_chain_count": self.reasoning_chain_count,
            "evidence_unit_count": self.evidence_unit_count,
            "doc_count": self.doc_count,
            "retrieval_plan": dict(self.retrieval_plan or {}),
            "events": [event.to_dict() for event in self.events],
            "total_latency_ms": self.total_latency_ms,
            "error": self.error,
        }

    def has_content(self) -> bool:
        return any(
            (
                bool(self.query),
                self.path_count != 0,
                self.subgraph_count != 0,
                self.reasoning_chain_count != 0,
                self.evidence_unit_count != 0,
                self.doc_count != 0,
                bool(self.events),
                bool(self.error),
            )
        )
