from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from scripts.release_evidence.models import (
    BundleIdentity,
    FileIdentity,
    KnowledgeBaseIdentity,
    QualityMetrics,
    TargetIdentity,
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
    ("field", "signature"),
    [
        pytest.param("graph_signature", "   ", id="graph-spaces"),
        pytest.param("document_signature", "\t", id="document-tab"),
        pytest.param("embedding_signature", "\n", id="embedding-newline"),
        pytest.param("index_signature", " \t\r\n", id="index-mixed-whitespace"),
    ],
)
def test_knowledge_base_identity_rejects_blank_signatures(
    field: str,
    signature: str,
) -> None:
    payload: dict[str, object] = {
        "schema_version": "1",
        "manifest_version": 7,
        "stage": "ready",
        "health": "ready",
        "published_at": "2026-07-16T07:30:00+00:00",
        "index_version": "v000007",
        "collection_name": "cooking_knowledge__active",
        "graph_signature": "graph-signature",
        "document_signature": "document-signature",
        "embedding_signature": "embedding-signature",
        "index_signature": "index-signature",
        "total_documents": 323,
        "total_chunks": 1543,
        "vector_rows": 1543,
    }
    payload[field] = signature

    with pytest.raises(ValidationError):
        KnowledgeBaseIdentity.model_validate(payload)


def test_knowledge_base_identity_accepts_non_blank_signatures() -> None:
    identity = KnowledgeBaseIdentity(
        schema_version="1",
        manifest_version=7,
        stage="ready",
        health="ready",
        published_at="2026-07-16T07:30:00+00:00",
        index_version="v000007",
        collection_name="cooking_knowledge__active",
        graph_signature="graph-signature",
        document_signature="document-signature",
        embedding_signature="embedding-signature",
        index_signature="index-signature",
        total_documents=323,
        total_chunks=1543,
        vector_rows=1543,
    )

    assert identity.index_signature == "index-signature"


@pytest.mark.parametrize(
    "host",
    [
        pytest.param(r"C:\Users\runner\.env", id="windows-path"),
        pytest.param(r"quality\example.com", id="backslash"),
        pytest.param("quality.example.com\x00secret", id="nul"),
        pytest.param("quality.example.com\x01secret", id="control-character"),
        pytest.param("https://quality.example.com/path", id="scheme-and-path"),
        pytest.param("quality.example.com/path", id="path"),
        pytest.param(" quality.example.com", id="leading-space"),
        pytest.param("quality.example.com\t", id="trailing-tab"),
        pytest.param("", id="empty"),
        pytest.param("quality..example.com", id="empty-label"),
        pytest.param("-quality.example.com", id="leading-label-hyphen"),
        pytest.param("quality-.example.com", id="trailing-label-hyphen"),
        pytest.param("quality_example.com", id="underscore"),
        pytest.param("quälity.example.com", id="non-ascii"),
        pytest.param("quality.example.com:", id="empty-port"),
        pytest.param("quality.example.com:https", id="non-numeric-port"),
        pytest.param("quality.example.com:443:444", id="multiple-ports"),
        pytest.param("quality.example.com:0", id="zero-port"),
        pytest.param("quality.example.com:65536", id="out-of-range-port"),
        pytest.param("user@quality.example.com", id="userinfo"),
        pytest.param("quality.example.com?token=secret", id="query"),
        pytest.param("quality.example.com#fragment", id="fragment"),
        pytest.param("http://[::1]:8000", id="bracketed-ipv6-url"),
        pytest.param("fe80::1%eth0", id="ipv6-zone-id"),
        pytest.param("2001:db8::g", id="ipv6-non-hex"),
        pytest.param("1:2:3:4:5:6:7:8:9", id="ipv6-too-many-hextets"),
        pytest.param("2001:db8::1/path", id="ipv6-slash"),
        pytest.param(r"2001:db8::1\path", id="ipv6-backslash"),
        pytest.param(" 2001:db8::1", id="ipv6-whitespace"),
        pytest.param("2001:db8::1\x00", id="ipv6-control-character"),
        pytest.param("[::1]", id="bracketed-ipv6-without-port"),
        pytest.param("[::1]:0", id="bracketed-ipv6-zero-port"),
        pytest.param("[::1]:65536", id="bracketed-ipv6-out-of-range-port"),
        pytest.param("[fe80::1%eth0]:8000", id="bracketed-ipv6-zone-id"),
        pytest.param("[2001:db8::1]:8000/path", id="bracketed-ipv6-path"),
    ],
)
def test_target_identity_rejects_unsafe_hosts(host: str) -> None:
    with pytest.raises(ValidationError):
        TargetIdentity(api_host=host, judge_host="judge.example.com")


def test_target_identity_accepts_expected_dns_hosts() -> None:
    target = TargetIdentity(
        api_host="quality.example.com",
        judge_host="judge.example.com",
    )

    assert target.api_host == "quality.example.com"
    assert target.judge_host == "judge.example.com"


@pytest.mark.parametrize(
    "host",
    [
        pytest.param("quality-1.example.com:443", id="dns-with-port"),
        pytest.param("localhost:7687", id="single-label-with-port"),
        pytest.param("127.0.0.1:8000", id="ipv4-with-port"),
    ],
)
def test_target_identity_accepts_ascii_dns_hosts_with_numeric_ports(host: str) -> None:
    target = TargetIdentity(api_host=host, judge_host="judge.example.com")

    assert target.api_host == host


@pytest.mark.parametrize(
    "host",
    [
        pytest.param("::1", id="integration-loopback"),
        pytest.param("::1:8000", id="numeric-final-hextet"),
        pytest.param("2001:db8::1", id="documentation-prefix"),
        pytest.param("::ffff:192.0.2.128", id="ipv4-mapped"),
    ],
)
def test_target_identity_accepts_ipv6_literals(host: str) -> None:
    target = TargetIdentity(api_host=host, judge_host="judge.example.com")

    assert target.api_host == host


@pytest.mark.parametrize(
    "host",
    [
        pytest.param("[::1]:8000", id="loopback-with-port"),
        pytest.param("[2001:db8::1]:443", id="documentation-prefix-with-port"),
        pytest.param("[::ffff:192.0.2.128]:65535", id="ipv4-mapped-with-port"),
    ],
)
def test_target_identity_accepts_bracketed_ipv6_with_numeric_port(host: str) -> None:
    target = TargetIdentity(api_host=host, judge_host="judge.example.com")

    assert target.api_host == host


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


@pytest.mark.parametrize(
    "path",
    [
        pytest.param(
            "https://user:password@example.com/report.json",
            id="credential-bearing-url",
        ),
        pytest.param(
            "https://example.com/report.json?token=secret",
            id="query-bearing-url",
        ),
        pytest.param("s3://bucket/report.json", id="uri-scheme"),
        pytest.param("reports/report.json:secret", id="windows-ads"),
        pytest.param("reports/report.json\nsecret", id="control-character"),
        pytest.param("reports/private key/report.json", id="whitespace-component"),
        pytest.param("reports/report.json#fragment", id="fragment"),
        pytest.param("reports/report%20.json", id="percent-encoding"),
        pytest.param("reports/报告.json", id="non-ascii"),
    ],
)
def test_file_identity_rejects_unsafe_path_components(path: str) -> None:
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
        path="reports-1/integration_gate/report.v1.json",
        bytes=10,
        sha256="a" * 64,
    )

    assert artifact.path == "reports-1/integration_gate/report.v1.json"
