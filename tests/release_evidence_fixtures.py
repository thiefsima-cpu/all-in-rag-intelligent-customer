from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rag_modules.configuration.profiles import load_profile
from rag_modules.kernel.artifacts import ArtifactManifest


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
    write_json(
        integration_dir / "report.json",
        {
            "schema_version": 1,
            "generated_at": "2026-07-16T07:55:00+00:00",
            "passed": True,
            "target": {
                "api_host": "quality.example.com",
                "neo4j_host": "neo4j.example.com",
                "milvus_host": "milvus.example.com",
            },
            "metrics": {
                "check_count": 10,
                "failed_count": 0,
                "blocked_count": 0,
                "case_count": 1,
                "executed_case_count": 1,
                "observation_count": 1,
                "failure_type_counts": {},
                "total_estimated_cost_usd": 0.01,
                "max_latency_ms": 1000.0,
            },
            "checks": [],
            "cases": [],
            "artifacts": {
                "report_json": "report.json",
                "summary_md": "summary.md",
            },
        },
    )
    (integration_dir / "summary.md").write_text(
        "# Real-Dependency Integration Gate\n\nStatus: PASS\n",
        encoding="utf-8",
    )
    write_json(
        live_dir / "report.json",
        {
            "schema_version": 1,
            "generated_at": "2026-07-16T07:50:00+00:00",
            "passed": True,
            "target": {
                "api_host": "quality.example.com",
                "judge_host": "judge.example.com",
            },
            "top_k": 6,
            "metrics": {
                "case_count": 1,
                "pass_rate": 1.0,
                "deterministic_pass_rate": 1.0,
                "judge_pass_rate": 1.0,
                "recall_at_k": 1.0,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
                "fallback_rate": 0.0,
                "retrieval_degradation_rate": 0.0,
                "p95_latency_ms": 1000.0,
                "estimated_cost_usd": 0.02,
                "avg_judge_scores": {
                    "faithfulness": 1.0,
                    "answer_relevance": 1.0,
                },
                "by_query_type": {},
                "by_cuisine": {},
                "by_constraint_type": {},
                "by_risk_tag": {},
                "by_response_mode": {},
                "by_strategy": {},
            },
            "failure_type_counts": {},
            "checks": [],
            "cases": [],
            "manual_review_sample_count": 1,
            "manual_review_sample": [],
            "artifacts": {
                "report_json": "report.json",
                "summary_md": "summary.md",
                "manual_review_sample_jsonl": "manual_review_sample.jsonl",
            },
        },
    )
    (live_dir / "summary.md").write_text(
        "# Live Quality Gate\n\nStatus: PASS\n",
        encoding="utf-8",
    )
    (live_dir / "manual_review_sample.jsonl").write_text(
        '{"case_id":"grounded_mapo_tofu","must_not_claim":"palace secret recipe"}\n',
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
