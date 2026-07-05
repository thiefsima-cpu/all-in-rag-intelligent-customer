"""Runtime DTOs for live quality gate execution."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

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


@dataclass(frozen=True)
class JudgeVerdict:
    case_id: str
    scores: Mapping[str, float]
    passed: bool
    rationale: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scores", MappingProxyType(dict(self.scores)))


@dataclass(frozen=True)
class JudgeRunResult:
    case_id: str
    verdict: JudgeVerdict | None
    checks: tuple[GateCheckResult, ...]


@dataclass(frozen=True)
class DeterministicCaseResult:
    case_id: str
    query_type: str
    cuisine: str
    constraint_types: tuple[str, ...]
    risk_tags: tuple[str, ...]
    response_mode: str
    strategy: str
    passed: bool
    response_mode_passed: bool
    failures: tuple[str, ...]
    metrics: Mapping[str, float | None]
    checks: tuple[GateCheckResult, ...]
    observation: LiveQualityObservation
    judge_passed: bool | None = None
    judge_scores: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", MappingProxyType(dict(self.metrics)))
        if self.judge_scores is not None:
            object.__setattr__(
                self,
                "judge_scores",
                MappingProxyType(dict(self.judge_scores)),
            )

    @property
    def checks_by_name(self) -> dict[str, GateCheckResult]:
        return {check.name: check for check in self.checks}

    def with_judge_result(
        self,
        passed: bool,
        scores: Mapping[str, float],
    ) -> DeterministicCaseResult:
        deterministic_passed = not self.failures
        return replace(
            self,
            passed=deterministic_passed and passed,
            metrics=dict(self.metrics),
            judge_passed=passed,
            judge_scores=dict(scores),
        )
