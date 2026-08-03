"""Domain-neutral entity KV materialization for graph index retrieval."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Dict, List

from ..query_understanding.registry import dedupe_preserve_order
from .models import EntityKeyValue
from .store import GraphIndexStore

logger = logging.getLogger(__name__)


def _domain_property_values(props: Mapping[str, object]) -> List[str]:
    values: List[str] = []
    for value in props.values():
        if isinstance(value, (str, int, float, bool)) and str(value).strip():
            values.append(str(value))
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value if str(item).strip())
    return dedupe_preserve_order(values)


def _add_domain_entity(entity: Any, store: GraphIndexStore) -> None:
    entity_id = str(entity.node_id)
    entity_name = str(getattr(entity, "name", "") or entity_id)
    labels = [str(label) for label in (getattr(entity, "labels", None) or []) if label]
    raw_properties = getattr(entity, "properties", {}) or {}
    props = dict(raw_properties) if isinstance(raw_properties, Mapping) else {}
    domain_name = str(props.get("domain") or "").strip()
    entity_type = labels[0] if labels else str(props.get("entity_type") or "Entity")
    property_values = _domain_property_values(props)
    content_parts = [f"entity_name: {entity_name}", f"entity_type: {entity_type}"]
    for key, value in props.items():
        if value not in (None, "", [], {}):
            content_parts.append(f"{key}: {value}")
    store.add_entity(
        entity_id,
        EntityKeyValue(
            entity_name=entity_name,
            index_keys=dedupe_preserve_order([entity_name, entity_id, *property_values]),
            value_content="\n".join(content_parts),
            entity_type=entity_type,
            metadata={
                "node_id": entity_id,
                "labels": labels,
                "domain": domain_name,
                "properties": props,
            },
        ),
        extra_keys=[entity_name],
    )


class EntityIndexBuilder:
    """Build entity key-value payloads from graph nodes."""

    def build(
        self,
        *,
        entities: List[Any],
        store: GraphIndexStore,
    ) -> Dict[str, EntityKeyValue]:
        logger.info("Building domain entity key-value index...")
        for entity in entities:
            _add_domain_entity(entity, store)
        logger.info("Domain entity index built with %s entities.", len(store.entity_kv_store))
        return store.entity_kv_store

    def build_domain_entities(
        self,
        *,
        entities: List[Any],
        store: GraphIndexStore,
    ) -> Dict[str, EntityKeyValue]:
        """Compatibility alias for the domain-neutral entity builder."""

        return self.build(entities=entities, store=store)
