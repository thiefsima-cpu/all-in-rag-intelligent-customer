"""Neo4j driver factory adapter."""

from __future__ import annotations

from typing import Any, cast

from neo4j import GraphDatabase

from ...runtime_contracts import Neo4jDriverPort


def create_neo4j_driver(
    uri: str,
    user: str,
    password: str,
    **driver_options: Any,
) -> Neo4jDriverPort:
    """Create a Neo4j driver with repository-standard authentication."""

    return cast(
        Neo4jDriverPort,
        GraphDatabase.driver(
            uri,
            auth=(user, password),
            **driver_options,
        ),
    )
