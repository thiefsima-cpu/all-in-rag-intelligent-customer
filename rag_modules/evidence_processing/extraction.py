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
    recipe_ids = metadata.get("recipe_node_ids") or []
    recipe_names = metadata.get("recipe_names") or []
    recipe_id = (
        str(recipe_ids[0])
        if recipe_ids
        else str(metadata.get("recipe_id") or metadata.get("node_id") or "")
    )
    recipe_name = str(recipe_names[0]) if recipe_names else str(metadata.get("recipe_name") or "")

    units: List[EvidenceUnit] = []
    description = str(graph_evidence.get("description") or "").strip()
    if description:
        units.append(
            EvidenceUnit(
                unit_id=f"unit::{stable_hash(description)}",
                evidence_type="graph_summary",
                claim=description,
                source=source,
                score=score,
                recipe_id=recipe_id,
                recipe_name=recipe_name,
                entities=list(
                    dict.fromkeys(recipe_names + list(metadata.get("matched_terms") or []))
                ),
                is_graph_evidence=True,
                metadata={"search_type": metadata.get("search_type")},
            )
        )

    for rel in relationships[:20]:
        if isinstance(rel, str):
            claim = rel
            rel_type = ""
            entities: List[str] = []
        elif isinstance(rel, dict):
            rel_type = str(rel.get("type") or rel.get("relation_type") or "RELATED")
            start_id = str(rel.get("startNodeId") or rel.get("source_id") or "")
            end_id = str(rel.get("endNodeId") or rel.get("target_id") or "")
            start = str(rel.get("source_name") or labels_by_id.get(start_id) or start_id or "")
            end = str(rel.get("target_name") or labels_by_id.get(end_id) or end_id or "")
            if start and end:
                claim = f"{start} -[{rel_type}]-> {end}"
                entities = [start, end]
            else:
                claim = rel_type
                entities = [item for item in (start, end) if item]
        else:
            continue
        if not claim:
            continue
        units.append(
            EvidenceUnit(
                unit_id=f"unit::{stable_hash(claim)}",
                evidence_type="graph_relation",
                claim=claim,
                source=source,
                score=score,
                recipe_id=recipe_id,
                recipe_name=recipe_name,
                relation_type=rel_type,
                entities=list(dict.fromkeys(entities)),
                is_graph_evidence=True,
                metadata={"search_type": metadata.get("search_type")},
            )
        )
    return units


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

    units: List[EvidenceUnit] = []
    for item in metadata.get("evidence_units") or []:
        if isinstance(item, EvidenceUnit):
            units.append(item)
        elif isinstance(item, dict) and item.get("claim"):
            units.append(
                EvidenceUnit(
                    unit_id=str(
                        item.get("unit_id") or f"unit::{stable_hash(str(item.get('claim')))}"
                    ),
                    evidence_type=str(item.get("evidence_type") or "text"),
                    claim=str(item.get("claim") or ""),
                    source=str(item.get("source") or source),
                    score=float(item.get("score") or score),
                    recipe_id=str(item.get("recipe_id") or metadata.get("recipe_id") or ""),
                    recipe_name=str(item.get("recipe_name") or metadata.get("recipe_name") or ""),
                    relation_type=str(item.get("relation_type") or ""),
                    entities=[str(value) for value in item.get("entities") or [] if value],
                    is_graph_evidence=bool(item.get("is_graph_evidence")),
                    metadata=dict(item.get("metadata") or {}),
                )
            )

    graph_evidence = metadata.get("graph_evidence") or {}
    if isinstance(graph_evidence, dict):
        if graph_evidence.get("primary") or graph_evidence.get("merged"):
            primary = graph_evidence.get("primary") or {}
            units.extend(
                _graph_relationship_units(
                    metadata=metadata,
                    graph_evidence=primary,
                    source=source,
                    score=score,
                )
            )
            for merged in graph_evidence.get("merged") or []:
                if isinstance(merged, dict):
                    units.extend(
                        _graph_relationship_units(
                            metadata=metadata,
                            graph_evidence=merged,
                            source=source,
                            score=score,
                        )
                    )
        else:
            units.extend(
                _graph_relationship_units(
                    metadata=metadata,
                    graph_evidence=graph_evidence,
                    source=source,
                    score=score,
                )
            )

    if not units:
        recipe_name = str(metadata.get("recipe_name") or "")
        claim = content.strip()[:260]
        if claim:
            units.append(
                EvidenceUnit(
                    unit_id=f"unit::{stable_hash(claim)}",
                    evidence_type=infer_evidence_type(metadata),
                    claim=claim,
                    source=source,
                    score=score,
                    recipe_id=str(metadata.get("recipe_id") or metadata.get("node_id") or ""),
                    recipe_name=recipe_name,
                    entities=[recipe_name] if recipe_name else [],
                    is_graph_evidence=False,
                    metadata={"search_type": metadata.get("search_type")},
                )
            )

    seen = set()
    deduped: List[Dict[str, Any]] = []
    for unit in units:
        key = unit.unit_id or unit.claim
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(unit.to_dict())
    return deduped[:30]


__all__ = ["extract_evidence_units"]
