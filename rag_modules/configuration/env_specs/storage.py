"""Storage environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

STORAGE_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec("INDEX_CACHE_DIR", ("storage", "index_cache_dir"), "str"),
    _spec("ARTIFACT_MANIFEST_PATH", ("storage", "artifact_manifest_path"), "str"),
    _spec("NEO4J_URI", ("storage", "neo4j_uri"), "str"),
    _spec("NEO4J_USER", ("storage", "neo4j_user"), "str"),
    _spec("NEO4J_PASSWORD", ("storage", "neo4j_password"), "str"),
    _spec("NEO4J_DATABASE", ("storage", "neo4j_database"), "str"),
    _spec("MILVUS_HOST", ("storage", "milvus_host"), "str"),
    _spec("MILVUS_PORT", ("storage", "milvus_port"), "int"),
    _spec("MILVUS_COLLECTION_NAME", ("storage", "milvus_collection_name"), "str"),
    _spec("MILVUS_DIMENSION", ("storage", "milvus_dimension"), "int"),
    _spec("ENABLE_INDEX_CACHE", ("storage", "enable_index_cache"), "bool"),
    _spec("MILVUS_BLUE_GREEN_ENABLED", ("storage", "milvus_blue_green_enabled"), "bool"),
    _spec("MILVUS_COLLECTION_ALIAS_SUFFIX", ("storage", "milvus_collection_alias_suffix"), "str"),
    _spec("BUILD_JOB_STORE_PATH", ("storage", "build_job_store_path"), "str"),
    _spec(
        "NEO4J_MAX_CONNECTION_POOL_SIZE",
        ("storage", "neo4j_max_connection_pool_size"),
        "int",
    ),
    _spec(
        "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",
        ("storage", "neo4j_connection_acquisition_timeout_seconds"),
        "float",
    ),
    _spec(
        "NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",
        ("storage", "neo4j_max_connection_lifetime_seconds"),
        "float",
    ),
    _spec(
        "NEO4J_CONNECTION_TIMEOUT_SECONDS",
        ("storage", "neo4j_connection_timeout_seconds"),
        "float",
    ),
)


__all__ = ["STORAGE_ENV_FIELD_SPECS"]
