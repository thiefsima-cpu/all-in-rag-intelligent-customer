"""Human-readable formatters for app diagnostics DTOs."""

from __future__ import annotations

from typing import Optional


def startup_diagnostics_lines(diagnostics: object, *, title: Optional[str] = None) -> list[str]:
    heading = title or f"{diagnostics.mode.capitalize()} startup diagnostics"
    lines = [
        heading,
        "-" * len(heading),
        (
            f"Models: llm={diagnostics.llm_model}, "
            f"embedding={diagnostics.embedding_model}, rerank={diagnostics.rerank_model}"
        ),
        f"Tracing: {'enabled' if diagnostics.trace_enabled else 'disabled'} "
        f"({diagnostics.trace_path})",
        (
            "Runtime: "
            f"build_initialized={diagnostics.build_initialized}, "
            f"serving_initialized={diagnostics.serving_initialized}, "
            f"artifacts_ready={diagnostics.artifacts_ready}, "
            f"system_ready={diagnostics.system_ready}, "
            f"retrieval_engines_initialized={diagnostics.retrieval_engines_initialized}"
        ),
        (
            "Manifest: "
            f"health={diagnostics.manifest.health}, "
            f"stage={diagnostics.manifest.stage}, "
            f"version={diagnostics.manifest.manifest_version}, "
            f"slot={diagnostics.manifest.collection_slot or 'legacy'}, "
            f"cache_hit={diagnostics.manifest.cache_hit}, "
            f"documents={diagnostics.manifest.total_documents}, "
            f"chunks={diagnostics.manifest.total_chunks}, "
            f"vector_rows={diagnostics.manifest.vector_rows}"
        ),
        f"Manifest path: {diagnostics.manifest.manifest_path}",
    ]
    if diagnostics.manifest.documents_path:
        lines.append(f"Documents cache: {diagnostics.manifest.documents_path}")
    if diagnostics.manifest.chunks_path:
        lines.append(f"Chunks cache: {diagnostics.manifest.chunks_path}")
    lines.append(
        "Trace stats: "
        f"dropped={diagnostics.trace_stats.dropped_events}, "
        f"queued={diagnostics.trace_stats.queued_events}, "
        f"async_enabled={diagnostics.trace_stats.async_enabled}"
    )
    if diagnostics.manifest.last_error:
        lines.append(f"Manifest error: {diagnostics.manifest.last_error}")
    return lines


__all__ = ["startup_diagnostics_lines"]
