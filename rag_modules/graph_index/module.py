"""Graph index orchestration facade over split builders and store."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .entity_index_builder import EntityIndexBuilder
from .models import EntityKeyValue, RelationKeyValue
from .relation_index_builder import RelationIndexBuilder
from .snapshot import from_cache_dict, to_cache_dict
from .store import GraphIndexStore


class GraphIndexingModule:
    """Public graph indexing surface backed by split entity/relation builders."""

    def __init__(
        self,
        config,
        llm_client,
        *,
        store: GraphIndexStore | None = None,
        entity_builder: EntityIndexBuilder | None = None,
        relation_builder: RelationIndexBuilder | None = None,
    ) -> None:
        self.config = config
        self.llm_client = llm_client
        self.store = store or GraphIndexStore()
        self.entity_builder = entity_builder or EntityIndexBuilder()
        self.relation_builder = relation_builder or RelationIndexBuilder(
            config=config,
            llm_client=llm_client,
        )

    @property
    def entity_kv_store(self) -> Dict[str, EntityKeyValue]:
        return self.store.entity_kv_store

    @entity_kv_store.setter
    def entity_kv_store(self, value: Dict[str, EntityKeyValue]) -> None:
        self.store.entity_kv_store = dict(value or {})

    @property
    def relation_kv_store(self) -> Dict[str, RelationKeyValue]:
        return self.store.relation_kv_store

    @relation_kv_store.setter
    def relation_kv_store(self, value: Dict[str, RelationKeyValue]) -> None:
        self.store.relation_kv_store = dict(value or {})

    @property
    def key_to_entities(self):
        return self.store.key_to_entities

    @key_to_entities.setter
    def key_to_entities(self, value) -> None:
        self.store.key_to_entities = value

    @property
    def key_to_relations(self):
        return self.store.key_to_relations

    @key_to_relations.setter
    def key_to_relations(self, value) -> None:
        self.store.key_to_relations = value

    def create_entity_key_values(
        self,
        recipes: List[Any],
        ingredients: List[Any],
        cooking_steps: List[Any],
    ) -> Dict[str, EntityKeyValue]:
        return self.entity_builder.build(
            recipes=recipes,
            ingredients=ingredients,
            cooking_steps=cooking_steps,
            store=self.store,
        )

    def create_relation_key_values(
        self,
        relationships: List[Tuple[str, str, str]],
    ) -> Dict[str, RelationKeyValue]:
        return self.relation_builder.build(
            relationships=relationships,
            store=self.store,
        )

    def to_cache_dict(self) -> Dict[str, Any]:
        return to_cache_dict(self.store)

    def from_cache_dict(self, payload: Dict[str, Any]) -> bool:
        return from_cache_dict(self.store, payload)

    def deduplicate_entities_and_relations(self) -> None:
        self.store.deduplicate_entities_and_relations()

    def _rebuild_key_mappings(self) -> None:
        self.store.rebuild_key_mappings()

    def get_entities_by_key(self, key: str) -> List[EntityKeyValue]:
        return self.store.get_entities_by_key(key)

    def get_relations_by_key(self, key: str) -> List[RelationKeyValue]:
        return self.store.get_relations_by_key(key)

    def get_statistics(self) -> Dict[str, Any]:
        return self.store.get_statistics()
