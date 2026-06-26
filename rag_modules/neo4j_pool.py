"""Compatibility export for the canonical Neo4j infrastructure manager."""

from __future__ import annotations

from .infra.neo4j import Neo4jConnectionManager

__all__ = ["Neo4jConnectionManager"]
