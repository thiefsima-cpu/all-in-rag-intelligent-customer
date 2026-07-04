from __future__ import annotations

import ast
from pathlib import Path

from rag_modules.contracts.graph import GraphQuery
from rag_modules.contracts.runtime.analysis import QueryAnalysis
from rag_modules.contracts.runtime.errors import RuntimeErrorDetail
from rag_modules.contracts.runtime.generation import GenerationSnapshot
from rag_modules.contracts.runtime.graph import GraphRetrievalSnapshot
from rag_modules.contracts.runtime.retrieval import HybridRetrievalOutcome
from rag_modules.contracts.runtime.workflows import RouteResolution
from rag_modules.kernel.artifacts import (
    ArtifactManifest,
    DocumentArtifactResult,
    DocumentArtifactSignatures,
    DocumentArtifactStats,
)
from rag_modules.kernel.documents import TextDocument
from rag_modules.kernel.retrieval import CandidateSourceDegradationStrategy
from rag_modules.kernel.routing import RouteStatistics, SearchStrategy


def test_shared_types_have_canonical_module_ownership() -> None:
    expected_modules = {
        ArtifactManifest: "rag_modules.kernel.artifacts",
        DocumentArtifactResult: "rag_modules.kernel.artifacts",
        DocumentArtifactSignatures: "rag_modules.kernel.artifacts",
        DocumentArtifactStats: "rag_modules.kernel.artifacts",
        TextDocument: "rag_modules.kernel.documents",
        CandidateSourceDegradationStrategy: "rag_modules.kernel.retrieval",
        RouteStatistics: "rag_modules.kernel.routing",
        SearchStrategy: "rag_modules.kernel.routing",
        GraphQuery: "rag_modules.contracts.graph",
        GenerationSnapshot: "rag_modules.contracts.runtime.generation",
        GraphRetrievalSnapshot: "rag_modules.contracts.runtime.graph",
        HybridRetrievalOutcome: "rag_modules.contracts.runtime.retrieval",
        QueryAnalysis: "rag_modules.contracts.runtime.analysis",
        RouteResolution: "rag_modules.contracts.runtime.workflows",
        RuntimeErrorDetail: "rag_modules.contracts.runtime.errors",
    }

    assert {value: value.__module__ for value in expected_modules} == expected_modules


def test_kernel_has_no_subsystem_imports() -> None:
    kernel_dir = Path(__file__).parents[1] / "rag_modules" / "kernel"
    forbidden = {
        "app",
        "build_pipeline",
        "configuration",
        "generation",
        "graph",
        "infra",
        "interfaces",
        "query_policy",
        "query_understanding",
        "retrieval",
        "routing",
        "runtime",
    }
    violations: list[str] = []

    for path in kernel_dir.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    names = [module.split(".", 1)[0]] if module else []
                else:
                    names = [module]
            else:
                continue
            for name in names:
                parts = name.split(".")
                if "rag_modules" in parts:
                    parts = parts[parts.index("rag_modules") + 1 :]
                if parts and parts[0] in forbidden:
                    violations.append(f"{path.name}:{node.lineno}: {name}")

    assert violations == []
