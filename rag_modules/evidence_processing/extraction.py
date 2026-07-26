"""Evidence unit extraction."""

from __future__ import annotations

from ..contracts import EvidenceDocument, JsonObject, coerce_float, coerce_json_object
from .helpers import (
    document_content,
    document_metadata,
    first_value,
    infer_evidence_type,
    stable_hash,
)
from .models import EvidenceUnit


def _json_object_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [coerce_json_object(item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _node_label_names(nodes: list[JsonObject]) -> dict[str, str]:
    labels_by_id: dict[str, str] = {}
    for node in nodes:
        node_id = str(node.get("id") or node.get("nodeId") or "")
        name = str(node.get("name") or node.get("title") or node_id or "")
        if node_id and name:
            labels_by_id[node_id] = name
    return labels_by_id


def _explicit_units(metadata: JsonObject, source: str, score: float) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    raw_units = metadata.get("evidence_units")
    for item in _json_object_list(raw_units):
        claim = str(item.get("claim") or "")
        if not claim:
            continue
        units.append(
            EvidenceUnit(
                unit_id=str(item.get("unit_id") or f"unit::{stable_hash(claim)}"),
                evidence_type=str(item.get("evidence_type") or "text"),
                claim=claim,
                source=str(item.get("source") or source),
                score=coerce_float(item.get("score"), score),
                entity_id=str(
                    item.get("entity_id")
                    or item.get("recipe_id")
                    or metadata.get("entity_id")
                    or metadata.get("recipe_id")
                    or ""
                ),
                entity_name=str(
                    item.get("entity_name")
                    or item.get("recipe_name")
                    or metadata.get("entity_name")
                    or metadata.get("recipe_name")
                    or ""
                ),
                domain=str(
                    metadata.get("domain")
                    or (
                        "recipe" if metadata.get("recipe_id") or metadata.get("recipe_name") else ""
                    )
                ),
                relation_type=str(item.get("relation_type") or ""),
                entities=_string_list(item.get("entities")),
                is_graph_evidence=bool(item.get("is_graph_evidence")),
                metadata=coerce_json_object(item.get("metadata")),
            )
        )
    return units


def _graph_payloads(graph_evidence: JsonObject) -> list[JsonObject]:
    primary = coerce_json_object(graph_evidence.get("primary"))
    merged = _json_object_list(graph_evidence.get("merged"))
    if primary or merged:
        return [primary, *merged]
    return [graph_evidence]


def _relationship_claim(
    relationship: object,
    labels_by_id: dict[str, str],
) -> tuple[str, str, list[str]] | None:
    if isinstance(relationship, str):
        return relationship, "", []
    if not isinstance(relationship, dict):
        return None
    relation_type = str(relationship.get("type") or relationship.get("relation_type") or "RELATED")
    start_id = str(relationship.get("startNodeId") or relationship.get("source_id") or "")
    end_id = str(relationship.get("endNodeId") or relationship.get("target_id") or "")
    start = str(relationship.get("source_name") or labels_by_id.get(start_id) or start_id or "")
    end = str(relationship.get("target_name") or labels_by_id.get(end_id) or end_id or "")
    if start and end:
        return f"{start} -[{relation_type}]-> {end}", relation_type, [start, end]
    return relation_type, relation_type, [item for item in (start, end) if item]


def _graph_entity_values(metadata: JsonObject) -> tuple[str, str, list[str]]:
    recipe_ids = _string_list(metadata.get("recipe_node_ids"))
    recipe_names = _string_list(metadata.get("recipe_names"))
    entity_id = (
        recipe_ids[0]
        if recipe_ids
        else str(
            metadata.get("entity_id") or metadata.get("recipe_id") or metadata.get("node_id") or ""
        )
    )
    entity_name = (
        recipe_names[0]
        if recipe_names
        else str(metadata.get("entity_name") or metadata.get("recipe_name") or "")
    )
    entity_names = _string_list(metadata.get("entity_names")) or recipe_names
    return entity_id, entity_name, entity_names


def _evidence_domain(metadata: JsonObject) -> str:
    return str(
        metadata.get("domain")
        or ("recipe" if metadata.get("recipe_id") or metadata.get("recipe_name") else "")
    )


def _graph_summary_unit(
    *,
    metadata: JsonObject,
    graph_evidence: JsonObject,
    source: str,
    score: float,
    entity_id: str,
    entity_name: str,
    entity_names: list[str],
) -> EvidenceUnit | None:
    description = str(graph_evidence.get("description") or "").strip()
    if not description:
        return None
    return EvidenceUnit(
        unit_id=f"unit::{stable_hash(description)}",
        evidence_type="graph_summary",
        claim=description,
        source=source,
        score=score,
        entity_id=entity_id,
        entity_name=entity_name,
        domain=_evidence_domain(metadata),
        entities=list(dict.fromkeys(entity_names + _string_list(metadata.get("matched_terms")))),
        is_graph_evidence=True,
        metadata={"search_type": metadata.get("search_type")},
    )


def _graph_relationship_unit(
    *,
    metadata: JsonObject,
    source: str,
    score: float,
    entity_id: str,
    entity_name: str,
    relationship_claim: tuple[str, str, list[str]],
) -> EvidenceUnit:
    claim, relation_type, entities = relationship_claim
    return EvidenceUnit(
        unit_id=f"unit::{stable_hash(claim)}",
        evidence_type="graph_relation",
        claim=claim,
        source=source,
        score=score,
        entity_id=entity_id,
        entity_name=entity_name,
        domain=_evidence_domain(metadata),
        relation_type=relation_type,
        entities=list(dict.fromkeys(entities)),
        is_graph_evidence=True,
        metadata={"search_type": metadata.get("search_type")},
    )


def _graph_relationship_units(
    *,
    metadata: JsonObject,
    graph_evidence: JsonObject,
    source: str,
    score: float,
) -> list[EvidenceUnit]:
    nodes = _json_object_list(graph_evidence.get("nodes")) or _json_object_list(
        graph_evidence.get("connected_nodes")
    )
    raw_relationships = graph_evidence.get("relationships")
    relationships = raw_relationships if isinstance(raw_relationships, list) else []
    labels_by_id = _node_label_names(nodes)
    entity_id, entity_name, entity_names = _graph_entity_values(metadata)
    units: list[EvidenceUnit] = []
    summary = _graph_summary_unit(
        metadata=metadata,
        graph_evidence=graph_evidence,
        source=source,
        score=score,
        entity_id=entity_id,
        entity_name=entity_name,
        entity_names=entity_names,
    )
    if summary is not None:
        units.append(summary)
    for relationship in relationships[:20]:
        relationship_claim = _relationship_claim(relationship, labels_by_id)
        if not relationship_claim or not relationship_claim[0]:
            continue
        units.append(
            _graph_relationship_unit(
                metadata=metadata,
                source=source,
                score=score,
                entity_id=entity_id,
                entity_name=entity_name,
                relationship_claim=relationship_claim,
            )
        )
    return units


def _fallback_unit(
    *,
    content: str,
    metadata: JsonObject,
    source: str,
    score: float,
) -> EvidenceUnit | None:
    claim = content.strip()[:260]
    if not claim:
        return None
    entity_name = str(metadata.get("entity_name") or metadata.get("recipe_name") or "")
    return EvidenceUnit(
        unit_id=f"unit::{stable_hash(claim)}",
        evidence_type=infer_evidence_type(metadata),
        claim=claim,
        source=source,
        score=score,
        entity_id=str(
            metadata.get("entity_id") or metadata.get("recipe_id") or metadata.get("node_id") or ""
        ),
        entity_name=entity_name,
        domain=_evidence_domain(metadata),
        entities=[entity_name] if entity_name else [],
        is_graph_evidence=False,
        metadata={"search_type": metadata.get("search_type")},
    )


def _dedupe_units(units: list[EvidenceUnit]) -> list[JsonObject]:
    seen: set[str] = set()
    deduped: list[JsonObject] = []
    for unit in units:
        key = unit.unit_id or unit.claim
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(unit.to_dict())
    return deduped[:30]


def _extraction_context(
    doc: EvidenceDocument,
    metadata: JsonObject | None,
) -> tuple[str, JsonObject, str, float]:
    document_payload = document_metadata(doc, metadata)
    source = str(
        first_value(document_payload, ["search_source", "search_method", "search_type"], "unknown")
    )
    score = coerce_float(
        first_value(
            document_payload,
            ["final_score", "relevance_score", "constraint_score", "score"],
            0.0,
        )
    )
    return document_content(doc), document_payload, source, score


def extract_evidence_units(
    doc: EvidenceDocument,
    metadata: JsonObject | None = None,
) -> list[JsonObject]:
    content, document_payload, source, score = _extraction_context(doc, metadata)
    units = _explicit_units(document_payload, source, score)
    graph_evidence = document_payload.get("graph_evidence")
    if isinstance(graph_evidence, dict):
        for payload in _graph_payloads(graph_evidence):
            units.extend(
                _graph_relationship_units(
                    metadata=document_payload,
                    graph_evidence=payload,
                    source=source,
                    score=score,
                )
            )
    if not units:
        fallback = _fallback_unit(
            content=content,
            metadata=document_payload,
            source=source,
            score=score,
        )
        if fallback is not None:
            units.append(fallback)
    return _dedupe_units(units)


__all__ = ["extract_evidence_units"]
