"""In-memory graph index store and lookup helpers."""

from __future__ import annotations

from collections import defaultdict
from typing import DefaultDict, Dict, Iterable, List

from ..query_understanding import dedupe_preserve_order
from .models import EntityKeyValue, RelationKeyValue


def _append_unique(mapping, key: str, value: str) -> None:
    if not key or not value:
        return
    if value not in mapping[key]:
        mapping[key].append(value)


class GraphIndexStore:
    """Own graph entity/relation KV payloads plus lookup mappings."""

    def __init__(self) -> None:
        self.entity_kv_store: Dict[str, EntityKeyValue] = {}
        self.relation_kv_store: Dict[str, RelationKeyValue] = {}
        self.key_to_entities: DefaultDict[str, List[str]] = defaultdict(list)
        self.key_to_relations: DefaultDict[str, List[str]] = defaultdict(list)

    def add_entity(
        self,
        entity_id: str,
        entity_kv: EntityKeyValue,
        *,
        extra_keys: Iterable[str] | None = None,
    ) -> None:
        self.entity_kv_store[str(entity_id)] = entity_kv
        for key in dedupe_preserve_order([*(extra_keys or []), *(entity_kv.index_keys or [])]):
            _append_unique(self.key_to_entities, key, str(entity_id))

    def add_relation(
        self,
        relation_kv: RelationKeyValue,
        *,
        extra_keys: Iterable[str] | None = None,
    ) -> None:
        relation_id = str(relation_kv.relation_id)
        self.relation_kv_store[relation_id] = relation_kv
        for key in dedupe_preserve_order([*(extra_keys or []), *(relation_kv.index_keys or [])]):
            _append_unique(self.key_to_relations, key, relation_id)

    def rebuild_key_mappings(self) -> None:
        self.key_to_entities.clear()
        self.key_to_relations.clear()

        for entity_id, entity_kv in self.entity_kv_store.items():
            for key in entity_kv.index_keys:
                _append_unique(self.key_to_entities, key, str(entity_id))

        for relation_id, relation_kv in self.relation_kv_store.items():
            for key in relation_kv.index_keys:
                _append_unique(self.key_to_relations, key, str(relation_id))

    def get_entities_by_key(self, key: str) -> List[EntityKeyValue]:
        entity_ids = self.key_to_entities.get(str(key), [])
        return [self.entity_kv_store[eid] for eid in entity_ids if eid in self.entity_kv_store]

    def get_relations_by_key(self, key: str) -> List[RelationKeyValue]:
        relation_ids = self.key_to_relations.get(str(key), [])
        return [
            self.relation_kv_store[rid] for rid in relation_ids if rid in self.relation_kv_store
        ]

    def deduplicate_entities_and_relations(self) -> None:
        name_to_entities = defaultdict(list)
        for entity_id, entity_kv in self.entity_kv_store.items():
            name_to_entities[str(entity_kv.entity_name)].append(str(entity_id))

        entities_to_remove: List[str] = []
        for entity_ids in name_to_entities.values():
            if len(entity_ids) <= 1:
                continue
            primary_id = entity_ids[0]
            primary_entity = self.entity_kv_store[primary_id]
            for entity_id in entity_ids[1:]:
                duplicate_entity = self.entity_kv_store[entity_id]
                primary_entity.value_content += f"\n\n补充信息: {duplicate_entity.value_content}"
                primary_entity.index_keys = dedupe_preserve_order(
                    [*primary_entity.index_keys, *duplicate_entity.index_keys]
                )
                primary_entity.metadata = {
                    **dict(duplicate_entity.metadata or {}),
                    **dict(primary_entity.metadata or {}),
                }
                entities_to_remove.append(entity_id)

        for entity_id in entities_to_remove:
            self.entity_kv_store.pop(entity_id, None)

        relation_signature_to_ids = defaultdict(list)
        for relation_id, relation_kv in self.relation_kv_store.items():
            signature = f"{relation_kv.source_entity}_{relation_kv.target_entity}_{relation_kv.relation_type}"
            relation_signature_to_ids[signature].append(str(relation_id))

        relations_to_remove: List[str] = []
        for relation_ids in relation_signature_to_ids.values():
            if len(relation_ids) <= 1:
                continue
            primary_id = relation_ids[0]
            primary_relation = self.relation_kv_store[primary_id]
            for relation_id in relation_ids[1:]:
                duplicate_relation = self.relation_kv_store[relation_id]
                primary_relation.index_keys = dedupe_preserve_order(
                    [*primary_relation.index_keys, *duplicate_relation.index_keys]
                )
                primary_relation.metadata = {
                    **dict(duplicate_relation.metadata or {}),
                    **dict(primary_relation.metadata or {}),
                }
                relations_to_remove.append(relation_id)

        for relation_id in relations_to_remove:
            self.relation_kv_store.pop(relation_id, None)

        self.rebuild_key_mappings()

    def get_statistics(self) -> Dict[str, object]:
        return {
            "total_entities": len(self.entity_kv_store),
            "total_relations": len(self.relation_kv_store),
            "total_entity_keys": sum(len(kv.index_keys) for kv in self.entity_kv_store.values()),
            "total_relation_keys": sum(
                len(kv.index_keys) for kv in self.relation_kv_store.values()
            ),
            "entity_types": {
                "Recipe": len(
                    [kv for kv in self.entity_kv_store.values() if kv.entity_type == "Recipe"]
                ),
                "Ingredient": len(
                    [kv for kv in self.entity_kv_store.values() if kv.entity_type == "Ingredient"]
                ),
                "CookingStep": len(
                    [kv for kv in self.entity_kv_store.values() if kv.entity_type == "CookingStep"]
                ),
            },
        }
