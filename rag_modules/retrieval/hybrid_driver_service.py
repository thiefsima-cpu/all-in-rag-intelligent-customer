"""Neo4j driver lifecycle for hybrid retrieval runtime."""

from __future__ import annotations

import logging

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)


class HybridDriverService:
    """Own driver acquisition and close semantics for hybrid retrieval."""

    def __init__(self, *, storage, neo4j_manager=None) -> None:
        self.storage = storage
        self.neo4j_manager = neo4j_manager

    def ensure_driver(self, state):
        if state.driver is not None:
            return state.driver
        if self.neo4j_manager is not None:
            state.driver = self.neo4j_manager.driver
            state.owns_driver = False
            return state.driver
        state.driver = GraphDatabase.driver(
            self.storage.neo4j_uri,
            auth=(self.storage.neo4j_user, self.storage.neo4j_password),
        )
        state.owns_driver = True
        return state.driver

    @staticmethod
    def close(state) -> None:
        if state.owns_driver and state.driver:
            state.driver.close()
            logger.info("Neo4j connection closed.")


__all__ = ["HybridDriverService"]
