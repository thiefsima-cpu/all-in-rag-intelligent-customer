"""Ports consumed by Neo4j infrastructure adapters."""

from __future__ import annotations

from typing import Any, Protocol


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior returned by the provider driver."""

    def __enter__(self) -> "Neo4jSessionPort": ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(self, query: str, parameters: object | None = None, **kwargs: object) -> Any: ...

    def execute_read(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...

    def execute_write(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior created by the provider factory."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...

    def close(self) -> None: ...


__all__ = ["Neo4jDriverPort", "Neo4jSessionPort"]
