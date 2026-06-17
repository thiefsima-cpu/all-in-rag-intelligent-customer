"""Machine-readable inventory for canonical, internal, and legacy module surfaces."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PublicSurfaceEntry:
    module_name: str
    kind: str
    canonical_module: str
    retirement_phase: str
    notes: str = ""
    removal_version: str = ""
    scan_rules: tuple[str, ...] = ()


LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION = "0.2.0"
LEGACY_PUBLIC_SURFACE_SCAN_RULES = (
    "internal_dependency_guard",
    "thin_wrapper_guard",
)


PUBLIC_API_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "rag_modules.configuration",
        "public_api",
        "rag_modules.configuration",
        "canonical",
        "Primary configuration entrypoint for external callers and top-level bootstrapping.",
    ),
    PublicSurfaceEntry(
        "rag_modules.interfaces",
        "public_api",
        "rag_modules.interfaces",
        "canonical",
        "Stable interface layer package for API entrypoints.",
    ),
    PublicSurfaceEntry(
        "rag_modules.interfaces.api",
        "public_api",
        "rag_modules.interfaces.api",
        "canonical",
        "Stable FastAPI application factory surface.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app",
        "public_api",
        "rag_modules.app",
        "canonical",
        "Stable application-layer package exports.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app.assembly",
        "public_api",
        "rag_modules.app.assembly",
        "canonical",
        "Canonical application assembly entry for building the system facade.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app.system",
        "public_api",
        "rag_modules.app.system",
        "canonical",
        "Stable application facade for runtime lifecycle and answering use cases.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app.providers",
        "public_api",
        "rag_modules.app.providers",
        "canonical",
        "Public default-provider facade over internal provider components.",
    ),
)

SERVICE_API_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "rag_modules.app.services",
        "service_api",
        "rag_modules.app.services",
        "canonical",
        "Repository-internal service layer used by application assembly and workflows.",
    ),
    PublicSurfaceEntry(
        "rag_modules.routing",
        "service_api",
        "rag_modules.routing",
        "canonical",
        "Repository-internal routing workflow and orchestration surface.",
    ),
    PublicSurfaceEntry(
        "rag_modules.retrieval",
        "service_api",
        "rag_modules.retrieval",
        "canonical",
        "Repository-internal retrieval runtime and evidence contracts.",
    ),
    PublicSurfaceEntry(
        "rag_modules.generation",
        "service_api",
        "rag_modules.generation",
        "canonical",
        "Repository-internal grounded generation workflows and adapters.",
    ),
    PublicSurfaceEntry(
        "rag_modules.query_understanding",
        "service_api",
        "rag_modules.query_understanding",
        "canonical",
        "Repository-internal query planning and semantic analysis surface.",
    ),
)

INTERNAL_ONLY_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "rag_modules.app.composition",
        "internal_only",
        "rag_modules.app.composition",
        "internal_only",
        "Composition-root helpers for runtime assembly. Do not import from feature code.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app.provider_components",
        "internal_only",
        "rag_modules.app.provider_components",
        "internal_only",
        "Provider wiring helpers for assembly internals. Use rag_modules.app.providers instead.",
    ),
)

ROOT_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "intelligent_query_router",
        "root_facade",
        "rag_modules.routing.intelligent_query_router",
        "external_migration_window",
        removal_version=LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
        scan_rules=LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    ),
    PublicSurfaceEntry(
        "graph_data_preparation",
        "root_facade",
        "rag_modules.graph.data_preparation",
        "external_migration_window",
        removal_version=LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
        scan_rules=LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    ),
    PublicSurfaceEntry(
        "graph_indexing",
        "root_facade",
        "rag_modules.graph.indexing",
        "external_migration_window",
        removal_version=LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
        scan_rules=LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    ),
)

EXTERNAL_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "config",
        "repo_root_facade",
        "rag_modules.configuration",
        "external_migration_window",
        removal_version=LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
        scan_rules=LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    ),
)

LEGACY_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    *ROOT_PUBLIC_SURFACE,
    *EXTERNAL_PUBLIC_SURFACE,
)

CANONICAL_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    *PUBLIC_API_SURFACE,
    *SERVICE_API_SURFACE,
    *INTERNAL_ONLY_SURFACE,
)

ALL_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    *CANONICAL_SURFACE,
    *LEGACY_PUBLIC_SURFACE,
)


def modules_for(entries: Iterable[PublicSurfaceEntry]) -> frozenset[str]:
    return frozenset(entry.module_name for entry in entries)


def surface_by_kind(
    entries: Iterable[PublicSurfaceEntry] = ALL_PUBLIC_SURFACE,
) -> dict[str, tuple[PublicSurfaceEntry, ...]]:
    grouped: dict[str, list[PublicSurfaceEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.kind, []).append(entry)
    return {kind: tuple(kind_entries) for kind, kind_entries in grouped.items()}


def canonical_surface_by_module() -> dict[str, PublicSurfaceEntry]:
    return {entry.module_name: entry for entry in CANONICAL_SURFACE}


def legacy_surface_by_module() -> dict[str, PublicSurfaceEntry]:
    return {entry.module_name: entry for entry in LEGACY_PUBLIC_SURFACE}


def public_surface_by_module() -> dict[str, PublicSurfaceEntry]:
    return {entry.module_name: entry for entry in ALL_PUBLIC_SURFACE}


def root_facade_module_names() -> frozenset[str]:
    return frozenset(f"rag_modules.{entry.module_name}" for entry in ROOT_PUBLIC_SURFACE)


def repo_root_facade_module_names() -> frozenset[str]:
    return modules_for(EXTERNAL_PUBLIC_SURFACE)


__all__ = [
    "ALL_PUBLIC_SURFACE",
    "CANONICAL_SURFACE",
    "EXTERNAL_PUBLIC_SURFACE",
    "INTERNAL_ONLY_SURFACE",
    "LEGACY_PUBLIC_SURFACE",
    "LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION",
    "LEGACY_PUBLIC_SURFACE_SCAN_RULES",
    "PUBLIC_API_SURFACE",
    "ROOT_PUBLIC_SURFACE",
    "SERVICE_API_SURFACE",
    "PublicSurfaceEntry",
    "canonical_surface_by_module",
    "legacy_surface_by_module",
    "modules_for",
    "public_surface_by_module",
    "repo_root_facade_module_names",
    "root_facade_module_names",
    "surface_by_kind",
]
