"""Storage configuration section model."""

from __future__ import annotations

from pydantic import Field

from .base import ConfigSection


class StorageSettings(ConfigSection):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="password", repr=False)
    neo4j_database: str = "neo4j"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "cooking_knowledge"
    milvus_dimension: int = Field(default=1024, ge=0)
    enable_index_cache: bool = True
    index_cache_dir: str = "storage/indexes"
    artifact_manifest_path: str = ""
    milvus_blue_green_enabled: bool = True
    milvus_collection_alias_suffix: str = "__active"
    build_job_store_path: str = ""
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_acquisition_timeout_seconds: float = 30.0
    neo4j_max_connection_lifetime_seconds: float = 3600.0
    neo4j_connection_timeout_seconds: float = 15.0


__all__ = ["StorageSettings"]
