"""Relation KV materialization for graph index retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES
from ..query_policy import get_query_policy
from ..query_understanding import dedupe_preserve_order, relation_index_terms
from .models import EntityKeyValue, RelationKeyValue
from .store import GraphIndexStore

logger = logging.getLogger(__name__)


class RelationIndexBuilder:
    """Build relation key-value payloads from graph edges and semantic tags."""

    def __init__(self, config, llm_client=None) -> None:
        self.config = config
        self.llm_client = llm_client
        policy = get_query_policy()
        self.relation_index_keywords = policy.relations.relation_index_keywords
        self.relation_index_suffix_templates = policy.relations.relation_index_suffix_templates
        self.semantic_relation_key_specs = dict(policy.graph.reasoning.semantic_relation_key_specs)

    def build(
        self,
        *,
        relationships: List[Tuple[str, str, str]],
        store: GraphIndexStore,
    ) -> Dict[str, RelationKeyValue]:
        logger.info("Building relation key-value index...")
        for index, (source_id, relation_type, target_id) in enumerate(relationships):
            source_entity = store.entity_kv_store.get(str(source_id))
            target_entity = store.entity_kv_store.get(str(target_id))
            if not source_entity or not target_entity:
                continue

            relation_id = f"rel_{index}_{source_id}_{target_id}"
            value_content = "\n".join(
                [
                    f"relation_type: {relation_type}",
                    f"source_entity: {source_entity.entity_name} ({source_entity.entity_type})",
                    f"target_entity: {target_entity.entity_name} ({target_entity.entity_type})",
                ]
            )
            relation_kv = RelationKeyValue(
                relation_id=relation_id,
                index_keys=self._generate_relation_index_keys(
                    source_entity,
                    target_entity,
                    relation_type,
                ),
                value_content=value_content,
                relation_type=relation_type,
                source_entity=str(source_id),
                target_entity=str(target_id),
                metadata={
                    "source_name": source_entity.entity_name,
                    "target_name": target_entity.entity_name,
                    "created_from_graph": True,
                },
            )
            store.add_relation(relation_kv)

        self._add_semantic_relation_key_values(store)
        logger.info(
            "Relation key-value index built with %s relations.",
            len(store.relation_kv_store),
        )
        return store.relation_kv_store

    def _add_semantic_relation_key_values(self, store: GraphIndexStore) -> None:
        counter = len(store.relation_kv_store)
        simple_semantic_relations = [
            rel_type
            for rel_type in SEMANTIC_RELATION_TYPES
            if rel_type not in self.semantic_relation_key_specs
        ]

        for source_id, source_entity in list(store.entity_kv_store.items()):
            if source_entity.entity_type != "Recipe":
                continue
            props = source_entity.metadata.get("properties", {}) or {}
            semantic_relations = props.get("semantic_relations", {}) or {}
            semantic_items: List[Tuple[str, str, List[str]]] = []

            for rel_type in simple_semantic_relations:
                for target in semantic_relations.get(rel_type, []) or []:
                    semantic_items.append((rel_type, str(target), [str(target), rel_type]))

            semantic_items.extend(self._semantic_relation_items(semantic_relations))

            for rel_type, target_name, keys in semantic_items:
                relation_id = f"semantic_rel_{counter}_{source_id}_{rel_type}_{target_name}"
                counter += 1
                value_content = "\n".join(
                    [
                        f"relation_type: {rel_type}",
                        f"source_recipe: {source_entity.entity_name}",
                        f"semantic_target: {target_name}",
                    ]
                )
                relation_kv = RelationKeyValue(
                    relation_id=relation_id,
                    index_keys=dedupe_preserve_order([rel_type, target_name, *keys]),
                    value_content=value_content,
                    relation_type=rel_type,
                    source_entity=str(source_id),
                    target_entity=str(target_name),
                    metadata={
                        "source_name": source_entity.entity_name,
                        "target_name": target_name,
                        "created_from_semantic_schema": True,
                    },
                )
                store.add_relation(relation_kv)

    def _generate_relation_index_keys(
        self,
        source_entity: EntityKeyValue,
        target_entity: EntityKeyValue,
        relation_type: str,
    ) -> List[str]:
        source_props = source_entity.metadata.get("properties", {}) or {}
        target_props = target_entity.metadata.get("properties", {}) or {}
        keys = relation_index_terms(
            relation_type,
            source_entity.entity_name,
            target_entity.entity_name,
        )
        keys.extend(
            str(value)
            for value in (
                source_props.get("category"),
                source_props.get("cuisineType"),
                target_props.get("category"),
                target_props.get("cuisineType"),
                *self.relation_index_keywords.get(relation_type, ()),
            )
            if value
        )
        suffix_template = self.relation_index_suffix_templates.get(relation_type)
        if suffix_template:
            keys.append(suffix_template.format(source_entity=source_entity.entity_name))

        if getattr(self.config, "enable_llm_relation_keys", False):
            keys.extend(
                self._compat_relation_key_expansion(
                    source_entity=source_entity,
                    target_entity=target_entity,
                    relation_type=relation_type,
                )
            )
        return dedupe_preserve_order(keys)

    def _semantic_relation_items(
        self,
        semantic_relations: dict[str, Any],
    ) -> List[Tuple[str, str, List[str]]]:
        items: List[Tuple[str, str, List[str]]] = []
        for relation_type, spec in self.semantic_relation_key_specs.items():
            for payload in semantic_relations.get(relation_type, []) or []:
                if not isinstance(payload, dict):
                    continue
                target = str(payload.get(spec.target_field) or "").strip()
                keys: List[str] = []
                for field in spec.key_fields:
                    value = payload.get(field)
                    if isinstance(value, (list, tuple)):
                        keys.extend(str(item) for item in value if str(item).strip())
                    elif str(value or "").strip():
                        keys.append(str(value))
                if target:
                    items.append((str(relation_type), target, keys))
        return items

    @staticmethod
    def _compat_relation_key_expansion(
        *,
        source_entity: EntityKeyValue,
        target_entity: EntityKeyValue,
        relation_type: str,
    ) -> List[str]:
        return relation_index_terms(
            relation_type,
            source_entity.entity_name,
            target_entity.entity_name,
        )
