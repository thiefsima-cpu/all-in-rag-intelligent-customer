"""Relation KV materialization for graph index retrieval."""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from ..query_understanding import dedupe_preserve_order, relation_index_terms
from ..semantic_schema import SEMANTIC_RELATION_TYPES
from .models import EntityKeyValue, RelationKeyValue
from .store import GraphIndexStore

logger = logging.getLogger(__name__)

_RELATION_TYPE_HINTS: Dict[str, Tuple[str, ...]] = {
    "REQUIRES": ("食材搭配", "烹饪原料"),
    "CONTAINS_STEP": ("制作步骤", "烹饪过程", "制作方法"),
    "BELONGS_TO_CATEGORY": ("菜品分类", "美食类别"),
    "HAS_FLAVOR": ("口味", "风味"),
    "USES_TECHNIQUE": ("技法", "技巧"),
    "HAS_DIET_TAG": ("饮食偏好", "素食", "素菜"),
    "HAS_HEALTH_TAG": ("健康限制", "少油", "低脂", "低糖", "控糖", "低盐", "减脂"),
    "HAS_CUISINE_STYLE": ("菜系", "风格"),
    "HAS_INGREDIENT_CATEGORY": ("食材类别", "分类"),
    "HAS_TIME_PROFILE": ("时间", "时长", "快手", "省时"),
    "HAS_DIFFICULTY_LEVEL": ("难度", "简单", "新手", "易做"),
    "CONTRIBUTES_TO": ("贡献", "形成", "影响"),
    "INGREDIENT_CONTRIBUTES_TO": ("调味", "口感", "风味"),
    "TECHNIQUE_MODIFIES_TEXTURE": ("口感", "软嫩", "酥脆", "质地"),
}


class RelationIndexBuilder:
    """Build relation key-value payloads from graph edges and semantic tags."""

    def __init__(self, config, llm_client=None) -> None:
        self.config = config
        self.llm_client = llm_client

    def build(
        self,
        *,
        relationships: List[Tuple[str, str, str]],
        store: GraphIndexStore,
    ) -> Dict[str, RelationKeyValue]:
        logger.info("开始构建关系键值索引...")
        for index, (source_id, relation_type, target_id) in enumerate(relationships):
            source_entity = store.entity_kv_store.get(str(source_id))
            target_entity = store.entity_kv_store.get(str(target_id))
            if not source_entity or not target_entity:
                continue

            relation_id = f"rel_{index}_{source_id}_{target_id}"
            value_content = "\n".join(
                [
                    f"关系类型: {relation_type}",
                    f"源实体: {source_entity.entity_name} ({source_entity.entity_type})",
                    f"目标实体: {target_entity.entity_name} ({target_entity.entity_type})",
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
        logger.info("关系键值索引构建完成，共 %s 个关系", len(store.relation_kv_store))
        return store.relation_kv_store

    def _add_semantic_relation_key_values(self, store: GraphIndexStore) -> None:
        counter = len(store.relation_kv_store)
        simple_semantic_relations = [
            rel_type
            for rel_type in SEMANTIC_RELATION_TYPES
            if rel_type
            not in {"CONTRIBUTES_TO", "INGREDIENT_CONTRIBUTES_TO", "TECHNIQUE_MODIFIES_TEXTURE"}
        ]

        for source_id, source_entity in list(store.entity_kv_store.items()):
            if source_entity.entity_type != "Recipe":
                continue
            props = source_entity.metadata.get("properties", {}) or {}
            semantic_relations = props.get("semantic_relations", {}) or {}
            semantic_items = []

            for rel_type in simple_semantic_relations:
                for target in semantic_relations.get(rel_type, []) or []:
                    semantic_items.append((rel_type, target, [target, rel_type]))

            for item in semantic_relations.get("CONTRIBUTES_TO", []) or []:
                effect = item.get("effect")
                causes = item.get("causes", [])
                if effect:
                    semantic_items.append(("CONTRIBUTES_TO", effect, [effect, *list(causes or [])]))

            for item in semantic_relations.get("INGREDIENT_CONTRIBUTES_TO", []) or []:
                source = item.get("source")
                effect = item.get("effect")
                if source and effect:
                    semantic_items.append(
                        (
                            "INGREDIENT_CONTRIBUTES_TO",
                            effect,
                            [source, effect, "INGREDIENT_CONTRIBUTES_TO"],
                        )
                    )

            for item in semantic_relations.get("TECHNIQUE_MODIFIES_TEXTURE", []) or []:
                source = item.get("source")
                effect = item.get("effect")
                if source and effect:
                    semantic_items.append(
                        (
                            "TECHNIQUE_MODIFIES_TEXTURE",
                            effect,
                            [source, effect, "TECHNIQUE_MODIFIES_TEXTURE"],
                        )
                    )

            for rel_type, target_name, keys in semantic_items:
                relation_id = f"semantic_rel_{counter}_{source_id}_{rel_type}_{target_name}"
                counter += 1
                value_content = "\n".join(
                    [
                        f"关系类型: {rel_type}",
                        f"源菜品: {source_entity.entity_name}",
                        f"语义目标: {target_name}",
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
                *_RELATION_TYPE_HINTS.get(relation_type, ()),
            )
            if value
        )
        if relation_type == "REQUIRES":
            keys.append(f"{source_entity.entity_name}_食材")
        if relation_type == "CONTAINS_STEP":
            keys.append(f"{source_entity.entity_name}_步骤")

        if getattr(self.config, "enable_llm_relation_keys", False):
            keys.extend(
                self._compat_relation_key_expansion(
                    source_entity=source_entity,
                    target_entity=target_entity,
                    relation_type=relation_type,
                )
            )
        return dedupe_preserve_order(keys)

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
