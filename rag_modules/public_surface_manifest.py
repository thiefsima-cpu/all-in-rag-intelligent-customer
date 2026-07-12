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


@dataclass(frozen=True, slots=True)
class PackageExportEntry:
    module_name: str
    export_name: str
    kind: str
    canonical_module: str
    notes: str = ""


# Package-version milestone for the final public import-facade removal; not API_VERSION.
LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION = "0.2.0"
LEGACY_PUBLIC_SURFACE_SCAN_RULES = (
    "internal_dependency_guard",
    "thin_wrapper_guard",
)


PUBLIC_API_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "rag_modules",
        "public_api",
        "rag_modules",
        "canonical",
        (
            "root package export surface. Names in rag_modules.__all__ are public API "
            "and are governed by ROOT_PACKAGE_EXPORTS."
        ),
    ),
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
        "Stable runtime facade and composition entrypoints.",
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
        "Canonical runtime provider boundary for application assembly.",
    ),
)

SERVICE_API_SURFACE: tuple[PublicSurfaceEntry, ...] = (
    PublicSurfaceEntry(
        "rag_modules.application",
        "service_api",
        "rag_modules.application",
        "canonical",
        "Pure application use cases, consumer-owned ports, and application DTOs.",
    ),
    PublicSurfaceEntry(
        "rag_modules.contracts",
        "service_api",
        "rag_modules.contracts",
        "canonical",
        "Canonical cross-subsystem contract kernel for shared DTOs and query settings.",
    ),
    PublicSurfaceEntry(
        "rag_modules.app.services",
        "service_api",
        "rag_modules.app.services",
        "canonical",
        "Compatibility imports for services now owned by rag_modules.application.",
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
        "Repository-internal retrieval runtime. Shared DTOs live in rag_modules.contracts.",
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
)

ROOT_PACKAGE_EXPORTS: tuple[PackageExportEntry, ...] = (
    PackageExportEntry(
        "rag_modules",
        "AdvancedGraphRAGSystem",
        "public_api",
        "rag_modules.app.system",
        "Stable root package entrypoint for serving/build runtime orchestration.",
    ),
    PackageExportEntry(
        "rag_modules",
        "GenerationWorkflowService",
        "public_api",
        "rag_modules.generation.service",
        "Stable root package entrypoint for generation workflow orchestration.",
    ),
    PackageExportEntry(
        "rag_modules",
        "KnowledgeBaseService",
        "public_api",
        "rag_modules.application.knowledge_base",
        "Stable root package entrypoint for build/rebuild knowledge-base workflows.",
    ),
    PackageExportEntry(
        "rag_modules",
        "MilvusIndexConstructionModule",
        "public_api",
        "rag_modules.infra.milvus_index_construction",
        "Stable root package entrypoint for Milvus index construction.",
    ),
)

ROOT_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = ()

EXTERNAL_PUBLIC_SURFACE: tuple[PublicSurfaceEntry, ...] = ()

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


def root_package_exports_by_name() -> dict[str, PackageExportEntry]:
    return {entry.export_name: entry for entry in ROOT_PACKAGE_EXPORTS}


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
    "PackageExportEntry",
    "PUBLIC_API_SURFACE",
    "ROOT_PACKAGE_EXPORTS",
    "ROOT_PUBLIC_SURFACE",
    "SERVICE_API_SURFACE",
    "PublicSurfaceEntry",
    "canonical_surface_by_module",
    "legacy_surface_by_module",
    "modules_for",
    "public_surface_by_module",
    "repo_root_facade_module_names",
    "root_package_exports_by_name",
    "root_facade_module_names",
    "surface_by_kind",
]
