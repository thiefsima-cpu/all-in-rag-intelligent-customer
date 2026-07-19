"""Ontology-driven graph loading for non-recipe domain packs."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping

from ...contracts.graph_preparation import GraphNode
from ...domains.contracts import DomainDocumentMapper, DomainOntology
from ...kernel.documents import TextDocument
from ...kernel.json_types import coerce_json_object
from ...safe_logging import log_failure
from ..ports import Neo4jDriverPort
from .loader import LoadedGraphData, Neo4jSessionLike, _string_list

logger = logging.getLogger(__name__)

DOMAIN_ENTITIES_QUERY = """
MATCH (n)
WHERE any(label IN labels(n) WHERE label IN $labels)
  AND n.domain = $domain_name
  AND coalesce(n.createdFrom, '') <> 'semantic_schema'
RETURN labels(n) AS labels,
       properties(n) AS properties
ORDER BY elementId(n)
"""


class DomainGraphDataLoader:
    """Load all primary entities declared by a domain ontology."""

    def __init__(self, ontology: DomainOntology, *, domain_name: str) -> None:
        self.ontology = ontology
        self.domain_name = str(domain_name)

    def load(self, driver: Neo4jDriverPort, *, database: str) -> LoadedGraphData:
        with driver.session(database=database) as session:
            entities = self._load_entities(session)
        logger.info("Loaded %d domain entities.", len(entities))
        return LoadedGraphData(recipes=entities, ingredients=[], cooking_steps=[])

    def _load_entities(self, session: Neo4jSessionLike) -> list[GraphNode]:
        entities: list[GraphNode] = []
        for record in session.run(
            DOMAIN_ENTITIES_QUERY,
            {
                "labels": list(self.ontology.primary_labels),
                "domain_name": self.domain_name,
            },
        ):
            labels = tuple(_string_list(record.get("labels")))
            properties = coerce_json_object(record.get("properties"))
            node_type = self.ontology.node_type_for_labels(labels)
            if node_type is None:
                continue
            node_id = _first_property(properties, node_type.id_fields)
            name = _first_property(properties, node_type.name_fields) or node_id
            if not node_id:
                continue
            entities.append(
                GraphNode(
                    node_id=node_id,
                    labels=list(labels),
                    name=name,
                    properties=properties,
                )
            )
        return entities


def _first_property(properties: Mapping[str, object], field_names: tuple[str, ...]) -> str:
    for field_name in field_names:
        value = properties.get(field_name)
        if value not in (None, ""):
            return str(value)
    return ""


class DomainDocumentBuilder:
    """Materialize retrieval documents through the selected domain mapper."""

    def __init__(self, mapper: DomainDocumentMapper) -> None:
        self.mapper = mapper

    def build(
        self,
        *,
        driver: Neo4jDriverPort,
        database: str,
        recipes: Iterable[GraphNode],
    ) -> list[TextDocument]:
        del driver, database
        documents: list[TextDocument] = []
        for entity in recipes:
            payload = {
                **dict(entity.properties or {}),
                "entity_id": entity.node_id,
                "entity_name": entity.name,
                "entity_type": entity.labels[0] if entity.labels else "Entity",
                "node_id": entity.node_id,
                "name": entity.name,
            }
            try:
                documents.append(self.mapper.map_document(payload))
            except Exception as exc:
                log_failure(
                    logger,
                    logging.WARNING,
                    "domain_document_mapping_failed",
                    code="DOMAIN_DOCUMENT_MAPPING_FAILED",
                    error=exc,
                )
        return documents


__all__ = ["DOMAIN_ENTITIES_QUERY", "DomainDocumentBuilder", "DomainGraphDataLoader"]
