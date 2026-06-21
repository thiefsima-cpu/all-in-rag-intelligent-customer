"""
Unified Neo4j connection manager.

All modules that need Neo4j share a single driver instance created here,
instead of each module opening its own connection.
"""

import logging
from typing import Optional

from neo4j import Driver, GraphDatabase

logger = logging.getLogger(__name__)


class Neo4jConnectionManager:
    """Manages a single Neo4j driver instance shared across all modules."""

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        *,
        max_connection_pool_size: int = 50,
        connection_acquisition_timeout_seconds: float = 30.0,
        max_connection_lifetime_seconds: float = 3600.0,
        connection_timeout_seconds: float = 15.0,
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.max_connection_pool_size = max(1, int(max_connection_pool_size))
        self.connection_acquisition_timeout_seconds = max(
            0.1,
            float(connection_acquisition_timeout_seconds),
        )
        self.max_connection_lifetime_seconds = max(
            0.1,
            float(max_connection_lifetime_seconds),
        )
        self.connection_timeout_seconds = max(
            0.1,
            float(connection_timeout_seconds),
        )
        self._driver: Optional[Driver] = None

    @property
    def driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                self.uri,
                auth=(self.user, self.password),
                max_connection_pool_size=self.max_connection_pool_size,
                connection_acquisition_timeout=self.connection_acquisition_timeout_seconds,
                max_connection_lifetime=self.max_connection_lifetime_seconds,
                connection_timeout=self.connection_timeout_seconds,
            )
            # Verify connectivity on first access
            with self._driver.session(database=self.database) as session:
                session.run("RETURN 1")
            logger.info("Neo4j connection established: %s (db=%s)", self.uri, self.database)
        return self._driver

    def session(self, **kwargs):
        """Convenience shortcut for ``self.driver.session(database=..., **kwargs)``."""
        kwargs.setdefault("database", self.database)
        return self.driver.session(**kwargs)

    def close(self):
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
