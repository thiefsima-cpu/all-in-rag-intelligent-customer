from __future__ import annotations

from collections.abc import Mapping, Sequence

from rag_modules.app.provider_components.contracts import (
    ApplicationServiceComponentProvider,
    InfrastructureComponentProvider,
    RetrievalComponentProvider,
)
from rag_modules.app.provider_components.infrastructure import (
    DefaultInfrastructureComponentProvider,
)
from rag_modules.app.provider_components.retrieval import DefaultRetrievalComponentProvider
from rag_modules.app.provider_components.services import (
    DefaultApplicationServiceComponentProvider,
)
from rag_modules.app.runtime_contracts import (
    GraphDataModulePort,
    GraphRAGRetrievalPort,
    HybridRetrievalPort,
    LLMChatPort,
    LLMClientPort,
    LLMCompletionChoicePort,
    LLMCompletionMessagePort,
    LLMCompletionResponsePort,
    LLMCompletionsPort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)
from rag_modules.configuration.testing import build_test_config
from rag_modules.graph.retrieval_types import GraphQuery
from rag_modules.query_constraints import QueryConstraints
from rag_modules.query_understanding import QueryPlan
from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome
from rag_modules.runtime import GraphRetrievalSnapshot

infrastructure_provider: InfrastructureComponentProvider = DefaultInfrastructureComponentProvider()
retrieval_provider: RetrievalComponentProvider = DefaultRetrievalComponentProvider()
service_provider: ApplicationServiceComponentProvider = DefaultApplicationServiceComponentProvider()


class _CompletionMessage:
    content: str | None = "{}"


class _CompletionChoice:
    message: LLMCompletionMessagePort = _CompletionMessage()


class _CompletionResponse:
    choices: Sequence[LLMCompletionChoicePort] = (_CompletionChoice(),)


class _Completions:
    def create(
        self,
        *,
        model: str,
        messages: Sequence[Mapping[str, str]],
        temperature: float,
        max_tokens: int,
        timeout: int | float,
    ) -> LLMCompletionResponsePort:
        del model, messages, temperature, max_tokens, timeout
        return _CompletionResponse()


class _Chat:
    completions: LLMCompletionsPort = _Completions()


class _LLMClient:
    chat: LLMChatPort = _Chat()


class _HybridRetrieval:
    def hybrid_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        candidate_k: int | None = None,
        query_plan: QueryPlan | None = None,
    ) -> HybridRetrievalOutcome:
        del request_or_query, top_k, constraints, candidate_k, query_plan
        return HybridRetrievalOutcome()

    def enrich_to_parent_evidence_documents(
        self,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]:
        del top_n
        return list(docs)


class _GraphRetrieval:
    def graph_rag_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> list[EvidenceDocument]:
        del request_or_query, top_k, constraints, query_plan
        return []

    def graph_rag_evidence_search_with_trace(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
        del request_or_query, constraints, query_plan
        return [], GraphRetrievalSnapshot(requested_top_k=top_k)

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        del plan
        raise NotImplementedError


llm_client: LLMClientPort = _LLMClient()
hybrid_retrieval: HybridRetrievalPort = _HybridRetrieval()
graph_retrieval: GraphRAGRetrievalPort = _GraphRetrieval()


def accept_runtime_ports(
    graph_manager: Neo4jManagerPort,
    data_module: GraphDataModulePort,
    index_module: VectorIndexModulePort,
    query_tracer: QueryTracerPort,
) -> tuple[BuildRuntime, ServingRuntime, SystemInfrastructureView]:
    config = build_test_config()
    build_runtime = BuildRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    serving_runtime = ServingRuntime(
        config=config,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
        query_tracer=query_tracer,
    )
    infrastructure = SystemInfrastructureView(
        query_tracer=query_tracer,
        neo4j_manager=graph_manager,
        data_module=data_module,
        index_module=index_module,
    )
    return build_runtime, serving_runtime, infrastructure


def accept_grouped_views(
    infrastructure: SystemInfrastructureView,
    retrieval: SystemRetrievalView,
    services: SystemServicesView,
) -> tuple[SystemInfrastructureView, SystemRetrievalView, SystemServicesView]:
    return infrastructure, retrieval, services
