"""Candidate generation for hybrid retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence, Tuple

from ..contracts import EvidenceDocument, RetrievalRequest
from ..infra.resilience import CircuitBreaker, CircuitOpenError
from ..safe_logging import log_failure
from .candidate_sources import CandidateSourceSpec, RetrievalCandidateSource

logger = logging.getLogger(__name__)

SKIP_CANDIDATE_SOURCES_METADATA_KEY = "skip_candidate_sources"


class CandidateSourceDegradationStrategy(str, Enum):
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"


SOURCE_DEGRADATION_STRATEGY_CONTINUE = CandidateSourceDegradationStrategy.CONTINUE.value
SOURCE_DEGRADATION_STRATEGY_FAIL_FAST = CandidateSourceDegradationStrategy.FAIL_FAST.value
SUPPORTED_SOURCE_DEGRADATION_STRATEGIES = {
    strategy.value for strategy in CandidateSourceDegradationStrategy
}
CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED = "CANDIDATE_SOURCE_RETRIEVAL_FAILED"
CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN = "CANDIDATE_SOURCE_CIRCUIT_OPEN"
CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED = "CANDIDATE_SOURCE_REQUEST_SKIPPED"
CANDIDATE_SOURCE_ERROR_DEGRADED = "CANDIDATE_SOURCE_DEGRADED"
_SOURCE_DEGRADATION_ERROR_CODES = {
    "exception": CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED,
    "circuit_open": CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN,
    "request_skip": CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED,
}


def _candidate_source_error_code(reason: str) -> str:
    return _SOURCE_DEGRADATION_ERROR_CODES.get(
        str(reason or "").strip(),
        CANDIDATE_SOURCE_ERROR_DEGRADED,
    )


def _normalize_source_degradation_strategy(
    value: CandidateSourceDegradationStrategy | str,
) -> CandidateSourceDegradationStrategy:
    if isinstance(value, CandidateSourceDegradationStrategy):
        return value
    normalized = str(value or CandidateSourceDegradationStrategy.CONTINUE.value).strip().lower()
    try:
        return CandidateSourceDegradationStrategy(normalized)
    except ValueError:
        supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
        raise ValueError(f"source_degradation_strategy must be one of: {supported}") from None


@dataclass
class CandidateSourceResult:
    """Documents produced by one retrieval candidate source."""

    spec: CandidateSourceSpec
    documents: List[EvidenceDocument] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CandidateSourceDegradation:
    """Traceable degraded decision for one candidate source."""

    spec: CandidateSourceSpec
    reason: str
    error_type: str = ""
    message: str = ""
    circuit_state: str = ""
    failure_count: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "source": self.spec.name,
            "error_code": _candidate_source_error_code(self.reason),
            "error_type": self.error_type,
        }


@dataclass
class CandidateSet:
    """Normalized candidate documents across all configured sources."""

    source_results: List[CandidateSourceResult] = field(default_factory=list)
    degraded: List[CandidateSourceDegradation] = field(default_factory=list)

    @property
    def dual_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("dual")

    @property
    def vector_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("vector")

    @property
    def bm25_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("bm25")

    @property
    def constraint_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("constraints")

    @property
    def ranked_lists(self) -> List[Tuple[str, List[EvidenceDocument]]]:
        ranked: List[Tuple[str, List[EvidenceDocument]]] = []
        for result in sorted(self.source_results, key=lambda item: item.spec.rank_order):
            if result.documents:
                ranked.append((result.spec.rank_name, list(result.documents)))
        return ranked

    @property
    def stats(self) -> dict:
        return {
            result.spec.name: len(result.documents)
            for result in sorted(self.source_results, key=lambda item: item.spec.rank_order)
        }

    @property
    def degraded_sources(self) -> List[str]:
        return [item.spec.name for item in self.degraded]

    @property
    def degraded_details(self) -> List[Dict[str, object]]:
        return [item.to_dict() for item in self.degraded]

    def documents_for(self, source_name: str) -> List[EvidenceDocument]:
        for result in self.source_results:
            if result.spec.name == source_name:
                return list(result.documents)
        return []

    def to_stage_details(self) -> Dict[str, object]:
        return {
            "candidate_counts": self.stats,
            "degraded_sources": self.degraded_sources,
            "degraded_candidates": self.degraded_details,
        }


class RetrievalCandidateGenerator:
    """Generate hybrid retrieval candidates from configured source contracts."""

    def __init__(
        self,
        *,
        sources: Sequence[RetrievalCandidateSource],
        source_failure_threshold: int = 1,
        source_recovery_timeout_seconds: float = 30.0,
        source_degradation_strategy: CandidateSourceDegradationStrategy | str = (
            CandidateSourceDegradationStrategy.CONTINUE
        ),
    ):
        self.sources = tuple(sources)
        self.source_failure_threshold = max(1, int(source_failure_threshold))
        self.source_recovery_timeout_seconds = max(0.1, float(source_recovery_timeout_seconds))
        self.source_degradation_strategy = _normalize_source_degradation_strategy(
            source_degradation_strategy
        )
        self._source_breakers = {
            source.spec.name: CircuitBreaker(
                failure_threshold=self.source_failure_threshold,
                recovery_timeout_seconds=self.source_recovery_timeout_seconds,
            )
            for source in self.sources
        }

    def generate(self, request: RetrievalRequest) -> CandidateSet:
        effective_request = self._calibrate_request(request)
        results: List[CandidateSourceResult] = []
        degraded: List[CandidateSourceDegradation] = []
        skipped_sources = self._request_skipped_sources(effective_request)
        for source in self.sources:
            documents, degradation = self._retrieve_source(
                source,
                effective_request,
                skipped_sources=skipped_sources,
            )
            if degradation:
                degraded.append(degradation)
            results.append(
                CandidateSourceResult(
                    spec=source.spec,
                    documents=documents,
                )
            )
        candidate_set = CandidateSet(source_results=results, degraded=degraded)
        logger.debug("Hybrid candidate generation stats: %s", candidate_set.stats)
        return candidate_set

    @staticmethod
    def _calibrate_request(request: RetrievalRequest) -> RetrievalRequest:
        effective_request = request
        if request.query_plan:
            if not request.entity_keywords and request.planned_entity_keywords:
                effective_request = effective_request.copy_with(
                    entity_keywords=request.planned_entity_keywords,
                )
            if not request.topic_keywords and request.planned_topic_keywords:
                effective_request = effective_request.copy_with(
                    topic_keywords=request.planned_topic_keywords,
                )
            if (
                not request.effective_constraints.has_constraints()
                and request.query_plan.constraints.has_constraints()
            ):
                effective_request = effective_request.copy_with(
                    constraints=request.query_plan.constraints,
                )
        return effective_request

    @staticmethod
    def _request_skipped_sources(request: RetrievalRequest) -> set[str]:
        raw_sources = request.metadata.get(SKIP_CANDIDATE_SOURCES_METADATA_KEY, [])
        if isinstance(raw_sources, str):
            raw_sources = [raw_sources]
        return {str(item).strip() for item in (raw_sources or []) if str(item).strip()}

    def _retrieve_source(
        self,
        source: RetrievalCandidateSource,
        request: RetrievalRequest,
        *,
        skipped_sources: set[str],
    ) -> tuple[List[EvidenceDocument], CandidateSourceDegradation | None]:
        breaker = self._source_breakers[source.spec.name]
        if source.spec.name in skipped_sources:
            return [], self._degradation(
                source.spec,
                reason="request_skip",
                breaker=breaker,
            )
        try:
            breaker.before_call()
        except CircuitOpenError as exc:
            if self._should_raise_degradation():
                raise
            return [], self._degradation(
                source.spec,
                reason="circuit_open",
                breaker=breaker,
                error=exc,
            )
        try:
            documents = self._normalize_source_documents(
                source.retrieve(request),
                spec=source.spec,
            )
        except Exception as exc:
            breaker.record_failure()
            logger.warning("Candidate source degraded: name=%s", source.spec.name)
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            if self._should_raise_degradation():
                raise
            return [], self._degradation(
                source.spec,
                reason="exception",
                breaker=breaker,
                error=exc,
            )
        breaker.record_success()
        return documents, None

    def _should_raise_degradation(self) -> bool:
        return self.source_degradation_strategy is CandidateSourceDegradationStrategy.FAIL_FAST

    @staticmethod
    def _degradation(
        spec: CandidateSourceSpec,
        *,
        reason: str,
        breaker: CircuitBreaker,
        error: Exception | None = None,
    ) -> CandidateSourceDegradation:
        snapshot = breaker.snapshot()
        return CandidateSourceDegradation(
            spec=spec,
            reason=reason,
            error_type=type(error).__name__ if error else "",
            circuit_state=snapshot.state,
            failure_count=snapshot.failure_count,
        )

    @staticmethod
    def _normalize_source_documents(
        documents: List[EvidenceDocument],
        *,
        spec: CandidateSourceSpec,
    ) -> List[EvidenceDocument]:
        normalized: List[EvidenceDocument] = []
        for doc in documents or []:
            metadata: Dict[str, object] = dict(doc.metadata or {})
            metadata.setdefault("search_method", doc.search_method or spec.search_method)
            metadata.setdefault("search_type", doc.search_type or spec.search_type)
            normalized.append(
                doc.copy_with(
                    search_method=doc.search_method or spec.search_method,
                    search_type=doc.search_type or spec.search_type,
                    metadata=metadata,
                )
            )
        return normalized


__all__ = [
    "CandidateSet",
    "CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN",
    "CANDIDATE_SOURCE_ERROR_DEGRADED",
    "CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED",
    "CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED",
    "CandidateSourceDegradation",
    "CandidateSourceDegradationStrategy",
    "CandidateSourceResult",
    "RetrievalCandidateGenerator",
    "SKIP_CANDIDATE_SOURCES_METADATA_KEY",
]
