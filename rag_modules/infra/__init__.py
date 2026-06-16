"""Infrastructure-facing adapters."""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "MilvusIndexConstructionModule": ".milvus",
    "SemanticGraphSchemaWriter": ".semantic_graph_writer",
}

__all__ = ["MilvusIndexConstructionModule", "SemanticGraphSchemaWriter"]


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)


def __dir__() -> list[str]:
    return sorted(list(globals()) + __all__)
