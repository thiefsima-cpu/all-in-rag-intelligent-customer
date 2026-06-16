"""Snapshot serialization helpers for graph index state."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from typing import Any, Dict

from .models import EntityKeyValue, RelationKeyValue
from .store import GraphIndexStore

GRAPH_INDEX_VERSION = 3


def to_cache_dict(store: GraphIndexStore) -> Dict[str, Any]:
    return {
        "graph_index_version": GRAPH_INDEX_VERSION,
        "entity_kv_store": {
            str(entity_id): asdict(entity)
            for entity_id, entity in store.entity_kv_store.items()
        },
        "relation_kv_store": {
            str(relation_id): asdict(relation)
            for relation_id, relation in store.relation_kv_store.items()
        },
        "key_to_entities": {
            str(key): list(values)
            for key, values in store.key_to_entities.items()
        },
        "key_to_relations": {
            str(key): list(values)
            for key, values in store.key_to_relations.items()
        },
    }


def from_cache_dict(store: GraphIndexStore, payload: Dict[str, Any]) -> bool:
    if not payload:
        return False

    if int(payload.get("graph_index_version") or 0) != GRAPH_INDEX_VERSION:
        return False

    try:
        store.entity_kv_store = {
            str(entity_id): EntityKeyValue(
                entity_name=str(item.get("entity_name") or ""),
                index_keys=[str(value) for value in item.get("index_keys") or []],
                value_content=str(item.get("value_content") or ""),
                entity_type=str(item.get("entity_type") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
            for entity_id, item in (payload.get("entity_kv_store") or {}).items()
        }
        store.relation_kv_store = {
            str(relation_id): RelationKeyValue(
                relation_id=str(item.get("relation_id") or relation_id),
                index_keys=[str(value) for value in item.get("index_keys") or []],
                value_content=str(item.get("value_content") or ""),
                relation_type=str(item.get("relation_type") or ""),
                source_entity=str(item.get("source_entity") or ""),
                target_entity=str(item.get("target_entity") or ""),
                metadata=dict(item.get("metadata") or {}),
            )
            for relation_id, item in (payload.get("relation_kv_store") or {}).items()
        }
    except (AttributeError, TypeError, ValueError):
        return False
    store.key_to_entities = defaultdict(list)
    store.key_to_relations = defaultdict(list)

    for key, values in (payload.get("key_to_entities") or {}).items():
        store.key_to_entities[str(key)] = list(values or [])
    for key, values in (payload.get("key_to_relations") or {}).items():
        store.key_to_relations[str(key)] = list(values or [])

    if store.entity_kv_store and (not store.key_to_entities or not store.key_to_relations):
        store.rebuild_key_mappings()
    return bool(store.entity_kv_store or store.relation_kv_store)
