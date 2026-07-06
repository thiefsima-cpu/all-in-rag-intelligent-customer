from __future__ import annotations

import importlib
import importlib.util

import pytest

from scripts.gates import GateCheckResult, GateFailureType
from scripts.live_quality_gate.models import (
    LiveQualityCasePolicy,
    LiveQualityResponseMode,
    ManualReviewPolicy,
)
from scripts.live_quality_gate.runtime_models import (
    LiveQualityEvidence,
    LiveQualityObservation,
)


def load_evaluator_module():
    spec = importlib.util.find_spec("scripts.live_quality_gate.evaluator")
    assert spec is not None, "scripts.live_quality_gate.evaluator is missing"
    return importlib.import_module("scripts.live_quality_gate.evaluator")


def deterministic_case_result_type():
    runtime_models = importlib.import_module("scripts.live_quality_gate.runtime_models")
    result_type = getattr(runtime_models, "DeterministicCaseResult", None)
    assert result_type is not None, "DeterministicCaseResult is missing from runtime_models"
    return result_type


def make_case(
    *,
    case_id: str = "grounded_mapo_tofu",
    query_type: str = "single_recipe",
    cuisine: str = "sichuan",
    constraint_types: list[str] | None = None,
    risk_tags: list[str] | None = None,
    response_mode: LiveQualityResponseMode = LiveQualityResponseMode.GROUNDED_ANSWER,
    allowed_strategies: list[str] | None = None,
    required_sources: list[str] | None = None,
    relevant_recipes: dict[str, float] | None = None,
    must_include_facts: list[str] | None = None,
    must_not_claim: list[str] | None = None,
) -> LiveQualityCasePolicy:
    return LiveQualityCasePolicy(
        case_id=case_id,
        query="How do I make mapo tofu?",
        query_type=query_type,
        cuisine=cuisine,
        constraint_types=[] if constraint_types is None else constraint_types,
        risk_tags=[] if risk_tags is None else risk_tags,
        expected_response_mode=response_mode,
        allowed_strategies=["combined"] if allowed_strategies is None else allowed_strategies,
        required_sources=["vector"] if required_sources is None else required_sources,
        relevant_recipes=(
            {"Mapo Tofu": 3.0, "Dan Dan Noodles": 1.0}
            if relevant_recipes is None
            else relevant_recipes
        ),
        must_include_facts=["doubanjiang"] if must_include_facts is None else must_include_facts,
        must_not_claim=(["palace secret recipe"] if must_not_claim is None else must_not_claim),
        judge_rubric={
            "faithfulness": "Use only supported evidence.",
            "answer_relevance": "Answer the recipe question directly.",
        },
        manual_review=ManualReviewPolicy(owner="business-quality", sample=True),
    )


def make_observation(
    *,
    case_id: str = "grounded_mapo_tofu",
    answer: str = "Use doubanjiang with tofu for mapo tofu.",
    strategy: str = "combined",
    evidence: tuple[LiveQualityEvidence, ...] | None = None,
    ranked_recipe_names: tuple[str, ...] = ("Mapo Tofu", "Dan Dan Noodles"),
    sources: frozenset[str] = frozenset({"vector"}),
    fallback_used: bool = False,
    retrieval_degraded: bool = False,
    latency_ms: float = 120.0,
    estimated_cost_usd: float = 0.01234567,
) -> LiveQualityObservation:
    return LiveQualityObservation(
        case_id=case_id,
        answer=answer,
        strategy=strategy,
        evidence=(
            (
                LiveQualityEvidence(
                    recipe_name="Mapo Tofu",
                    source="vector",
                    content="Mapo tofu uses doubanjiang and tofu.",
                    score=0.98,
                ),
            )
            if evidence is None
            else evidence
        ),
        ranked_recipe_names=ranked_recipe_names,
        sources=sources,
        fallback_used=fallback_used,
        retrieval_degraded=retrieval_degraded,
        latency_ms=latency_ms,
        prompt_tokens=101,
        completion_tokens=37,
        total_tokens=138,
        estimated_cost_usd=estimated_cost_usd,
    )


def test_runtime_models_expose_deterministic_case_result_with_judge_overlay() -> None:
    result_type = deterministic_case_result_type()
    scores = {"faithfulness": 0.91}
    result = result_type(
        case_id="grounded_mapo_tofu",
        query_type="single_recipe",
        cuisine="sichuan",
        constraint_types=("weekday",),
        risk_tags=("prompt_injection",),
        response_mode="grounded_answer",
        strategy="combined",
        passed=True,
        response_mode_passed=True,
        failures=(),
        metrics={"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0},
        checks=(GateCheckResult.pass_check("case.grounded_mapo_tofu.deterministic"),),
        observation=make_observation(),
    )

    judged = result.with_judge_result(False, scores)
    scores["faithfulness"] = 0.1

    assert result.checks_by_name == {
        "case.grounded_mapo_tofu.deterministic": result.checks[0],
    }
    assert judged is not result
    assert judged.passed is False
    assert judged.judge_passed is False
    assert judged.judge_scores == {"faithfulness": 0.91}
    assert judged.failures == result.failures
    assert judged.checks == result.checks


def test_runtime_models_judge_overlay_uses_deterministic_baseline_and_copies_mutables() -> None:
    result_type = deterministic_case_result_type()
    source_metrics = {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
    result = result_type(
        case_id="grounded_mapo_tofu",
        query_type="single_recipe",
        cuisine="sichuan",
        constraint_types=("weekday",),
        risk_tags=("prompt_injection",),
        response_mode="grounded_answer",
        strategy="combined",
        passed=True,
        response_mode_passed=True,
        failures=(),
        metrics=source_metrics,
        checks=(GateCheckResult.pass_check("case.grounded_mapo_tofu.deterministic"),),
        observation=make_observation(),
    )

    failed_scores = {"faithfulness": 0.2}
    failed = result.with_judge_result(False, failed_scores)
    passed_scores = {"faithfulness": 0.95}
    recovered = failed.with_judge_result(True, passed_scores)

    failed_scores["faithfulness"] = 0.0
    passed_scores["faithfulness"] = 0.0
    source_metrics["recall_at_k"] = 0.5

    assert failed.passed is False
    assert failed.judge_passed is False
    assert failed.judge_scores == {"faithfulness": 0.2}
    assert recovered.passed is True
    assert recovered.judge_passed is True
    assert recovered.judge_scores == {"faithfulness": 0.95}
    assert recovered.metrics == {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
    assert recovered.metrics is not failed.metrics


def test_runtime_models_freeze_metrics_and_judge_score_mappings() -> None:
    result_type = deterministic_case_result_type()
    result = result_type(
        case_id="grounded_mapo_tofu",
        query_type="single_recipe",
        cuisine="sichuan",
        constraint_types=("weekday",),
        risk_tags=("prompt_injection",),
        response_mode="grounded_answer",
        strategy="combined",
        passed=True,
        response_mode_passed=True,
        failures=(),
        metrics={"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0},
        checks=(GateCheckResult.pass_check("case.grounded_mapo_tofu.deterministic"),),
        observation=make_observation(),
    )
    judged = result.with_judge_result(True, {"faithfulness": 0.91})

    with pytest.raises(TypeError):
        result.metrics["recall_at_k"] = 0.5

    with pytest.raises(TypeError):
        judged.judge_scores["faithfulness"] = 0.1

    assert result.metrics == {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
    assert judged.judge_scores == {"faithfulness": 0.91}


def test_evaluate_deterministic_case_passes_grounded_case_and_deduplicates_ranked_recipes() -> None:
    evaluator = load_evaluator_module()
    case = make_case()
    observation = make_observation(
        ranked_recipe_names=("Mapo Tofu", "Mapo Tofu", "Dan Dan Noodles"),
        sources=frozenset({"vector", "graph"}),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=2)

    assert result.case_id == "grounded_mapo_tofu"
    assert result.response_mode == "grounded_answer"
    assert result.passed is True
    assert result.response_mode_passed is True
    assert result.failures == ()
    assert result.metrics == {"recall_at_k": 1.0, "mrr": 1.0, "ndcg_at_k": 1.0}
    check = result.checks_by_name["case.grounded_mapo_tofu.deterministic"]
    assert check.code == "DETERMINISTIC_QUALITY_OK"
    assert check.failure_type is None


def test_evaluate_deterministic_case_does_not_require_more_positive_hits_than_top_k() -> None:
    evaluator = load_evaluator_module()
    case = make_case(
        relevant_recipes={
            "Mapo Tofu": 3.0,
            "Dan Dan Noodles": 2.0,
            "Kung Pao Chicken": 1.0,
        }
    )
    observation = make_observation(
        ranked_recipe_names=("Mapo Tofu", "Dan Dan Noodles", "Unrelated Recipe"),
        sources=frozenset({"vector", "graph"}),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=2)

    assert result.passed is True
    assert "missing_relevant_recipes" not in result.failures
    assert result.metrics["recall_at_k"] == 2 / 3
    assert result.metrics["ndcg_at_k"] == 1.0


def test_evaluate_deterministic_case_reports_strategy_and_source_mismatches() -> None:
    evaluator = load_evaluator_module()
    case = make_case(required_sources=["vector", "graph"])
    observation = make_observation(
        strategy="hybrid_traditional",
        sources=frozenset({"vector"}),
        ranked_recipe_names=("Mapo Tofu",),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=2)

    assert result.passed is False
    assert result.response_mode_passed is True
    assert result.failures == (
        "missing_relevant_recipes",
        "missing_required_sources",
        "strategy_mismatch",
    )
    check = result.checks_by_name["case.grounded_mapo_tofu.deterministic"]
    assert check.failure_type is GateFailureType.QUALITY_REGRESSION
    assert check.code == "DETERMINISTIC_QUALITY_FAILED"
    assert check.actual == [
        "missing_relevant_recipes",
        "missing_required_sources",
        "strategy_mismatch",
    ]


def test_evaluate_deterministic_case_flags_answer_expectation_and_resilience_failures() -> None:
    evaluator = load_evaluator_module()
    case = make_case(must_include_facts=["doubanjiang"], must_not_claim=["palace secret recipe"])
    observation = make_observation(
        answer="This palace secret recipe skips the evidence entirely.",
        evidence=(),
        fallback_used=True,
        retrieval_degraded=True,
        ranked_recipe_names=("Unrelated Recipe",),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=1)

    assert result.passed is False
    assert result.response_mode_passed is False
    assert result.failures == (
        "fallback_used",
        "forbidden_claim",
        "missing_relevant_recipes",
        "missing_required_fact",
        "response_mode_mismatch",
        "retrieval_degraded",
    )


def test_evaluate_deterministic_case_handles_abstention_without_ranking_metrics() -> None:
    evaluator = load_evaluator_module()
    case = make_case(
        case_id="injection_secret_recipe",
        query_type="safety",
        cuisine="general",
        constraint_types=["evidence_grounding"],
        risk_tags=["prompt_injection"],
        response_mode=LiveQualityResponseMode.NO_EVIDENCE,
        allowed_strategies=["graph_rag", "combined"],
        required_sources=[],
        relevant_recipes={"Unsupported Recipe": 0.0},
        must_include_facts=["insufficient evidence"],
    )
    observation = make_observation(
        case_id="injection_secret_recipe",
        answer="I found insufficient evidence for that request.",
        strategy="graph_rag",
        evidence=(
            LiveQualityEvidence(
                recipe_name="Invented Recipe",
                source="graph",
                content="Unsupported evidence.",
                score=0.4,
            ),
        ),
        ranked_recipe_names=("Invented Recipe",),
        sources=frozenset({"graph"}),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=3)

    assert result.passed is False
    assert result.response_mode_passed is False
    assert result.metrics == {"recall_at_k": None, "mrr": None, "ndcg_at_k": None}
    assert result.failures == ("response_mode_mismatch", "unexpected_evidence")


def test_evaluate_deterministic_case_relies_on_abstention_envelope_and_fact_checks() -> None:
    evaluator = load_evaluator_module()
    case = make_case(
        case_id="needs_clarification",
        query_type="constraint",
        cuisine="general",
        response_mode=LiveQualityResponseMode.CLARIFICATION,
        allowed_strategies=["combined"],
        required_sources=[],
        relevant_recipes={"Unsupported Recipe": 0.0},
        must_include_facts=["tell me your dietary constraints"],
        must_not_claim=["I already know your constraints"],
    )
    observation = make_observation(
        case_id="needs_clarification",
        answer="Please tell me your dietary constraints so I can help safely.",
        evidence=(),
        ranked_recipe_names=(),
        sources=frozenset(),
    )

    result = evaluator.evaluate_deterministic_case(case, observation, top_k=2)

    assert result.response_mode_passed is True
    assert result.failures == ()
    assert result.metrics == {"recall_at_k": None, "mrr": None, "ndcg_at_k": None}


def test_aggregate_live_quality_metrics_combines_totals_and_slice_views() -> None:
    evaluator = load_evaluator_module()
    grounded_case = make_case(
        constraint_types=["weekday"],
        risk_tags=["safety_sensitive"],
    )
    abstention_case = make_case(
        case_id="injection_secret_recipe",
        query_type="safety",
        cuisine="general",
        constraint_types=["evidence_grounding"],
        risk_tags=["prompt_injection"],
        response_mode=LiveQualityResponseMode.NO_EVIDENCE,
        allowed_strategies=["graph_rag", "combined"],
        required_sources=[],
        relevant_recipes={"Unsupported Recipe": 0.0},
        must_include_facts=["insufficient evidence"],
    )
    degraded_case = make_case(
        case_id="slow_grounded_case",
        query_type="multi_recipe",
        cuisine="hunan",
        allowed_strategies=["hybrid_traditional"],
        required_sources=["vector"],
        relevant_recipes={"Mapo Tofu": 3.0, "Dan Dan Noodles": 1.0},
    )

    grounded_result = evaluator.evaluate_deterministic_case(
        grounded_case,
        make_observation(
            sources=frozenset({"vector", "graph"}),
            ranked_recipe_names=("Mapo Tofu", "Mapo Tofu", "Dan Dan Noodles"),
            latency_ms=120.0,
            estimated_cost_usd=0.01,
        ),
        top_k=2,
    ).with_judge_result(True, {"faithfulness": 0.9, "answer_relevance": 0.8})
    abstention_result = evaluator.evaluate_deterministic_case(
        abstention_case,
        make_observation(
            case_id="injection_secret_recipe",
            answer="There is insufficient evidence for that request.",
            strategy="graph_rag",
            evidence=(),
            ranked_recipe_names=(),
            sources=frozenset(),
            latency_ms=80.0,
            estimated_cost_usd=0.02,
        ),
        top_k=2,
    ).with_judge_result(False, {"faithfulness": 0.6, "answer_relevance": 0.7})
    degraded_result = evaluator.evaluate_deterministic_case(
        degraded_case,
        make_observation(
            case_id="slow_grounded_case",
            strategy="hybrid_traditional",
            answer="Use doubanjiang with tofu for mapo tofu.",
            ranked_recipe_names=("Mapo Tofu",),
            fallback_used=True,
            retrieval_degraded=True,
            latency_ms=400.0,
            estimated_cost_usd=0.03,
        ),
        top_k=2,
    )

    metrics = evaluator.aggregate_live_quality_metrics(
        [grounded_result, abstention_result, degraded_result]
    )

    assert metrics["case_count"] == 3
    assert metrics["pass_rate"] == 1 / 3
    assert metrics["deterministic_pass_rate"] == 2 / 3
    assert metrics["judge_pass_rate"] == 0.5
    assert metrics["recall_at_k"] == 0.75
    assert metrics["mrr"] == 1.0
    assert metrics["ndcg_at_k"] == 0.9586597063564786
    assert metrics["fallback_rate"] == 1 / 3
    assert metrics["retrieval_degradation_rate"] == 1 / 3
    assert metrics["p95_latency_ms"] == 400.0
    assert metrics["estimated_cost_usd"] == 0.06
    assert metrics["avg_judge_scores"] == {
        "faithfulness": 0.75,
        "answer_relevance": 0.75,
    }
    assert metrics["by_query_type"]["single_recipe"]["case_count"] == 1
    assert metrics["by_query_type"]["safety"]["judge_pass_rate"] == 0.0
    assert metrics["by_response_mode"]["grounded_answer"]["deterministic_pass_rate"] == 0.5
    assert metrics["by_response_mode"]["grounded_answer"]["recall_at_k"] == 0.75
    assert metrics["by_response_mode"]["grounded_answer"]["mrr"] == 1.0
    assert metrics["by_response_mode"]["grounded_answer"]["ndcg_at_k"] == 0.9586597063564786
    assert metrics["by_response_mode"]["grounded_answer"]["fallback_rate"] == 0.5
    assert metrics["by_response_mode"]["grounded_answer"]["retrieval_degradation_rate"] == 0.5
    assert metrics["by_response_mode"]["grounded_answer"]["p95_latency_ms"] == 400.0
    assert metrics["by_response_mode"]["grounded_answer"]["estimated_cost_usd"] == 0.04
    assert metrics["by_strategy"]["graph_rag"]["avg_judge_scores"] == {
        "faithfulness": 0.6,
        "answer_relevance": 0.7,
    }
    assert metrics["by_strategy"]["graph_rag"]["recall_at_k"] is None
    assert metrics["by_strategy"]["graph_rag"]["mrr"] is None
    assert metrics["by_strategy"]["graph_rag"]["ndcg_at_k"] is None
    assert metrics["by_strategy"]["graph_rag"]["fallback_rate"] == 0.0
    assert metrics["by_strategy"]["graph_rag"]["retrieval_degradation_rate"] == 0.0
    assert metrics["by_strategy"]["graph_rag"]["p95_latency_ms"] == 80.0
    assert metrics["by_strategy"]["graph_rag"]["estimated_cost_usd"] == 0.02
    assert metrics["by_constraint_type"]["weekday"]["pass_rate"] == 1.0
    assert metrics["by_risk_tag"]["prompt_injection"]["deterministic_pass_rate"] == 1.0


def test_aggregate_live_quality_metrics_returns_stable_empty_totals() -> None:
    evaluator = load_evaluator_module()

    metrics = evaluator.aggregate_live_quality_metrics([])

    assert metrics == {
        "case_count": 0,
        "pass_rate": 0.0,
        "deterministic_pass_rate": 0.0,
        "judge_pass_rate": None,
        "recall_at_k": None,
        "mrr": None,
        "ndcg_at_k": None,
        "fallback_rate": 0.0,
        "retrieval_degradation_rate": 0.0,
        "p95_latency_ms": 0.0,
        "estimated_cost_usd": 0.0,
        "avg_judge_scores": {},
        "by_query_type": {},
        "by_cuisine": {},
        "by_constraint_type": {},
        "by_risk_tag": {},
        "by_response_mode": {},
        "by_strategy": {},
    }
