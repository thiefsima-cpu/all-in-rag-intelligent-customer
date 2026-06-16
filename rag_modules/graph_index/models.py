"""Graph index key-value models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class EntityKeyValue:
    """Entity-oriented key-value payload for in-memory graph retrieval."""

    entity_name: str
    index_keys: List[str]
    value_content: str
    entity_type: str
    metadata: Dict[str, Any]


@dataclass
class RelationKeyValue:
    """Relation-oriented key-value payload for in-memory graph retrieval."""

    relation_id: str
    index_keys: List[str]
    value_content: str
    relation_type: str
    source_entity: str
    target_entity: str
    metadata: Dict[str, Any]
