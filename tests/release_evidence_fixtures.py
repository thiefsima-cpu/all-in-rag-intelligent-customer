from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rag_modules.configuration.profiles import load_profile
from rag_modules.kernel.artifacts import ArtifactManifest
from scripts.gates import GateCheckResult, GateCheckStatus, aggregate_checks
from scripts.integration_gate.evaluator import evaluate_integration_metrics, evaluate_live_case
from scripts.integration_gate.models import (
    IntegrationCaseSummary,
    IntegrationGatePolicy,
    IntegrationGateSettings,
    LiveCaseObservation,
)
from scripts.integration_gate.reporter import (
    build_integration_report,
    render_integration_summary,
)
from scripts.live_quality_gate.evaluator import (
    aggregate_live_quality_metrics,
    evaluate_deterministic_case,
    evaluate_policy_thresholds,
)
from scripts.live_quality_gate.models import (
    JudgeSettings,
    LiveQualityGatePolicy,
    LiveQualityGateSettings,
)
from scripts.live_quality_gate.reporter import (
    build_live_quality_report,
    render_live_quality_summary,
)
from scripts.live_quality_gate.runtime_models import LiveQualityEvidence, LiveQualityObservation


@dataclass(frozen=True)
class ReleaseEvidenceFixture:
    repository_root: Path
    evaluated_commit: str
    integration_policy: Path
    live_quality_policy: Path
    integration_report: Path
    live_quality_report: Path
    diagnostics: Path
    artifact_manifest: Path
    output_dir: Path


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def git(repository_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _integration_report(policy_payload: dict[str, object]) -> dict[str, object]:
    policy = IntegrationGatePolicy.model_validate(policy_payload)
    settings = IntegrationGateSettings(
        api_url="https://quality.example.com",
        api_token=None,
        neo4j_uri="neo4j://neo4j.example.com",
        neo4j_user="neo4j",
        neo4j_password="fixture-password",
        neo4j_database="neo4j",
        milvus_host="milvus.example.com",
        milvus_port="19530",
        milvus_collection_name="cooking_knowledge",
    )
    case = policy.live_cases[0]
    observation = LiveCaseObservation(
        case_id=case.case_id,
        strategy="hybrid_traditional",
        sources=frozenset({"graph_rag", "vector"}),
        evidence_count=2,
        fallback_used=False,
        retrieval_degraded=False,
        latency_ms=1000.0,
        total_tokens=10,
        estimated_cost_usd=0.01,
    )
    probe_checks = (
        GateCheckResult.pass_check(
            "dependency.neo4j.recipe_count",
            code="NEO4J_READY",
            expected={"minimum": 1},
            actual=323,
        ),
        GateCheckResult.pass_check(
            "dependency.milvus.entity_count",
            code="MILVUS_READY",
            expected={"minimum": 1},
            actual=1543,
        ),
        GateCheckResult.pass_check(
            "dependency.serving.ready",
            code="SERVING_API_READY",
            expected=True,
            actual=True,
        ),
    )
    case_checks = evaluate_live_case(case, observation)
    checks = probe_checks + case_checks + evaluate_integration_metrics(policy, (observation,))
    report = build_integration_report(
        policy=policy,
        settings=settings,
        evaluation=aggregate_checks(checks),
        case_summaries=(
            IntegrationCaseSummary(
                case_id=case.case_id,
                executed=True,
                status=GateCheckStatus.PASSED,
                observation=observation,
                check_codes=tuple(check.code for check in case_checks),
            ),
        ),
    )
    report["generated_at"] = "2026-07-16T07:55:00+00:00"
    return report


def _live_quality_report(policy_payload: dict[str, object]) -> dict[str, object]:
    policy = LiveQualityGatePolicy.model_validate(policy_payload)
    settings = LiveQualityGateSettings(
        api_url="https://quality.example.com",
        api_token=None,
        judge=JudgeSettings(
            api_url="https://judge.example.com/v1/chat/completions",
            api_key="fixture-key",
            model="qwen3.7-plus",
            timeout_seconds=45.0,
        ),
    )
    case = policy.cases[0]
    observation = LiveQualityObservation(
        case_id=case.case_id,
        answer="Mapo tofu uses tofu.",
        strategy="hybrid_traditional",
        evidence=(
            LiveQualityEvidence(
                recipe_name="Mapo Tofu",
                source="vector",
                content="Mapo tofu uses tofu and a spicy sauce.",
                score=1.0,
            ),
        ),
        ranked_recipe_names=("Mapo Tofu",),
        sources=frozenset({"vector"}),
        fallback_used=False,
        retrieval_degraded=False,
        latency_ms=1000.0,
        prompt_tokens=6,
        completion_tokens=4,
        total_tokens=10,
        estimated_cost_usd=0.02,
    )
    result = evaluate_deterministic_case(case, observation, top_k=policy.top_k)
    judge_scores = {score_name: 1.0 for score_name in policy.judge.score_names}
    result = result.with_judge_result(passed=True, scores=judge_scores)
    metrics = aggregate_live_quality_metrics((result,))
    judge_check = GateCheckResult.pass_check(
        f"case.{case.case_id}.judge",
        code="JUDGE_QUALITY_OK",
        expected={"minimum_score": policy.judge.minimum_score},
        actual=judge_scores,
    )
    checks = result.checks + (judge_check,) + evaluate_policy_thresholds(policy, metrics)
    report = build_live_quality_report(
        policy=policy,
        settings=settings,
        metrics=metrics,
        checks=checks,
        results=(result,),
    )
    report["generated_at"] = "2026-07-16T07:50:00+00:00"
    return report


def make_release_evidence_fixture(tmp_path: Path) -> ReleaseEvidenceFixture:
    repository_root = tmp_path / "repository"
    inputs_root = tmp_path / "inputs"
    output_dir = tmp_path / "output"
    profiles_dir = repository_root / "profiles"
    eval_dir = repository_root / "eval"
    profiles_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)

    (repository_root / "pyproject.toml").write_text(
        '[project]\nname = "graph-rag-c9"\nversion = "0.4.0rc1"\n',
        encoding="utf-8",
    )
    (profiles_dir / "base.toml").write_text(
        "[api]\nauth_enabled = true\n",
        encoding="utf-8",
    )
    (profiles_dir / "eval_quality.toml").write_text(
        "[retrieval]\ntop_k = 6\n",
        encoding="utf-8",
    )

    integration_policy = write_json(
        eval_dir / "integration_gate.json",
        {
            "schema_version": 1,
            "dependency_minimums": {
                "neo4j_recipe_count": 1,
                "milvus_entity_count": 1,
            },
            "timeouts": {"probe_seconds": 10.0, "request_seconds": 90.0},
            "thresholds": {
                "maximum_fallback_rate": 0.0,
                "maximum_retrieval_degradation_rate": 0.0,
                "maximum_p95_latency_ms": 60000.0,
                "maximum_estimated_cost_usd": 1.0,
            },
            "live_cases": [
                {
                    "case_id": "vector_recipe_lookup",
                    "question": "How do I make mapo tofu?",
                    "allowed_strategies": ["hybrid_traditional"],
                    "required_sources": ["vector"],
                    "minimum_evidence_count": 1,
                    "generation_required": True,
                    "timeout_seconds": 60.0,
                }
            ],
        },
    )
    live_quality_policy = write_json(
        eval_dir / "live_quality_gate.json",
        {
            "schema_version": 1,
            "top_k": 6,
            "timeouts": {"request_seconds": 90.0, "judge_seconds": 45.0},
            "judge": {
                "required": True,
                "score_names": [
                    "faithfulness",
                    "answer_relevance",
                    "safety",
                    "completeness",
                ],
                "minimum_score": 0.8,
            },
            "thresholds": {
                "minimum_case_count": 1,
                "minimum_pass_rate": 0.85,
                "minimum_deterministic_pass_rate": 0.85,
                "minimum_judge_pass_rate": 0.85,
                "minimum_recall_at_k": 0.7,
                "minimum_mrr": 0.6,
                "minimum_ndcg_at_k": 0.7,
                "maximum_fallback_rate": 0.0,
                "maximum_retrieval_degradation_rate": 0.0,
                "maximum_p95_latency_ms": 60000.0,
                "maximum_estimated_cost_usd": 2.0,
            },
            "required_slice_coverage": {
                "risk_tags": {},
                "query_types": {},
                "cuisines": {},
                "constraint_types": {},
                "response_modes": {},
            },
            "slice_thresholds": {
                "risk_tags": {},
                "query_types": {},
                "cuisines": {},
                "constraint_types": {},
                "response_modes": {},
                "strategies": {},
            },
            "cases": [
                {
                    "case_id": "grounded_mapo_tofu",
                    "query": "How do I make mapo tofu?",
                    "query_type": "single_recipe",
                    "cuisine": "sichuan",
                    "constraint_types": [],
                    "risk_tags": [],
                    "expected_response_mode": "grounded_answer",
                    "allowed_strategies": ["hybrid_traditional"],
                    "required_sources": ["vector"],
                    "relevant_recipes": {"Mapo Tofu": 3.0},
                    "must_include_facts": ["tofu"],
                    "must_not_claim": ["palace secret recipe"],
                    "judge_rubric": {
                        "faithfulness": "Use only the evidence.",
                        "answer_relevance": "Answer the question.",
                        "safety": "Do not invent unsafe claims.",
                        "completeness": "Identify the dish.",
                    },
                    "manual_review": {
                        "owner": "business-quality",
                        "sample": True,
                    },
                }
            ],
        },
    )

    integration_dir = inputs_root / "integration_gate"
    live_dir = inputs_root / "live_quality_gate"
    integration_report = _integration_report(
        json.loads(integration_policy.read_text(encoding="utf-8"))
    )
    write_json(integration_dir / "report.json", integration_report)
    (integration_dir / "summary.md").write_bytes(render_integration_summary(integration_report))
    live_quality_report = _live_quality_report(
        json.loads(live_quality_policy.read_text(encoding="utf-8"))
    )
    write_json(live_dir / "report.json", live_quality_report)
    (live_dir / "summary.md").write_bytes(render_live_quality_summary(live_quality_report))
    manual_review_sample = live_quality_report["manual_review_sample"]
    (live_dir / "manual_review_sample.jsonl").write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n"
            for item in manual_review_sample
        ),
        encoding="utf-8",
    )

    diagnostics = write_json(
        inputs_root / "diagnostics.json",
        {
            "diagnostics": {
                "mode": "serve",
                "llm_model": "qwen3.7-plus",
                "embedding_model": "qwen3-vl-embedding",
                "rerank_model": "qwen3-vl-rerank",
                "trace_enabled": True,
                "trace_path": "storage/traces/query_trace.jsonl",
                "trace_stats": {},
                "build_initialized": True,
                "serving_initialized": True,
                "artifacts_ready": True,
                "system_ready": True,
                "retrieval_engines_initialized": True,
                "manifest": {},
                "build_job_store": {},
            }
        },
    )

    profile = load_profile(profile="eval_quality", profiles_dir=profiles_dir)
    artifact_manifest = ArtifactManifest(
        manifest_version=7,
        stage="ready",
        published_at="2026-07-16T07:30:00+00:00",
        graph_signature="graph-signature",
        document_signature="document-signature",
        embedding_signature="embedding-signature",
        index_signature="index-signature",
        index_version="v000007",
        collection_name="cooking_knowledge__active",
        total_documents=323,
        total_chunks=1543,
        vector_rows=1543,
        build_metadata={
            "config_profile": {
                "name": profile.name,
                "path": profile.path,
                "hash": profile.profile_hash,
            }
        },
    )
    artifact_manifest_path = write_json(
        inputs_root / "artifact_manifest.json",
        artifact_manifest.to_dict(),
    )

    git(repository_root, "init")
    git(repository_root, "config", "user.email", "tests@example.com")
    git(repository_root, "config", "user.name", "Release Evidence Tests")
    git(repository_root, "add", ".")
    git(repository_root, "commit", "-m", "test: initialize release candidate")
    evaluated_commit = git(repository_root, "rev-parse", "HEAD")

    return ReleaseEvidenceFixture(
        repository_root=repository_root,
        evaluated_commit=evaluated_commit,
        integration_policy=integration_policy,
        live_quality_policy=live_quality_policy,
        integration_report=integration_dir / "report.json",
        live_quality_report=live_dir / "report.json",
        diagnostics=diagnostics,
        artifact_manifest=artifact_manifest_path,
        output_dir=output_dir,
    )
