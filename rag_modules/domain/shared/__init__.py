"""Shared recipe/query domain helpers used across RAG subsystems."""

from .semantic_schema import infer_recipe_semantics

__all__ = [
    "infer_recipe_semantics",
]
