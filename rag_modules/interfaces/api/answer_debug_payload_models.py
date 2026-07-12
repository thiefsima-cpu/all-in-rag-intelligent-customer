"""Top-level debug answer payload DTOs."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from ...application.answering.answer_models import (
    QuestionAnswerDiagnostics,
    QuestionAnswerGrounding,
    QuestionAnswerResponse,
    QuestionAnswerTraces,
)
from .answer_debug_common_models import (
    EvidenceDocumentResponseModel,
    QueryAnalysisResponseModel,
    QueryDiagnosticsResponseModel,
)
from .answer_debug_retrieval_models import (
    AnswerContextResponseModel,
    GraphRetrievalSnapshotResponseModel,
    RetrievalOutcomeResponseModel,
    RouteResolutionResponseModel,
)
from .answer_debug_route_models import RouteSnapshotResponseModel
from .answer_debug_trace_models import (
    GenerationSnapshotResponseModel,
    QueryTraceEventResponseModel,
)
from .answer_public_models import AnswerSummaryModel


class AnswerGroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_outcome: RetrievalOutcomeResponseModel = Field(
        default_factory=RetrievalOutcomeResponseModel
    )
    answer_context: AnswerContextResponseModel = Field(default_factory=AnswerContextResponseModel)
    route_resolution: RouteResolutionResponseModel = Field(
        default_factory=RouteResolutionResponseModel
    )
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, grounding: QuestionAnswerGrounding) -> "AnswerGroundingModel":
        return cls(
            retrieval_outcome=RetrievalOutcomeResponseModel.from_dto(grounding.retrieval_outcome),
            answer_context=AnswerContextResponseModel.from_dto(grounding.answer_context),
            route_resolution=RouteResolutionResponseModel.from_dto(grounding.route_resolution),
            evidence_documents=[
                EvidenceDocumentResponseModel.from_dto(document)
                for document in grounding.evidence_documents
            ],
        )


class AnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
    )

    @classmethod
    def from_dto(cls, diagnostics: QuestionAnswerDiagnostics) -> "AnswerDiagnosticsModel":
        return cls(
            analysis=QueryAnalysisResponseModel.from_dto(diagnostics.analysis),
            diagnostics=QueryDiagnosticsResponseModel.from_dto(diagnostics.diagnostics),
        )


class AnswerTracesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    generation_trace: GenerationSnapshotResponseModel = Field(
        default_factory=GenerationSnapshotResponseModel
    )
    trace_event: QueryTraceEventResponseModel = Field(default_factory=QueryTraceEventResponseModel)

    @classmethod
    def from_dto(cls, traces: QuestionAnswerTraces) -> "AnswerTracesModel":
        return cls(
            route_trace=RouteSnapshotResponseModel.from_dto(traces.route_trace),
            graph_trace=GraphRetrievalSnapshotResponseModel.from_dto(traces.graph_trace),
            generation_trace=GenerationSnapshotResponseModel.from_dto(traces.generation_trace),
            trace_event=QueryTraceEventResponseModel.from_dto(traces.trace_event),
        )


class AnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: AnswerGroundingModel
    diagnostics: AnswerDiagnosticsModel
    traces: AnswerTracesModel

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AnswerPayloadModel":
        return cls.model_validate(dict(payload or {}))

    @classmethod
    def from_dto(cls, response: QuestionAnswerResponse) -> "AnswerPayloadModel":
        return cls(
            summary=AnswerSummaryModel.from_dto(response.summary),
            grounding=AnswerGroundingModel.from_dto(response.grounding),
            diagnostics=AnswerDiagnosticsModel.from_dto(response.diagnostics),
            traces=AnswerTracesModel.from_dto(response.traces),
        )


class AnswerResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AnswerPayloadModel


__all__ = [
    "AnswerDiagnosticsModel",
    "AnswerGroundingModel",
    "AnswerPayloadModel",
    "AnswerResponseModel",
    "AnswerTracesModel",
]
