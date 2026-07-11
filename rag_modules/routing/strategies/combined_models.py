"""Shared models for combined route execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal, TypeAlias

from ...contracts import EvidenceDocument, RequestControl, RetrievalRequest
from ...contracts.runtime.retrieval import HybridRetrievalOutcome

BranchName: TypeAlias = Literal["traditional", "graph"]


@dataclass(frozen=True)
class TraditionalBranchResult:
    outcome: HybridRetrievalOutcome
    latency_ms: float


@dataclass(frozen=True)
class GraphBranchResult:
    documents: List[EvidenceDocument]
    trace: object
    latency_ms: float


BranchResult: TypeAlias = TraditionalBranchResult | GraphBranchResult


@dataclass(frozen=True)
class CombinedRouteRun:
    candidate_k: int
    branch_timeout_seconds: float
    traditional_request: RetrievalRequest
    graph_request: RetrievalRequest
    branch_controls: dict[BranchName, RequestControl]


@dataclass(frozen=True)
class BranchExecutionState:
    results: dict[BranchName, BranchResult]
    timed_out_branches: List[BranchName]
    cancel_observed_branches: List[BranchName]


@dataclass(frozen=True)
class CombinedBranchDocuments:
    combined_docs: List[EvidenceDocument]
    traditional_outcome: HybridRetrievalOutcome | None
    graph_trace: object | None
    traditional_docs: List[EvidenceDocument]
    graph_docs: List[EvidenceDocument]
    traditional_latency_ms: float | None
    graph_latency_ms: float | None


__all__ = [
    "BranchExecutionState",
    "BranchName",
    "BranchResult",
    "CombinedBranchDocuments",
    "CombinedRouteRun",
    "GraphBranchResult",
    "TraditionalBranchResult",
]
