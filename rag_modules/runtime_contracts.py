"""Structural runtime collaborator contracts shared below app assembly."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from .contracts import EvidenceDocument, QueryPlan, RetrievalRequest
    from .domain.shared.query_constraints import QueryConstraints
    from .graph.retrieval_types import GraphQuery
    from .retrieval.hybrid_outcome import HybridRetrievalOutcome
    from .runtime import (
        AnswerContext,
        GenerationSnapshot,
        GraphRetrievalSnapshot,
        QueryTraceEvent,
        RetrievalOutcome,
        RouteSnapshot,
    )
    from .runtime.json_types import JsonObject, JsonValue
    from .text_document import TextDocument
else:
    JsonObject = dict[str, object]
    JsonValue = object


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior used by retrieval adapters."""

    def __enter__(self) -> Neo4jSessionPort: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(self, query: str, parameters: object | None = None, **kwargs: object) -> Any: ...

    def execute_read(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...

    def execute_write(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior used by retrieval adapters."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...

    def close(self) -> None: ...


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior used by runtime assembly and shutdown."""

    @property
    def driver(self) -> Neo4jDriverPort: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class GraphDataModulePort(Protocol):
    """Graph data loader and document materializer behavior."""

    documents: list[TextDocument]
    chunks: list[TextDocument]

    def load_graph_data(self) -> JsonObject: ...

    def build_recipe_documents(self) -> list[TextDocument]: ...

    def chunk_documents(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> list[TextDocument]: ...

    def get_statistics(self) -> JsonObject: ...

    def close(self) -> None: ...


class VectorIndexModulePort(Protocol):
    """Vector index behavior used by build, serving, and hybrid retrieval."""

    collection_name: str

    def has_collection(self, collection_name: str | None = None) -> bool: ...

    def load_collection(self, collection_name: str | None = None) -> bool: ...

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool: ...

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filters: Mapping[str, JsonValue] | None = None,
    ) -> list[JsonObject]: ...

    def get_collection_stats(self, collection_name: str | None = None) -> JsonObject: ...

    def delete_collection(self, collection_name: str | None = None) -> bool: ...

    def close(self) -> None: ...


class QueryTracerPort(Protocol):
    """Query trace behavior consumed by answer workflow and runtime shutdown."""

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: str | None = None,
        route_trace: Mapping[str, JsonValue] | RouteSnapshot | None = None,
        graph_trace: Mapping[str, JsonValue] | GraphRetrievalSnapshot | None = None,
        generation_trace: Mapping[str, JsonValue] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent: ...

    def stats(self) -> JsonObject: ...

    def close(self) -> None: ...


class HybridCandidateRuntimePort(Protocol):
    """Candidate-source runtime behavior for hybrid retrieval."""

    def dual_level_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...

    def vector_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...

    def bm25_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...


class LLMCompletionMessagePort(Protocol):
    """OpenAI-compatible completion message shape used by query planning."""

    content: str | None


class LLMCompletionChoicePort(Protocol):
    """OpenAI-compatible completion choice shape used by query planning."""

    message: LLMCompletionMessagePort


class LLMCompletionResponsePort(Protocol):
    """OpenAI-compatible completion response shape used by query planning."""

    choices: Sequence[LLMCompletionChoicePort]


class LLMCompletionsPort(Protocol):
    """OpenAI-compatible chat completions surface kept for adapter boundaries."""

    def create(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: int | float,
    ) -> LLMCompletionResponsePort: ...


class LLMChatPort(Protocol):
    """OpenAI-compatible chat namespace kept for adapter boundaries."""

    completions: LLMCompletionsPort


class OpenAICompatibleLLMClientPort(Protocol):
    """Raw OpenAI-compatible client shape used only inside provider adapters."""

    chat: LLMChatPort


class LLMClientPort(Protocol):
    """Provider-neutral LLM behavior used by runtime services."""

    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int | float,
        model_name: str | None = None,
    ) -> LLMCompletionResponsePort: ...


class StreamingLLMClientPort(LLMClientPort, Protocol):
    """Provider-neutral streaming LLM behavior used by answer generation."""

    def stream_prompt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        retries: int,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> Iterator[str]: ...


class EmbeddingClientPort(Protocol):
    """Provider-neutral embedding behavior used by vector indexing and search."""

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class RerankClientPort(Protocol):
    """Provider-neutral rerank behavior used by retrieval post-processing."""

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> list[int]: ...


class HybridRetrievalPort(Protocol):
    """Hybrid retrieval behavior consumed by routing."""

    def hybrid_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        candidate_k: int | None = None,
        query_plan: QueryPlan | None = None,
    ) -> HybridRetrievalOutcome: ...

    def enrich_to_parent_evidence_documents(
        self,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]: ...


class GraphRAGRetrievalPort(Protocol):
    """Graph retrieval behavior consumed by routing."""

    def graph_rag_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> list[EvidenceDocument]: ...

    def graph_rag_evidence_search_with_trace(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]: ...

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery: ...


__all__ = [
    "GraphDataModulePort",
    "GraphRAGRetrievalPort",
    "HybridCandidateRuntimePort",
    "HybridRetrievalPort",
    "EmbeddingClientPort",
    "LLMChatPort",
    "LLMClientPort",
    "LLMCompletionChoicePort",
    "LLMCompletionMessagePort",
    "LLMCompletionResponsePort",
    "LLMCompletionsPort",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "Neo4jSessionPort",
    "OpenAICompatibleLLMClientPort",
    "QueryTracerPort",
    "RerankClientPort",
    "StreamingLLMClientPort",
    "VectorIndexModulePort",
]
