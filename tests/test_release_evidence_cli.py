from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.release_evidence import cli
from scripts.release_evidence.capture import CaptureInputs, CaptureOutputs
from scripts.release_evidence.models import TransportIdentity
from scripts.release_evidence.verifier import VerifyInputs

_FAILURE_PAYLOAD = {
    "code": "RELEASE_EVIDENCE_OPERATION_FAILED",
    "failure_type": "gate-error",
    "passed": False,
}


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


def _patch_diagnostics_response(monkeypatch, payload: dict[str, object]) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return payload

    monkeypatch.setattr(cli.requests, "get", lambda *_args, **_kwargs: Response())


def _use_temporary_directory(monkeypatch, directory: Path, *, failure: str | None = None) -> None:
    named_temporary_file = cli.tempfile.NamedTemporaryFile

    class FailingHandle:
        def __init__(self, inner) -> None:
            self._inner = inner
            self.name = inner.name

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, exception_type, exception, traceback):
            result = self._inner.__exit__(exception_type, exception, traceback)
            if failure == "flush" and exception_type is None:
                raise OSError(f"flush failed for Bearer raw-token at {self.name}")
            return result

        def close(self) -> None:
            self._inner.close()
            if failure == "flush":
                raise OSError(f"flush failed for Bearer raw-token at {self.name}")

        def write(self, value: str) -> int:
            if failure == "write":
                raise OSError(f"write failed for Bearer raw-token at {self.name}")
            return self._inner.write(value)

    def create_temporary_file(**kwargs):
        handle = named_temporary_file(**kwargs, dir=directory)
        return FailingHandle(handle) if failure is not None else handle

    monkeypatch.setattr(cli.tempfile, "NamedTemporaryFile", create_temporary_file)


def _assert_safe_failure(captured, temporary_directory: Path) -> None:
    assert captured.out == ""
    assert json.loads(captured.err) == _FAILURE_PAYLOAD
    assert "raw-token" not in captured.err
    assert str(temporary_directory.resolve()) not in captured.err


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
    assert captured["inputs"] == CaptureInputs(
        repository_root=Path("."),
        repository="owner/repository",
        package_version="0.4.0rc1",
        tag="v0.4.0-rc.1",
        evaluated_commit="a" * 40,
        integration_policy_path=Path("integration-policy.json"),
        live_quality_policy_path=Path("live-quality-policy.json"),
        integration_report_path=Path("integration-report.json"),
        live_quality_report_path=Path("live-quality-report.json"),
        diagnostics_path=Path("diagnostics.json"),
        artifact_manifest_path=Path("artifact-manifest.json"),
        judge_model="judge-model",
        output_dir=Path("evidence"),
    )


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


def test_capture_cli_removes_temporary_file_when_diagnostics_cannot_serialize(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _patch_diagnostics_response(monkeypatch, {"value": float("nan")})
    _use_temporary_directory(monkeypatch, tmp_path)

    exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 2
    _assert_safe_failure(capsys.readouterr(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_capture_cli_retries_internal_cleanup_without_covering_serialization_error(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _patch_diagnostics_response(monkeypatch, {"value": float("nan")})
    _use_temporary_directory(monkeypatch, tmp_path)
    unlink = Path.unlink
    failed_once = False

    def fail_once(path, *args, **kwargs):
        nonlocal failed_once
        if path.parent == tmp_path and not failed_once:
            failed_once = True
            raise OSError(f"cleanup failed for Bearer raw-token at {path.resolve()}")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_once)

    exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 2
    _assert_safe_failure(capsys.readouterr(), tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("failure", ["write", "flush"])
def test_capture_cli_removes_temporary_file_when_diagnostics_write_fails(
    tmp_path,
    monkeypatch,
    capsys,
    failure: str,
) -> None:
    _patch_diagnostics_response(monkeypatch, {"diagnostics": {"status": "ready"}})
    _use_temporary_directory(monkeypatch, tmp_path, failure=failure)

    exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 2
    _assert_safe_failure(capsys.readouterr(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_capture_cli_reports_cleanup_failure_before_success_output(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    _patch_diagnostics_response(monkeypatch, {"diagnostics": {"status": "ready"}})
    _use_temporary_directory(monkeypatch, tmp_path)
    unlink = Path.unlink
    failed_once = False

    def capture(_inputs):
        return CaptureOutputs(Path("capture.json"), Path("bundle.zip"))

    def fail_once(path, *args, **kwargs):
        nonlocal failed_once
        if path.parent == tmp_path and not failed_once:
            failed_once = True
            raise OSError(f"cleanup failed for Bearer raw-token at {path.resolve()}")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(cli, "capture_release_evidence", capture)
    monkeypatch.setattr(Path, "unlink", fail_once)

    exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 2
    _assert_safe_failure(capsys.readouterr(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_capture_error_is_preserved_when_cleanup_also_fails(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    unlink = Path.unlink

    with monkeypatch.context() as context:
        _patch_diagnostics_response(context, {"diagnostics": {"status": "ready"}})
        _use_temporary_directory(context, tmp_path)

        def fail_capture(_inputs):
            raise RuntimeError(f"capture failed for Bearer raw-token at {tmp_path.resolve()}")

        def fail_cleanup(path, *_args, **_kwargs):
            raise OSError(f"cleanup failed for Bearer raw-token at {path.resolve()}")

        context.setattr(cli, "capture_release_evidence", fail_capture)
        context.setattr(Path, "unlink", fail_cleanup)

        exit_code = cli.main(_capture_arguments("--diagnostics-url", "https://api.example/diag"))

    assert exit_code == 2
    _assert_safe_failure(capsys.readouterr(), tmp_path)
    for residual in tmp_path.iterdir():
        unlink(residual)
    assert list(tmp_path.iterdir()) == []


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
    assert dispatched["transport"] == TransportIdentity(
        provider="github-actions",
        workflow_run_id=123,
        workflow_head_sha="a" * 40,
        artifact_id=456,
        artifact_name="graph-rag-c9-0.4.0rc1-quality-evidence",
        artifact_digest="sha256:" + "b" * 64,
    )


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
    assert dispatched["inputs"] == VerifyInputs(
        repository_root=Path("."),
        manifest_path=Path("manifest.json"),
        release_commit="a" * 40,
        tag="v0.4.0-rc.1",
        bundle_path=Path("bundle.zip"),
        artifact_metadata_path=Path("artifact.json"),
    )


def test_cli_redacts_internal_exception_text(monkeypatch, capsys) -> None:
    def fail(_inputs):
        raise RuntimeError("Bearer actual-token-value")

    monkeypatch.setattr(cli, "verify_release_evidence", fail)

    exit_code = cli.main(_verify_arguments())

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "actual-token-value" not in captured.err
    assert json.loads(captured.err) == _FAILURE_PAYLOAD


def test_parser_rejects_missing_capture_arguments_with_exit_two(capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["capture"])

    assert raised.value.code == 2
    assert "actual-token-value" not in capsys.readouterr().err
