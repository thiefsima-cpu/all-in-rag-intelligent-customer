"""Evidence unit extraction."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..contracts import EvidenceDocument
from .helpers import (
    document_content,
    document_metadata,
    first_value,
    infer_evidence_type,
    stable_hash,
)
from .models import EvidenceUnit, PageDocumentLike


def _node_label_names(nodes: List[Dict[str, Any]]) -> Dict[str, str]:
    labels_by_id: Dict[str, str] = {}
    for node in nodes or []:
        node_id = str(node.get("id") or node.get("nodeId") or "")
        name = str(node.get("name") or node.get("title") or node_id or "")
        if node_id and name:
            labels_by_id[node_id] = name
    return labels_by_id


def _explicit_units(metadata: Dict[str, Any], source: str, score: float) -> List[EvidenceUnit]:
    units: List[EvidenceUnit] = []
    for item in metadata.get("evidence_units") or []:
        if isinstance(item, EvidenceUnit):
            units.append(item)
        elif isinstance(item, dict) and item.get("claim"):
            claim = str(item.get("claim") or "")
            units.append(
                EvidenceUnit(
                    unit_id=str(item.get("unit_id") or f"unit::{stable_hash(claim)}"),
                    evidence_type=str(item.get("evidence_type") or "text"),
                    claim=claim,
                    source=str(item.get("source") or source),
                    score=float(item.get("score") or score),
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
                            "recipe"
                            if metadata.get("recipe_id") or metadata.get("recipe_name")
                            else ""
                        )
                    ),
                    relation_type=str(item.get("relation_type") or ""),
                    entities=[str(value) for value in item.get("entities") or [] if value],
                    is_graph_evidence=bool(item.get("is_graph_evidence")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
    return units


def _graph_payloads(graph_evidence: Dict[str, Any]) -> List[Dict[str, Any]]:
    if graph_evidence.get("primary") or graph_evidence.get("merged"):
        payloads = [graph_evidence.get("primary") or {}]
        payloads.extend(
            item for item in graph_evidence.get("merged") or [] if isinstance(item, dict)
        )
        return payloads
    return [graph_evidence]


def _relationship_claim(
    relationship: Any,
    labels_by_id: Dict[str, str],
) -> tuple[str, str, List[str]] | None:
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


def _graph_entity_values(metadata: Dict[str, Any]) -> tuple[str, str, List[str]]:
    recipe_ids = metadata.get("recipe_node_ids") or []
    recipe_names = metadata.get("recipe_names") or []
    entity_id = (
        str(recipe_ids[0])
        if recipe_ids
        else str(
            metadata.get("entity_id") or metadata.get("recipe_id") or metadata.get("node_id") or ""
        )
    )
    entity_name = (
        str(recipe_names[0])
        if recipe_names
        else str(metadata.get("entity_name") or metadata.get("recipe_name") or "")
    )
    entity_names = [str(item) for item in metadata.get("entity_names") or recipe_names]
    return entity_id, entity_name, entity_names


def _graph_summary_unit(
    *,
    metadata: Dict[str, Any],
    graph_evidence: Dict[str, Any],
    source: str,
    score: float,
    entity_id: str,
    entity_name: str,
    entity_names: List[str],
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
        domain=str(
            metadata.get("domain")
            or ("recipe" if metadata.get("recipe_id") or metadata.get("recipe_name") else "")
        ),
        entities=list(dict.fromkeys(entity_names + list(metadata.get("matched_terms") or []))),
        is_graph_evidence=True,
        metadata={"search_type": metadata.get("search_type")},
    )


def _graph_relationship_unit(
    *,
    metadata: Dict[str, Any],
    source: str,
    score: float,
    entity_id: str,
    entity_name: str,
    relationship_claim: tuple[str, str, List[str]],
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
        domain=str(
            metadata.get("domain")
            or ("recipe" if metadata.get("recipe_id") or metadata.get("recipe_name") else "")
        ),
        relation_type=relation_type,
        entities=list(dict.fromkeys(entities)),
        is_graph_evidence=True,
        metadata={"search_type": metadata.get("search_type")},
    )


def _graph_relationship_units(
    *,
    metadata: Dict[str, Any],
    graph_evidence: Dict[str, Any],
    source: str,
    score: float,
) -> List[EvidenceUnit]:
    nodes = graph_evidence.get("nodes") or graph_evidence.get("connected_nodes") or []
    relationships = graph_evidence.get("relationships") or []
    labels_by_id = _node_label_names(nodes)
    entity_id, entity_name, entity_names = _graph_entity_values(metadata)
    units: List[EvidenceUnit] = []
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
    metadata: Dict[str, Any],
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
        domain=str(
            metadata.get("domain")
            or ("recipe" if metadata.get("recipe_id") or metadata.get("recipe_name") else "")
        ),
        entities=[entity_name] if entity_name else [],
        is_graph_evidence=False,
        metadata={"search_type": metadata.get("search_type")},
    )


def _dedupe_units(units: List[EvidenceUnit]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for unit in units:
        key = unit.unit_id or unit.claim
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(unit.to_dict())
    return deduped[:30]


def extract_evidence_units(
    doc: PageDocumentLike | EvidenceDocument,
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    content = document_content(doc)
    metadata = document_metadata(doc, metadata)
    source = str(
        first_value(metadata, ["search_source", "search_method", "search_type"], "unknown")
    )
    score = float(
        first_value(
            metadata,
            ["final_score", "relevance_score", "constraint_score", "score"],
            0.0,
        )
        or 0.0
    )

    units = _explicit_units(metadata, source, score)
    graph_evidence = metadata.get("graph_evidence") or {}
    if isinstance(graph_evidence, dict):
        for payload in _graph_payloads(graph_evidence):
            units.extend(
                _graph_relationship_units(
                    metadata=metadata,
                    graph_evidence=payload,
                    source=source,
                    score=score,
                )
            )
    if not units:
        fallback = _fallback_unit(content=content, metadata=metadata, source=source, score=score)
        if fallback is not None:
            units.append(fallback)
    return _dedupe_units(units)


__all__ = ["extract_evidence_units"]
