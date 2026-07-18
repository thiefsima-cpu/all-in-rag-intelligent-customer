from __future__ import annotations

from pathlib import Path

from .models import (
    ReleaseEvidenceManifest,
    TransportIdentity,
    load_capture_receipt,
    write_evidence_model,
)


class ReleaseEvidenceFinalizeError(RuntimeError):
    pass


def finalize_release_evidence(
    receipt_path: str | Path,
    transport: TransportIdentity,
    output_path: str | Path,
) -> ReleaseEvidenceManifest:
    receipt = load_capture_receipt(receipt_path)
    if transport.workflow_head_sha != receipt.provenance.evaluated_commit:
        raise ReleaseEvidenceFinalizeError("workflow head does not match evaluated commit")
    expected_artifact_name = f"graph-rag-c9-{receipt.release.package_version}-quality-evidence"
    if transport.artifact_name != expected_artifact_name:
        raise ReleaseEvidenceFinalizeError("workflow artifact name does not match release")
    manifest = ReleaseEvidenceManifest(
        **receipt.model_dump(exclude={"schema_version"}),
        transport=transport,
    )
    write_evidence_model(manifest, output_path)
    return manifest
