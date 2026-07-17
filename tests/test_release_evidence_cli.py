from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.release_evidence import cli
from scripts.release_evidence.capture import CaptureOutputs


def _capture_arguments(*diagnostics: str) -> list[str]:
    return [
        "capture",
        "--repository-root",
        ".",
        "--repository",
        "owner/repository",
        "--package-version",
        "0.4.0rc1",
        "--tag",
        "v0.4.0-rc.1",
        "--evaluated-commit",
        "a" * 40,
        "--integration-policy",
        "integration-policy.json",
        "--live-quality-policy",
        "live-quality-policy.json",
        "--integration-report",
        "integration-report.json",
        "--live-quality-report",
        "live-quality-report.json",
        *diagnostics,
        "--artifact-manifest",
        "artifact-manifest.json",
        "--judge-model",
        "judge-model",
        "--output-dir",
        "evidence",
        "--json",
    ]


def _verify_arguments() -> list[str]:
    return [
        "verify",
        "--repository-root",
        ".",
        "--manifest",
        "manifest.json",
        "--release-commit",
        "a" * 40,
        "--tag",
        "v0.4.0-rc.1",
        "--bundle",
        "bundle.zip",
        "--artifact-metadata",
        "artifact.json",
        "--json",
    ]


def test_capture_cli_dispatches_parsed_inputs_and_writes_json(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def capture(inputs):
        captured["inputs"] = inputs
        return CaptureOutputs(
            receipt_path=Path("evidence/capture.json"),
            bundle_path=Path("evidence/bundle.zip"),
        )

    monkeypatch.setattr(cli, "capture_release_evidence", capture)

    exit_code = cli.main(_capture_arguments("--diagnostics-json", "diagnostics.json"))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "bundle": str(Path("evidence/bundle.zip")),
        "capture_receipt": str(Path("evidence/capture.json")),
    }
    inputs = captured["inputs"]
    assert inputs.repository_root == Path(".")
    assert inputs.repository == "owner/repository"
    assert inputs.diagnostics_path == Path("diagnostics.json")
    assert inputs.output_dir == Path("evidence")


def test_capture_cli_fetches_diagnostics_with_token_and_removes_temporary_file(
    monkeypatch,
    capsys,
) -> None:
    request: dict[str, object] = {}
    diagnostics: dict[str, object] = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"diagnostics": {"status": "ready"}}

    def get(url, *, headers, timeout):
        request.update(url=url, headers=headers, timeout=timeout)
        return Response()

    def capture(inputs):
        diagnostics["path"] = inputs.diagnostics_path
        diagnostics["payload"] = json.loads(inputs.diagnostics_path.read_text(encoding="utf-8"))
        return CaptureOutputs(Path("capture.json"), Path("bundle.zip"))

    monkeypatch.setenv("LIVE_QUALITY_API_TOKEN", "test-token")
    monkeypatch.setattr(cli.requests, "get", get)
    monkeypatch.setattr(cli, "capture_release_evidence", capture)

    exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "bundle": "bundle.zip",
        "capture_receipt": "capture.json",
    }
    assert request == {
        "url": "https://api.example/diag",
        "headers": {"Authorization": "Bearer test-token"},
        "timeout": 15,
    }
    assert diagnostics["payload"] == {"diagnostics": {"status": "ready"}}
    assert not diagnostics["path"].exists()


def test_finalize_cli_normalizes_raw_digest_and_writes_safe_json(monkeypatch, capsys) -> None:
    dispatched: dict[str, object] = {}

    def finalize(receipt_path, transport, output_path):
        dispatched.update(
            receipt_path=receipt_path,
            transport=transport,
            output_path=output_path,
        )
        return object()

    monkeypatch.setattr(cli, "finalize_release_evidence", finalize)

    exit_code = cli.main(
        [
            "finalize",
            "--capture-receipt",
            "capture.json",
            "--workflow-run-id",
            "123",
            "--workflow-head-sha",
            "a" * 40,
            "--artifact-id",
            "456",
            "--artifact-name",
            "graph-rag-c9-0.4.0rc1-quality-evidence",
            "--artifact-digest",
            "b" * 64,
            "--output",
            "manifest.json",
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {"output": "manifest.json"}
    assert dispatched["receipt_path"] == Path("capture.json")
    assert dispatched["output_path"] == Path("manifest.json")
    assert dispatched["transport"].artifact_digest == "sha256:" + "b" * 64


def test_verify_cli_dispatches_inputs_and_writes_json(monkeypatch, capsys) -> None:
    dispatched: dict[str, object] = {}

    def verify(inputs):
        dispatched["inputs"] = inputs
        return SimpleNamespace(
            release=SimpleNamespace(package_version="0.4.0rc1"),
            provenance=SimpleNamespace(evaluated_commit="a" * 40),
        )

    monkeypatch.setattr(cli, "verify_release_evidence", verify)

    exit_code = cli.main(_verify_arguments())

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "evaluated_commit": "a" * 40,
        "package_version": "0.4.0rc1",
        "verified": True,
    }
    inputs = dispatched["inputs"]
    assert inputs.manifest_path == Path("manifest.json")
    assert inputs.artifact_metadata_path == Path("artifact.json")


def test_cli_redacts_internal_exception_text(monkeypatch, capsys) -> None:
    def fail(_inputs):
        raise RuntimeError("Bearer actual-token-value")

    monkeypatch.setattr(cli, "verify_release_evidence", fail)

    exit_code = cli.main(_verify_arguments())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "actual-token-value" not in captured.err
    assert json.loads(captured.err) == {
        "code": "RELEASE_EVIDENCE_OPERATION_FAILED",
        "failure_type": "gate-error",
        "passed": False,
    }


def test_parser_rejects_missing_capture_arguments_with_exit_two(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["capture"])

    assert raised.value.code == 2
    assert "actual-token-value" not in capsys.readouterr().err
