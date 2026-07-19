"""Customer-service document mapping and deterministic semantic extraction."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...kernel.documents import TextDocument
from ...kernel.json_types import JsonObject, coerce_json_object
from ..contracts import (
    DomainDocumentMapper,
    DomainExtraction,
    ExtractedEntity,
    ExtractedRelation,
)

_ORDER_PATTERN = re.compile(r"(?:订单(?:号)?|order)\s*[#：:]?\s*([A-Za-z0-9_-]{4,64})", re.I)
_POLICY_PATTERN = re.compile(
    r"(?:政策|policy)\s*(?:编号|id)?\s*[#：:]?\s*([A-Za-z0-9_.-]{3,64})", re.I
)
_DURATION_PATTERN = re.compile(r"(\d+)\s*(天|日|个月|月|年)")
_DOCUMENT_TYPES = {
    "order": "Order",
    "refund_policy": "RefundPolicy",
    "warranty_policy": "WarrantyPolicy",
    "invoice_policy": "InvoicePolicy",
    "service_policy": "ServicePolicy",
    "product": "Product",
    "support_article": "SupportArticle",
}


def _text(payload: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _safe_attributes(payload: Mapping[str, Any]) -> JsonObject:
    public_keys = (
        "document_type",
        "status",
        "policy_id",
        "product_sku",
        "effective_from",
        "effective_to",
        "version",
        "source_uri",
        "updated_at",
    )
    return {
        key: payload[key]
        for key in public_keys
        if key in payload and payload[key] not in (None, "", [], {})
    }


class CustomerServiceDocumentMapper(DomainDocumentMapper):
    """Map policies, orders, products, and support articles to neutral documents."""

    def map_document(self, payload: Mapping[str, Any]) -> TextDocument:
        content = _text(payload, "content", "body", "description", "text")
        title = _text(payload, "title", "name", "subject")
        entity_id = _text(
            payload,
            "entity_id",
            "node_id",
            "id",
            "order_id",
            "policy_id",
            "product_sku",
        )
        document_type = _text(payload, "document_type", "type") or "support_article"
        entity_type = _DOCUMENT_TYPES.get(document_type, document_type or "SupportArticle")
        entity_name = title or entity_id
        attributes = _safe_attributes(payload)
        metadata: JsonObject = {
            "domain": "customer_service",
            "entity_id": entity_id,
            "entity_name": entity_name,
            "entity_type": entity_type,
            "node_id": entity_id,
            "node_type": entity_type,
            "doc_type": document_type,
            "source": _text(payload, "source", "source_uri") or "knowledge_base",
            "attributes": attributes,
            **attributes,
        }
        extraction = self.extract(payload)
        metadata["semantic_entities"] = [
            {
                "entity_id": entity.entity_id,
                "entity_name": entity.entity_name,
                "entity_type": entity.entity_type,
                "attributes": dict(entity.attributes),
            }
            for entity in extraction.entities
        ]
        metadata["semantic_relations"] = [
            {
                "source_id": relation.source_id,
                "relation_type": relation.relation_type,
                "target_id": relation.target_id,
                "attributes": dict(relation.attributes),
            }
            for relation in extraction.relations
        ]
        rendered = f"# {entity_name}\n\n{content}" if title else content
        return TextDocument(content=rendered.strip(), metadata=metadata)

    def extract(self, payload: Mapping[str, Any]) -> DomainExtraction:
        content = "\n".join(
            filter(None, (_text(payload, "title", "name"), _text(payload, "content", "body")))
        )
        document_type = _text(payload, "document_type", "type") or "support_article"
        entity_type = _DOCUMENT_TYPES.get(document_type, document_type or "SupportArticle")
        primary_id = _text(
            payload,
            "entity_id",
            "node_id",
            "id",
            "order_id",
            "policy_id",
            "product_sku",
        )
        primary_name = _text(payload, "title", "name", "subject") or primary_id
        entities: list[ExtractedEntity] = []
        relations: list[ExtractedRelation] = []
        if primary_id or primary_name:
            entities.append(
                ExtractedEntity(
                    entity_id=primary_id or primary_name,
                    entity_name=primary_name or primary_id,
                    entity_type=entity_type,
                    attributes=_safe_attributes(payload),
                )
            )
        source_id = primary_id or primary_name
        order_ids = {_text(payload, "order_id"), *_ORDER_PATTERN.findall(content)} - {""}
        policy_ids = {_text(payload, "policy_id"), *_POLICY_PATTERN.findall(content)} - {""}
        product_sku = _text(payload, "product_sku", "sku")
        for order_id in sorted(order_ids):
            if order_id != source_id:
                entities.append(ExtractedEntity(order_id, order_id, "Order"))
                relations.append(ExtractedRelation(source_id, "DESCRIBES_ORDER", order_id))
        for policy_id in sorted(policy_ids):
            if policy_id != source_id:
                entities.append(ExtractedEntity(policy_id, policy_id, "ServicePolicy"))
                relation_type = "GOVERNED_BY" if entity_type == "Order" else "REFERENCES_POLICY"
                relations.append(ExtractedRelation(source_id, relation_type, policy_id))
        if product_sku and product_sku != source_id:
            entities.append(ExtractedEntity(product_sku, product_sku, "Product"))
            relation_type = "CONTAINS_PRODUCT" if entity_type == "Order" else "APPLIES_TO"
            relations.append(ExtractedRelation(source_id, relation_type, product_sku))
        durations = [f"{amount}{unit}" for amount, unit in _DURATION_PATTERN.findall(content)]
        if durations and source_id and entity_type.endswith("Policy"):
            term_id = f"{source_id}::term"
            term_attributes = coerce_json_object({"durations": durations})
            entities.append(
                ExtractedEntity(
                    entity_id=term_id,
                    entity_name="、".join(durations),
                    entity_type="PolicyTerm",
                    attributes=term_attributes,
                )
            )
            relations.append(
                ExtractedRelation(
                    source_id,
                    "HAS_TERM",
                    term_id,
                    term_attributes,
                )
            )
        supersedes = _text(payload, "supersedes")
        if supersedes and source_id:
            entities.append(ExtractedEntity(supersedes, supersedes, entity_type))
            relations.append(ExtractedRelation(source_id, "SUPERSEDES", supersedes))
        return DomainExtraction(entities=tuple(entities), relations=tuple(relations))


__all__ = ["CustomerServiceDocumentMapper"]
