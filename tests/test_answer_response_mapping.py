from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

from rag_modules.app.services.answer_models import QuestionAnswerResult
from rag_modules.contracts import (
    EvidenceDocument,
    QueryPlan,
    QuerySemanticProfile,
    QuerySemanticScoreBreakdown,
    RetrievalRequest,
)
from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.interfaces.api.answer_models import AnswerPayloadModel, PublicAnswerPayloadModel
from rag_modules.runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    GraphTraceEventSnapshot,
    ModelSuiteSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteResolution,
    RouteSnapshot,
    RouteStageSnapshot,
    SearchStrategy,
)


def test_answer_payload_maps_typed_response_without_to_dict() -> None:
    response = _complete_result().to_response()
    blocked_types = (
        AnswerContext,
        EvidenceDocument,
        GenerationSnapshot,
        GraphRetrievalSnapshot,
        QueryAnalysis,
        QueryConstraints,
        QueryDiagnostics,
        QueryPlan,
        QuerySemanticProfile,
        QueryTraceEvent,
        RetrievalRequest,
        RetrievalOutcome,
        RouteResolution,
        RouteSnapshot,
    )

    with ExitStack() as stack:
        for dto_type in blocked_types:
            stack.enter_context(
                patch.object(dto_type, "to_dict", side_effect=AssertionError("DTO serialized"))
            )
        payload = AnswerPayloadModel.from_dto(response)

    assert payload.summary.answer == "grounded answer"
    assert payload.grounding.retrieval_outcome.strategy == "combined"
    assert payload.traces.generation_trace.total_tokens == 12
    assert payload.traces.trace_event.diagnostics.overall_bucket == "healthy"


def test_typed_mapper_matches_compatibility_payload() -> None:
    response = _complete_result().to_response()

    assert AnswerPayloadModel.from_dto(response).model_dump() == response.to_dict()


def test_public_answer_payload_maps_typed_response_without_traces() -> None:
    response = _complete_result().to_response()

    payload = PublicAnswerPayloadModel.from_dto(response)

    assert payload.summary.answer == "grounded answer"
    assert payload.grounding.retrieval_outcome.strategy == "combined"
    assert payload.diagnostics.diagnostics.overall_bucket == "healthy"
    assert "traces" not in payload.model_dump()


def test_public_answer_payload_can_be_derived_from_debug_payload() -> None:
    response = _complete_result().to_response()
    debug_payload = AnswerPayloadModel.from_dto(response)

    payload = PublicAnswerPayloadModel.from_debug_payload(debug_payload)

    assert payload.model_dump() == {
        "summary": debug_payload.summary.model_dump(),
        "grounding": debug_payload.grounding.model_dump(),
        "diagnostics": debug_payload.diagnostics.model_dump(),
    }


def _complete_result() -> QuestionAnswerResult:
    question = "why does mapo tofu work"
    constraints = QueryConstraints(
        include_terms=["tofu"],
        ingredients=["tofu", "doubanjiang"],
        max_cook_minutes=30,
    )
    score_breakdown = QuerySemanticScoreBreakdown(
        relation_hit_count=1,
        constraint_hit_count=1,
        relationship_intensity=0.73,
        complexity=0.71,
    )
    semantic_profile = QuerySemanticProfile(
        query=question,
        query_type="path",
        source_entities=["tofu"],
        target_entities=["doubanjiang"],
        relation_types=["CONTRIBUTES_TO"],
        entity_keywords=["tofu"],
        topic_keywords=["texture"],
        constraints=constraints.to_dict(),
        complexity=0.71,
        relationship_intensity=0.73,
        reasoning_required=True,
        needs_recipe_recommendation=True,
        recommendation_hits=["recommend"],
        relation_hits=["because"],
        constraint_hits=["under 30 minutes"],
        structural_hits=["why"],
        fast_rule_hits=["tofu"],
        score_breakdown=score_breakdown,
    )
    query_plan = QueryPlan(
        query=question,
        intent="qa",
        complexity=0.71,
        relationship_intensity=0.73,
        reasoning_required=True,
        strategy="combined",
        confidence=0.91,
        reasoning="fixture",
        entity_keywords=["tofu"],
        topic_keywords=["texture"],
        graph_query_type="path",
        source_entities=["tofu"],
        target_entities=["doubanjiang"],
        relation_types=["CONTRIBUTES_TO"],
        max_depth=2,
        constraints=constraints,
        needs_recipe_recommendation=True,
        answer_style="grounded",
        used_cache=True,
        planner_mode="fixture",
        semantic_profile=semantic_profile,
        validation_errors=["ignored-warning"],
    )
    retrieval_request = RetrievalRequest.from_inputs(
        query=question,
        top_k=3,
        candidate_k=6,
        strategy="combined",
        constraints=constraints,
        query_plan=query_plan,
        entity_keywords=["tofu"],
        topic_keywords=["texture"],
        metadata={"request": "fixture"},
    )
    evidence = EvidenceDocument(
        content="Mapo tofu balances tofu and chili bean paste.",
        node_id="node-1",
        recipe_name="mapo tofu",
        node_type="recipe",
        score=0.95,
        search_type="graph",
        search_method="path",
        retrieval_level="recipe",
        doc_id="doc-1",
        recipe_id="recipe-1",
        source="graph",
        evidence_type="graph_relation",
        matched_terms=["tofu"],
        graph_evidence={"edge": "CONTRIBUTES_TO"},
        recipe_graph_evidence={"recipe": "mapo tofu"},
        constraint_evidence={"cook_minutes": 20},
        evidence_units=[{"claim": "tofu carries the sauce"}],
        route_strategy="combined",
        metadata={"rank": 1},
    )
    route_trace = RouteSnapshot(
        query=question,
        strategy="combined",
        requested_top_k=3,
        retrieval_request=retrieval_request,
        stages={
            "plan": RouteStageSnapshot(
                latency_ms=1.2,
                doc_count=0,
                sources={"planner": 1},
                details={"used_cache": True},
            ),
            "combined": RouteStageSnapshot(
                latency_ms=2.4,
                doc_count=1,
                sources={"graph": 1},
                details={"graph_doc_count": 1, "traditional_doc_count": 0},
            ),
        },
        total_latency_ms=5.6,
        final_doc_count=1,
    )
    retrieval_outcome = RetrievalOutcome(
        query=question,
        strategy="combined",
        evidence_documents=[evidence],
        route_trace=route_trace,
        metadata={"ranker": "fixture"},
    )
    analysis = QueryAnalysis(
        query_complexity=0.71,
        relationship_intensity=0.73,
        reasoning_required=True,
        entity_count=2,
        recommended_strategy=SearchStrategy.COMBINED,
        confidence=0.91,
        reasoning="fixture",
        semantic_profile=semantic_profile,
    )
    understanding = QueryUnderstandingSnapshot(
        query=question,
        query_plan=query_plan,
        analysis=analysis,
        constraints=constraints,
        semantic_profile=semantic_profile,
        metadata={"planner": "fixture"},
    )
    route_resolution = RouteResolution(
        understanding=understanding,
        retrieval=retrieval_outcome,
        metadata={"route": "combined"},
    )
    answer_context = AnswerContext.from_route_resolution(
        route_resolution,
        evidence_package={"items": [{"claim": "tofu carries the sauce"}]},
        metadata={"generator": "fixture"},
    )
    graph_trace = GraphRetrievalSnapshot(
        query=question,
        strategy="combined",
        requested_top_k=3,
        retrieval_request=retrieval_request,
        query_type="path",
        source_entities=["tofu"],
        target_entities=["doubanjiang"],
        relation_types=["CONTRIBUTES_TO"],
        sub_questions=["why sauce works"],
        path_count=1,
        subgraph_count=1,
        reasoning_patterns=["cause"],
        reasoning_chain_count=1,
        evidence_unit_count=1,
        doc_count=1,
        retrieval_plan={"max_depth": 2},
        events=[
            GraphTraceEventSnapshot(
                name="expand",
                status="ok",
                latency_ms=1.3,
                details={"paths": 1},
            )
        ],
        total_latency_ms=3.4,
    )
    generation_trace = GenerationSnapshot(
        status="success",
        mode="two_stage",
        decision_reason="grounded",
        total_evidence_items=2,
        selected_evidence_items=1,
        plan_latency_ms=1.0,
        compose_latency_ms=2.0,
        total_latency_ms=4.0,
        provider_latency_ms=3.2,
        prompt_tokens=7,
        completion_tokens=5,
        total_tokens=12,
        estimated_cost_usd=0.0012,
        token_usage_source="fixture",
    )
    diagnostics = QueryDiagnostics(
        retrieval_bucket="healthy",
        generation_bucket="healthy",
        overall_bucket="healthy",
    )
    trace_event = QueryTraceEvent(
        query_id="query-1",
        timestamp=123,
        query=question,
        strategy="combined",
        latency_ms=9.9,
        plan={"strategy": "combined"},
        models=ModelSuiteSnapshot(llm="llm", embedding="embedding", rerank="rerank"),
        retrieval=RetrievalTraceSnapshot(
            doc_count=1,
            evidence=[{"recipe_name": "mapo tofu", "score": 0.95}],
            route_trace=route_trace,
            graph_trace=graph_trace,
        ),
        generation=generation_trace,
        diagnostics=diagnostics,
        answer=AnswerTraceSnapshot(chars=15, preview="grounded answer"),
    )
    return QuestionAnswerResult(
        answer="grounded answer",
        analysis=analysis,
        retrieval_outcome=retrieval_outcome,
        answer_context=answer_context,
        route_resolution=route_resolution,
        latency_ms=9.9,
        route_trace=route_trace,
        graph_trace=graph_trace,
        generation_trace=generation_trace,
        trace_event=trace_event,
    )
