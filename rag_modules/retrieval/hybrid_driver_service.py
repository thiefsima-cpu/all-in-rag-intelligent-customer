"""Neo4j driver lifecycle for hybrid retrieval runtime."""

from __future__ import annotations

import logging

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
        raise RuntimeError("Hybrid retrieval requires an injected Neo4j manager.")

    @staticmethod
    def close(state) -> None:
        if state.owns_driver and state.driver:
            state.driver.close()
            logger.info("Neo4j connection closed.")


__all__ = ["HybridDriverService"]
