from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence

from rag_modules.app.diagnostics import DataStatsDiagnostics, TraceStatsDiagnostics
from rag_modules.app.providers import (
    ApplicationServiceProvider,
    InfrastructureProvider,
    RetrievalRuntimeProvider,
    create_default_runtime_provider,
)
from rag_modules.app.runtime_contracts import (
    EmbeddingClientPort,
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
    OpenAICompatibleLLMClientPort,
    QueryTracerPort,
    RerankClientPort,
    StreamingLLMClientPort,
    VectorIndexModulePort,
)
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.runtime_views import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)
from rag_modules.build_pipeline.graph_preparation.models import GraphLoadCounts
from rag_modules.build_pipeline.graph_preparation.statistics import GraphPreparationStats
from rag_modules.configuration.testing import build_test_config, semantic_runtime_settings
from rag_modules.contracts import (
    EvidenceDocument,
    GraphQueryType,
    QueryPlan,
    QuerySemanticProfile,
    RequestControl,
    RetrievalRequest,
)
from rag_modules.contracts.graph import GraphQuery
from rag_modules.contracts.runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
)
from rag_modules.contracts.runtime.retrieval import HybridRetrievalOutcome
from rag_modules.generation.execution.contracts import (
    GenerationAttemptResult,
    GenerationTokenUsage,
)
from rag_modules.generation.execution.engine import GenerationExecutionEngine
from rag_modules.generation.execution.usage import GenerationUsageCollector
from rag_modules.graph.retrieval_types import (
    GraphNodeSnapshot,
    GraphRelationshipSnapshot,
)
from rag_modules.infra.milvus.contracts import MilvusOperationHost
from rag_modules.infra.milvus.module import MilvusIndexConstructionModule
from rag_modules.kernel.json_types import JsonObject
from rag_modules.query_policy import get_query_policy
from rag_modules.query_policy.models import GenerationDecisionPolicy, GraphSubQuestionPolicy
from rag_modules.query_understanding.planning import QueryPlanCalibrator

runtime_provider = create_default_runtime_provider()
infrastructure_provider: InfrastructureProvider = runtime_provider.infrastructure
retrieval_provider: RetrievalRuntimeProvider = runtime_provider.retrieval_runtime
service_provider: ApplicationServiceProvider = runtime_provider.services

trace_stats: TraceStatsDiagnostics = TraceStatsDiagnostics.from_payload({"dropped_events": 1})
data_stats: DataStatsDiagnostics = DataStatsDiagnostics.from_payload({"total_recipes": 2})
policy_bundle = get_query_policy()
first_sub_question: GraphSubQuestionPolicy = policy_bundle.graph.sub_questions[0]
generation_decision_policy: GenerationDecisionPolicy = policy_bundle.generation.decision
graph_node_snapshot: GraphNodeSnapshot = GraphNodeSnapshot(node_id="r1", name="recipe")
graph_relationship_snapshot: GraphRelationshipSnapshot = GraphRelationshipSnapshot(
    relation_type="RELATED",
    start_node_id="r1",
    end_node_id="i1",
)
graph_load_counts: GraphLoadCounts = GraphLoadCounts(recipes=1)
graph_preparation_stats: GraphPreparationStats = GraphPreparationStats(total_recipes=1)


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


class _OpenAICompatibleLLMClient:
    chat: LLMChatPort = _Chat()


class _LLMClient:
    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int | float,
        model_name: str | None = None,
        control: RequestControl | None = None,
    ) -> LLMCompletionResponsePort:
        del prompt, temperature, max_tokens, timeout, model_name, control
        return _CompletionResponse()

    def stream_prompt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        retries: int,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
    ) -> Iterator[str]:
        del prompt, max_tokens, retries, temperature, timeout_seconds, control
        return iter(())


class _EmbeddingClient:
    def embed_query(self, text: str, *, timeout_seconds: float | None = None) -> list[float]:
        del text, timeout_seconds
        return []

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> list[list[float]]:
        del texts, timeout_seconds
        return []


class _RerankClient:
    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
        *,
        control: RequestControl | None = None,
        timeout_seconds: float | None = None,
    ) -> list[int]:
        del query, documents, top_n, control, timeout_seconds
        return []


class _HybridRetrieval:
    def hybrid_evidence_search(
        self,
        request: RetrievalRequest,
    ) -> HybridRetrievalOutcome:
        del request
        return HybridRetrievalOutcome()

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: list[EvidenceDocument],
        top_n: int | None = None,
    ) -> list[EvidenceDocument]:
        del request, top_n
        return list(docs)


class _GraphRetrieval:
    def graph_rag_evidence_search_with_trace(
        self,
        request: RetrievalRequest,
    ) -> tuple[list[EvidenceDocument], GraphRetrievalSnapshot]:
        return [], GraphRetrievalSnapshot(requested_top_k=request.top_k)

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        del plan
        raise NotImplementedError


openai_compatible_llm_client: OpenAICompatibleLLMClientPort = _OpenAICompatibleLLMClient()
llm_client: LLMClientPort = _LLMClient()
streaming_llm_client: StreamingLLMClientPort = _LLMClient()
embedding_client: EmbeddingClientPort = _EmbeddingClient()
rerank_client: RerankClientPort = _RerankClient()
hybrid_retrieval: HybridRetrievalPort = _HybridRetrieval()
graph_retrieval: GraphRAGRetrievalPort = _GraphRetrieval()


class _CandidateSetView:
    @property
    def stats(self) -> Mapping[str, int]:
        return {"vector": 1}

    @property
    def degraded_details(self) -> Sequence[Mapping[str, object]]:
        return ({"source": "bm25"},)


hybrid_outcome_from_candidate_view = HybridRetrievalOutcome.from_candidate_set(
    documents=[],
    candidates=_CandidateSetView(),
)


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


def accept_execution_hosts(
    generation_engine: GenerationExecutionEngine,
    milvus_module: MilvusIndexConstructionModule,
) -> tuple[GenerationExecutionEngine, MilvusOperationHost, VectorIndexModulePort]:
    return generation_engine, milvus_module, milvus_module


def accept_generation_execution_contracts(
    usage_collector: GenerationUsageCollector,
) -> tuple[GenerationAttemptResult, GenerationTokenUsage, int]:
    result = GenerationAttemptResult(answer="answer", request_retries=1)
    usage = usage_collector.drain_token_usage()
    return result, usage, usage_collector.drain_retry_count()


def accept_runtime_mapping_payloads(
    payload: Mapping[str, object],
) -> tuple[
    GenerationSnapshot,
    RouteSnapshot,
    RetrievalOutcome,
    QueryTraceEvent,
]:
    semantic_settings = semantic_runtime_settings(build_test_config())
    return (
        GenerationSnapshot.from_dict(payload),
        RouteSnapshot.from_dict(payload, semantic_settings=semantic_settings),
        RetrievalOutcome.from_dict(payload, semantic_settings=semantic_settings),
        QueryTraceEvent.from_dict(payload, semantic_settings=semantic_settings),
    )


def accept_json_runtime_ports(
    query_tracer: QueryTracerPort,
    index_module: VectorIndexModulePort,
    payload: JsonObject,
) -> tuple[JsonObject, JsonObject, list[JsonObject], QueryTraceEvent]:
    event = query_tracer.record(
        "question",
        analysis=payload,
        documents=RetrievalOutcome(),
        latency_ms=1.0,
        route_trace=payload,
        graph_trace=payload,
        generation_trace=payload,
    )
    return (
        query_tracer.stats(),
        index_module.get_collection_stats(),
        index_module.similarity_search(
            RetrievalRequest.from_inputs(
                query="question",
                top_k=1,
                candidate_k=1,
                metadata={"filters": payload},
            )
        ),
        event,
    )


def accept_query_plan_calibration_contracts() -> GraphQueryType:
    calibrator = QueryPlanCalibrator(semantic_runtime_settings(build_test_config()))
    profile = QuerySemanticProfile(query_type="path_finding")

    resolved_query_type: GraphQueryType = calibrator.resolve_graph_query_type(
        GraphQueryType.SUBGRAPH,
        profile,
    )

    return resolved_query_type
