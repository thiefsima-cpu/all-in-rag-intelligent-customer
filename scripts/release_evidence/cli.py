from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

import requests

from .capture import CaptureInputs, capture_release_evidence
from .finalize import finalize_release_evidence
from .models import TransportIdentity
from .verifier import VerifyInputs, verify_release_evidence


class ReleaseEvidenceCliError(RuntimeError):
    pass


def _discard_temporary_diagnostics(path: Path) -> None:
    for _attempt in range(2):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            continue
        return


def _remove_temporary_diagnostics(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except Exception as exc:
        raise ReleaseEvidenceCliError("temporary diagnostics cleanup failed") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture and verify release quality evidence.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture")
    capture.add_argument("--repository-root", type=Path, required=True)
    capture.add_argument("--repository", required=True)
    capture.add_argument("--package-version", required=True)
    capture.add_argument("--tag", required=True)
    capture.add_argument("--evaluated-commit", required=True)
    capture.add_argument("--integration-policy", type=Path, required=True)
    capture.add_argument("--live-quality-policy", type=Path, required=True)
    capture.add_argument("--integration-report", type=Path, required=True)
    capture.add_argument("--live-quality-report", type=Path, required=True)
    diagnostics = capture.add_mutually_exclusive_group(required=True)
    diagnostics.add_argument("--diagnostics-json", type=Path)
    diagnostics.add_argument("--diagnostics-url")
    capture.add_argument("--artifact-manifest", type=Path, required=True)
    capture.add_argument("--judge-model", required=True)
    capture.add_argument("--output-dir", type=Path, required=True)
    capture.add_argument("--json", action="store_true", dest="emit_json")

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--capture-receipt", type=Path, required=True)
    finalize.add_argument("--workflow-run-id", type=int, required=True)
    finalize.add_argument("--workflow-head-sha", required=True)
    finalize.add_argument("--artifact-id", type=int, required=True)
    finalize.add_argument("--artifact-name", required=True)
    finalize.add_argument("--artifact-digest", required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--json", action="store_true", dest="emit_json")

    verify = subparsers.add_parser("verify")
    verify.add_argument("--repository-root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--release-commit", required=True)
    verify.add_argument("--tag", required=True)
    verify.add_argument("--bundle", type=Path, required=True)
    verify.add_argument("--artifact-metadata", type=Path, required=True)
    verify.add_argument("--json", action="store_true", dest="emit_json")
    return parser


def _fetch_diagnostics(url: str) -> Path:
    headers: dict[str, str] = {}
    token = os.environ.get("LIVE_QUALITY_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("diagnostics response must be an object")
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        delete=False,
    )
    path = Path(handle.name)
    operation_error: Exception | None = None
    try:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    except Exception as exc:
        operation_error = exc
    try:
        handle.close()
    except Exception as exc:
        if operation_error is None:
            operation_error = exc
        try:
            handle.close()
        except Exception:
            pass
    if operation_error is not None:
        _discard_temporary_diagnostics(path)
        raise operation_error
    return path


def _emit(payload: dict[str, object], emit_json: bool) -> None:
    if emit_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        for name, value in payload.items():
            print(f"{name}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    temporary_diagnostics: Path | None = None
    try:
        if args.command == "capture":
            diagnostics_path = args.diagnostics_json
            if diagnostics_path is None:
                temporary_diagnostics = _fetch_diagnostics(args.diagnostics_url)
                diagnostics_path = temporary_diagnostics
            outputs = capture_release_evidence(
                CaptureInputs(
                    repository_root=args.repository_root,
                    repository=args.repository,
                    package_version=args.package_version,
                    tag=args.tag,
                    evaluated_commit=args.evaluated_commit,
                    integration_policy_path=args.integration_policy,
                    live_quality_policy_path=args.live_quality_policy,
                    integration_report_path=args.integration_report,
                    live_quality_report_path=args.live_quality_report,
                    diagnostics_path=diagnostics_path,
                    artifact_manifest_path=args.artifact_manifest,
                    judge_model=args.judge_model,
                    output_dir=args.output_dir,
                )
            )
            if temporary_diagnostics is not None:
                _remove_temporary_diagnostics(temporary_diagnostics)
                temporary_diagnostics = None
            _emit(
                {
                    "capture_receipt": str(outputs.receipt_path),
                    "bundle": str(outputs.bundle_path),
                },
                args.emit_json,
            )
            return 0
        if args.command == "finalize":
            artifact_digest = args.artifact_digest
            if not artifact_digest.startswith("sha256:"):
                artifact_digest = f"sha256:{artifact_digest}"
            finalize_release_evidence(
                args.capture_receipt,
                TransportIdentity(
                    provider="github-actions",
                    workflow_run_id=args.workflow_run_id,
                    workflow_head_sha=args.workflow_head_sha,
                    artifact_id=args.artifact_id,
                    artifact_name=args.artifact_name,
                    artifact_digest=artifact_digest,
                ),
                args.output,
            )
            _emit({"output": str(args.output)}, args.emit_json)
            return 0
        manifest = verify_release_evidence(
            VerifyInputs(
                repository_root=args.repository_root,
                manifest_path=args.manifest,
                release_commit=args.release_commit,
                tag=args.tag,
                bundle_path=args.bundle,
                artifact_metadata_path=args.artifact_metadata,
            )
        )
        _emit(
            {
                "verified": True,
                "package_version": manifest.release.package_version,
                "evaluated_commit": manifest.provenance.evaluated_commit,
            },
            args.emit_json,
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "passed": False,
                    "failure_type": "gate-error",
                    "code": "RELEASE_EVIDENCE_OPERATION_FAILED",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    finally:
        if temporary_diagnostics is not None:
            _discard_temporary_diagnostics(temporary_diagnostics)
