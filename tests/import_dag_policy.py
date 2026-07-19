from __future__ import annotations

CONTROLLED_LAZY_IMPORT_FILES = frozenset(
    {
        "rag_modules/__init__.py",
        "rag_modules/graph/__init__.py",
        "rag_modules/infra/__init__.py",
        "rag_modules/query_understanding/__init__.py",
        "rag_modules/retrieval/__init__.py",
        "rag_modules/routing/__init__.py",
    }
)

EXACT_MODULE_NODES = {
    "rag_modules": "package_root",
    "rag_modules.evaluation": "evaluation",
    "rag_modules.langchain_document_adapter": "langchain_adapter",
    "rag_modules.public_surface_manifest": "public_surface",
    "rag_modules.safe_logging": "safe_logging",
    "rag_modules.telemetry": "telemetry",
    "rag_modules.trace_privacy": "trace_privacy",
}

NODE_PREFIXES = {
    "app": ("rag_modules.app",),
    "application": ("rag_modules.application",),
    "build_pipeline": ("rag_modules.build_pipeline",),
    "configuration": ("rag_modules.configuration",),
    "contracts": ("rag_modules.contracts",),
    "domain": ("rag_modules.domain",),
    "domains": ("rag_modules.domains",),
    "evidence_processing": ("rag_modules.evidence_processing",),
    "generation": ("rag_modules.generation",),
    "graph": ("rag_modules.graph",),
    "graph_index": ("rag_modules.graph_index",),
    "infra": ("rag_modules.infra",),
    "interfaces": ("rag_modules.interfaces",),
    "kernel": ("rag_modules.kernel",),
    "observability": ("rag_modules.observability",),
    "query_policy": ("rag_modules.query_policy",),
    "query_understanding": ("rag_modules.query_understanding",),
    "retrieval": ("rag_modules.retrieval",),
    "routing": ("rag_modules.routing",),
    "runtime": ("rag_modules.runtime",),
}

ALLOWED_IMPORTS = {
    "package_root": frozenset({"app", "application", "generation", "infra"}),
    "app": frozenset(
        {
            "application",
            "build_pipeline",
            "configuration",
            "contracts",
            "domains",
            "generation",
            "graph",
            "infra",
            "kernel",
            "observability",
            "query_policy",
            "query_understanding",
            "retrieval",
            "routing",
            "runtime",
            "telemetry",
        }
    ),
    "application": frozenset({"contracts", "kernel", "safe_logging"}),
    "build_pipeline": frozenset(
        {
            "configuration",
            "contracts",
            "domain",
            "domains",
            "infra",
            "kernel",
            "runtime",
            "safe_logging",
        }
    ),
    "configuration": frozenset({"contracts", "domains", "kernel", "query_policy"}),
    "contracts": frozenset({"kernel"}),
    "domain": frozenset({"domains", "kernel"}),
    "domains": frozenset({"kernel"}),
    "evidence_processing": frozenset({"contracts"}),
    "generation": frozenset(
        {
            "configuration",
            "contracts",
            "evidence_processing",
            "infra",
            "kernel",
            "query_policy",
            "safe_logging",
        }
    ),
    "graph": frozenset(
        {
            "configuration",
            "contracts",
            "domains",
            "evidence_processing",
            "graph_index",
            "kernel",
            "query_policy",
            "query_understanding",
            "retrieval",
            "runtime",
            "safe_logging",
        }
    ),
    "graph_index": frozenset({"kernel", "query_policy", "query_understanding"}),
    "infra": frozenset({"contracts", "kernel", "safe_logging"}),
    "interfaces": frozenset(
        {
            "app",
            "application",
            "configuration",
            "contracts",
            "domains",
            "kernel",
            "query_policy",
            "runtime",
            "safe_logging",
            "telemetry",
        }
    ),
    "kernel": frozenset(),
    "observability": frozenset(
        {"configuration", "contracts", "kernel", "safe_logging", "trace_privacy"}
    ),
    "query_policy": frozenset({"domains"}),
    "query_understanding": frozenset({"contracts", "kernel", "query_policy", "safe_logging"}),
    "retrieval": frozenset(
        {
            "configuration",
            "contracts",
            "evidence_processing",
            "graph_index",
            "infra",
            "kernel",
            "query_understanding",
            "runtime",
            "safe_logging",
        }
    ),
    "routing": frozenset(
        {
            "contracts",
            "kernel",
            "query_policy",
            "query_understanding",
            "retrieval",
            "safe_logging",
        }
    ),
    "runtime": frozenset({"contracts", "kernel", "safe_logging"}),
    "evaluation": frozenset(),
    "langchain_adapter": frozenset({"kernel"}),
    "public_surface": frozenset(),
    "safe_logging": frozenset(),
    "telemetry": frozenset(),
    "trace_privacy": frozenset({"contracts"}),
}
