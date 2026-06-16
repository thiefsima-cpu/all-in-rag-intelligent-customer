"""Compatibility facade for split graph index modules."""

from .graph.indexing import EntityKeyValue, GraphIndexingModule, RelationKeyValue

__all__ = ["EntityKeyValue", "GraphIndexingModule", "RelationKeyValue"]
