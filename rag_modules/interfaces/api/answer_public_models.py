"""Public answer response DTOs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ...app.services.answer_models import (
    QuestionAnswerDiagnostics,
    QuestionAnswerGrounding,
    QuestionAnswerResponse,
    QuestionAnswerSummary,
)
from ...contracts import EvidenceDocument
from ...runtime.json_types import JsonObject, coerce_json_object
from .answer_mappers import public_answer_error

if TYPE_CHECKING:
    from .answer_debug_models import (
        AnswerDiagnosticsModel,
        AnswerGroundingModel,
        AnswerPayloadModel,
        EvidenceDocumentResponseModel,
        QueryDiagnosticsResponseModel,
    )


class AnswerSummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    status: str = "success"
    strategy: str = ""
    latency_ms: float = 0.0
    doc_count: int = 0
    has_evidence: bool = False
    fallback_used: bool = False
    failure_code: str = ""
    provider_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""
    error: str = ""

    @classmethod
    def from_dto(cls, summary: QuestionAnswerSummary) -> "AnswerSummaryModel":
        return cls(
            answer=summary.answer,
            status=summary.status,
            strategy=summary.strategy,
            latency_ms=summary.latency_ms,
            doc_count=summary.doc_count,
            has_evidence=summary.has_evidence,
            fallback_used=summary.fallback_used,
            failure_code=summary.failure_code,
            provider_latency_ms=summary.provider_latency_ms,
            prompt_tokens=summary.prompt_tokens,
            completion_tokens=summary.completion_tokens,
            total_tokens=summary.total_tokens,
            estimated_cost_usd=summary.estimated_cost_usd,
            token_usage_source=summary.token_usage_source,
            error=public_answer_error(summary.error),
        )


class PublicEvidenceDocumentResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    recipe_name: str = ""
    score: float = 0.0
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: list[str] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, document: EvidenceDocument) -> "PublicEvidenceDocumentResponseModel":
        return cls(
            content=document.content,
            recipe_name=document.recipe_name,
            score=document.score,
            source=document.source,
            evidence_type=document.evidence_type,
            matched_terms=list(document.matched_terms),
        )

    @classmethod
    def from_debug_model(
        cls,
        document: EvidenceDocumentResponseModel,
    ) -> "PublicEvidenceDocumentResponseModel":
        return cls(
            content=document.content,
            recipe_name=document.recipe_name,
            score=document.score,
            source=document.source,
            evidence_type=document.evidence_type,
            matched_terms=list(document.matched_terms),
        )


class PublicAnswerGroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_documents: list[PublicEvidenceDocumentResponseModel] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, grounding: QuestionAnswerGrounding) -> "PublicAnswerGroundingModel":
        return cls(
            evidence_documents=[
                PublicEvidenceDocumentResponseModel.from_dto(document)
                for document in grounding.evidence_documents
            ],
        )

    @classmethod
    def from_debug_model(
        cls,
        grounding: AnswerGroundingModel,
    ) -> "PublicAnswerGroundingModel":
        return cls(
            evidence_documents=[
                PublicEvidenceDocumentResponseModel.from_debug_model(document)
                for document in grounding.evidence_documents
            ],
        )


class PublicAnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_bucket: str = ""
    generation_bucket: str = ""
    overall_bucket: str = ""
    retrieval_degraded: bool = False
    degraded_sources: list[str] = Field(default_factory=list)
    degraded_candidates: list[JsonObject] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, diagnostics: QuestionAnswerDiagnostics) -> "PublicAnswerDiagnosticsModel":
        from .answer_debug_models import QueryDiagnosticsResponseModel

        return cls.from_query_diagnostics(
            QueryDiagnosticsResponseModel.from_dto(diagnostics.diagnostics)
        )

    @classmethod
    def from_debug_model(
        cls,
        diagnostics: AnswerDiagnosticsModel,
    ) -> "PublicAnswerDiagnosticsModel":
        return cls.from_query_diagnostics(diagnostics.diagnostics)

    @classmethod
    def from_query_diagnostics(
        cls,
        diagnostics: QueryDiagnosticsResponseModel,
    ) -> "PublicAnswerDiagnosticsModel":
        return cls(
            retrieval_bucket=diagnostics.retrieval_bucket,
            generation_bucket=diagnostics.generation_bucket,
            overall_bucket=diagnostics.overall_bucket,
            retrieval_degraded=diagnostics.retrieval_degraded,
            degraded_sources=list(diagnostics.degraded_sources),
            degraded_candidates=[
                coerce_json_object(candidate) for candidate in diagnostics.degraded_candidates
            ],
            circuit_breaker_triggered=diagnostics.circuit_breaker_triggered,
            answer_impacted=diagnostics.answer_impacted,
            failure_reasons=list(diagnostics.failure_reasons),
        )


class PublicAnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: PublicAnswerGroundingModel
    diagnostics: PublicAnswerDiagnosticsModel

    @classmethod
    def from_debug_payload(cls, payload: AnswerPayloadModel) -> "PublicAnswerPayloadModel":
        return cls(
            summary=payload.summary,
            grounding=PublicAnswerGroundingModel.from_debug_model(payload.grounding),
            diagnostics=PublicAnswerDiagnosticsModel.from_debug_model(payload.diagnostics),
        )

    @classmethod
    def from_dto(cls, response: QuestionAnswerResponse) -> "PublicAnswerPayloadModel":
        return cls(
            summary=AnswerSummaryModel.from_dto(response.summary),
            grounding=PublicAnswerGroundingModel.from_dto(response.grounding),
            diagnostics=PublicAnswerDiagnosticsModel.from_dto(response.diagnostics),
        )


class PublicAnswerResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: PublicAnswerPayloadModel


__all__ = [
    "AnswerSummaryModel",
    "PublicAnswerDiagnosticsModel",
    "PublicAnswerGroundingModel",
    "PublicAnswerPayloadModel",
    "PublicAnswerResponseModel",
    "PublicEvidenceDocumentResponseModel",
]
