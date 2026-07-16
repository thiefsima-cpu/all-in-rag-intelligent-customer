from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from scripts.release_evidence.models import (
    BundleIdentity,
    FileIdentity,
    QualityMetrics,
    TransportIdentity,
)


def test_bundle_identity_requires_lowercase_sha256() -> None:
    with pytest.raises(ValidationError):
        BundleIdentity(
            name="graph-rag-c9-0.4.0rc1-quality-evidence.zip",
            bytes=10,
            sha256="A" * 64,
        )


def test_bundle_identity_rejects_unknown_and_coerced_fields() -> None:
    with pytest.raises(ValidationError):
        BundleIdentity.model_validate(
            {
                "name": "graph-rag-c9-0.4.0rc1-quality-evidence.zip",
                "bytes": "10",
                "sha256": "a" * 64,
                "unexpected": True,
            }
        )


def test_quality_metrics_reject_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        QualityMetrics(
            case_count=1,
            pass_rate=1.0,
            deterministic_pass_rate=1.0,
            judge_pass_rate=1.0,
            recall_at_k=math.inf,
            mrr=1.0,
            ndcg_at_k=1.0,
            fallback_rate=0.0,
            retrieval_degradation_rate=0.0,
            p95_latency_ms=1.0,
            estimated_cost_usd=0.0,
        )


def test_transport_identity_requires_full_git_sha_and_prefixed_digest() -> None:
    with pytest.raises(ValidationError):
        TransportIdentity(
            provider="github-actions",
            workflow_run_id=1,
            workflow_head_sha="abc",
            artifact_id=2,
            artifact_name="evidence",
            artifact_digest="f" * 64,
        )


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/etc/passwd", id="posix-absolute"),
        pytest.param("C:/Users/runner/report.json", id="windows-drive-absolute"),
        pytest.param("C:report.json", id="windows-drive-relative"),
        pytest.param(r"\\server\share\report.json", id="windows-unc"),
        pytest.param("", id="empty"),
        pytest.param(".", id="current-directory"),
        pytest.param("..", id="parent-directory"),
        pytest.param(r"artifacts\report.json", id="backslash"),
    ],
)
def test_file_identity_rejects_non_repository_relative_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        FileIdentity(
            name="report",
            path=path,
            bytes=10,
            sha256="a" * 64,
        )


def test_file_identity_accepts_repository_relative_posix_path() -> None:
    artifact = FileIdentity(
        name="report",
        path="reports/integration_gate/report.json",
        bytes=10,
        sha256="a" * 64,
    )

    assert artifact.path == "reports/integration_gate/report.json"
