"""Consumer-owned ports for application use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, ContextManager, Protocol

from ..contracts import EvidenceDocument, RequestControl
from ..contracts.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ..kernel.artifacts import ArtifactManifest
from ..kernel.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from .answering.answer_models import QuestionAnswerResponse, QuestionAnswerResult

ProgressCallback = Callable[[str], None] | None
MessageCallback = Callable[[str], None] | None
ChunkCallback = Callable[[str], None] | None


class AnswerWorkflowCopy(Protocol):
    """Product-copy fields consumed by the answer use case."""

    no_evidence_answer: str
    answer_failed: str
    user_question_template: str
    query_routing_started: str
    answer_generation_started: str
    streaming_interrupted_fallback: str
    answer_complete_template: str
    strategy_summary_template: str
    strategy_icon_hybrid_traditional: str
    strategy_icon_graph_rag: str
    strategy_icon_combined: str
    strategy_icon_default: str
    document_summary_template: str
    document_summary_total_template: str
    unknown_entity_name: str
    unknown_search_type: str


class CloseablePort(Protocol):
    """Resource lifecycle behavior consumed by an application use case."""

    def close(self) -> object: ...


class AnswerSpanPort(Protocol):
    """Minimal span behavior used while executing an answer request."""

    def set_attribute(self, name: str, value: object) -> object: ...


class AnswerTelemetryPort(Protocol):
    """Observability behavior consumed by the answer use case."""

    def span(
        self,
        name: str,
        *,
        attributes: dict[str, object] | None = None,
    ) -> ContextManager[AnswerSpanPort]: ...

    def enrich_answer_span(self, span: AnswerSpanPort, result: object) -> None: ...

    def record_answer(self, result: object) -> None: ...


class QueryTracerPort(Protocol):
    """Query trace behavior consumed by the answer use case."""

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: RuntimeErrorDetail | Mapping[str, JsonValue] | None = None,
        route_trace: Mapping[str, JsonValue] | RouteSnapshot | None = None,
        graph_trace: Mapping[str, JsonValue] | GraphRetrievalSnapshot | None = None,
        generation_trace: Mapping[str, JsonValue] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent: ...

    def stats(self) -> JsonObject: ...

    def close(self) -> None: ...


class KnowledgeBaseBuildWorkflowPort(Protocol):
    """Build workflow behavior delegated to by the knowledge-base use case."""

    @property
    def artifacts_ready(self) -> bool: ...

    @property
    def artifact_manifest(self) -> ArtifactManifest: ...

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None: ...

    def build(
        self,
        progress: ProgressCallback = None,
        *,
        force_rebuild: bool = False,
        request_id: str = "",
        build_job_id: str = "",
    ) -> ArtifactManifest: ...

    def rebuild(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> ArtifactManifest: ...

    def show_stats(self, progress: ProgressCallback = None) -> None: ...


class KnowledgeBaseServicePort(Protocol):
    """Knowledge-base lifecycle behavior consumed by composition."""

    @property
    def artifacts_ready(self) -> bool: ...

    @property
    def system_ready(self) -> bool: ...

    @property
    def artifact_manifest(self) -> ArtifactManifest: ...

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None: ...

    def build(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def rebuild(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def show_stats(self, progress: ProgressCallback = None) -> None: ...

    def close(self) -> None: ...


class AnswerWorkflowPort(Protocol):
    """Question-answer behavior consumed by composition and interfaces."""

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResult: ...

    def answer_question_response(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResponse: ...


__all__ = [
    "AnswerSpanPort",
    "AnswerTelemetryPort",
    "AnswerWorkflowCopy",
    "AnswerWorkflowPort",
    "ChunkCallback",
    "CloseablePort",
    "KnowledgeBaseBuildWorkflowPort",
    "KnowledgeBaseServicePort",
    "MessageCallback",
    "ProgressCallback",
    "QueryTracerPort",
]
