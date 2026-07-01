"""Helpers that assemble typed HTTP responses for the FastAPI surface."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse

from ...runtime.artifacts import ArtifactManifest, artifact_health
from ...runtime.artifacts.registry import ArtifactRegistrySnapshot
from .answer_models import (
    AnswerPayloadModel,
    AnswerResponseModel,
    AnswerStreamEventModel,
    PublicAnswerPayloadModel,
    PublicAnswerResponseModel,
)
from .build_models import (
    ArtifactRegistryResponseModel,
    BuildJobListResponseModel,
    BuildJobResponseModel,
)
from .diagnostics_models import (
    DiagnosticsResponseModel,
    OperationResponseModel,
    StatsResponseModel,
)
from .error_models import ErrorCode, sanitize_public_error_fields


def _artifact_manifest_payload(manifest: ArtifactManifest) -> dict[str, Any]:
    return {
        "stage": manifest.stage,
        "health": artifact_health(manifest),
        "updated_at": manifest.updated_at,
        "collection_name": manifest.collection_name,
        "manifest_path": manifest.manifest_path,
        "documents_path": manifest.documents_path,
        "chunks_path": manifest.chunks_path,
        "total_documents": manifest.total_documents,
        "total_chunks": manifest.total_chunks,
        "vector_rows": manifest.vector_rows,
        "cache_hit": manifest.cache_hit,
        "last_error": ErrorCode.BUILD_FAILED.value if manifest.last_error else "",
        "build_metadata": dict(manifest.build_metadata),
        "manifest_version": manifest.manifest_version,
        "index_version": manifest.index_version,
        "collection_base_name": manifest.collection_base_name,
        "collection_slot": manifest.collection_slot,
        "previous_collection_name": manifest.previous_collection_name,
        "published_at": manifest.published_at,
    }


def build_json_response(*, status_code: int, content: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content)


def build_stats_response(stats_payload: dict[str, Any]) -> StatsResponseModel:
    safe = sanitize_public_error_fields(stats_payload, code=ErrorCode.BUILD_FAILED)
    return StatsResponseModel.model_validate({"stats": safe})


def build_diagnostics_response(diagnostics_payload: dict[str, Any]) -> DiagnosticsResponseModel:
    safe = sanitize_public_error_fields(diagnostics_payload, code=ErrorCode.BUILD_FAILED)
    return DiagnosticsResponseModel.model_validate({"diagnostics": safe})


def build_operation_response(operation_payload: dict[str, Any]) -> OperationResponseModel:
    safe = sanitize_public_error_fields(operation_payload, code=ErrorCode.BUILD_FAILED)
    return OperationResponseModel.model_validate(safe)


def build_answer_response(answer_payload: AnswerPayloadModel) -> AnswerResponseModel:
    return AnswerResponseModel(response=answer_payload)


def build_public_answer_response(answer_payload: AnswerPayloadModel) -> PublicAnswerResponseModel:
    return PublicAnswerResponseModel(
        response=PublicAnswerPayloadModel.from_debug_payload(answer_payload)
    )


def build_build_job_response(job_payload: dict[str, Any]) -> BuildJobResponseModel:
    safe = sanitize_public_error_fields(job_payload, code=ErrorCode.BUILD_FAILED)
    return BuildJobResponseModel.model_validate({"job": safe})


def build_build_job_list_response(
    job_payloads: list[dict[str, Any]],
    *,
    next_cursor: str = "",
) -> BuildJobListResponseModel:
    safe = sanitize_public_error_fields(list(job_payloads or []), code=ErrorCode.BUILD_FAILED)
    return BuildJobListResponseModel.model_validate(
        {"jobs": safe, "next_cursor": str(next_cursor or "")}
    )


def build_artifact_registry_response(
    snapshot: ArtifactRegistrySnapshot,
) -> ArtifactRegistryResponseModel:
    return ArtifactRegistryResponseModel.model_validate(
        {
            "active": _artifact_manifest_payload(snapshot.active),
            "candidate": (
                _artifact_manifest_payload(snapshot.candidate)
                if snapshot.candidate is not None
                else None
            ),
            "versions": list(snapshot.versions),
        }
    )


def encode_sse_event(event: AnswerStreamEventModel) -> str:
    data = json.dumps(event.data.model_dump(), ensure_ascii=False)
    return f"event: {event.event.value}\ndata: {data}\n\n"


def iter_sse_chunks(events: Iterable[AnswerStreamEventModel]) -> Iterator[str]:
    for event in events:
        yield encode_sse_event(event)


def build_sse_streaming_response(events: Iterable[AnswerStreamEventModel]) -> StreamingResponse:
    return StreamingResponse(
        iter_sse_chunks(events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = [
    "build_answer_response",
    "build_artifact_registry_response",
    "build_build_job_list_response",
    "build_build_job_response",
    "build_diagnostics_response",
    "build_json_response",
    "build_operation_response",
    "build_public_answer_response",
    "build_sse_streaming_response",
    "build_stats_response",
    "encode_sse_event",
    "iter_sse_chunks",
]
