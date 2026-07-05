"""Runtime DTOs for live quality gate execution."""

from __future__ import annotations

from dataclasses import dataclass

from scripts.gates import GateCheckResult


@dataclass(frozen=True)
class LiveQualityEvidence:
    recipe_name: str
    source: str
    content: str
    score: float


@dataclass(frozen=True)
class LiveQualityObservation:
    case_id: str
    answer: str
    strategy: str
    evidence: tuple[LiveQualityEvidence, ...]
    ranked_recipe_names: tuple[str, ...]
    sources: frozenset[str]
    fallback_used: bool
    retrieval_degraded: bool
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float


@dataclass(frozen=True)
class LiveQualityCaseRunResult:
    case_id: str
    observation: LiveQualityObservation | None
    checks: tuple[GateCheckResult, ...]
