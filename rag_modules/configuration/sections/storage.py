"""Storage configuration section loader."""

from __future__ import annotations

import os
from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import StorageSettings
from .common import mapping_defaults


def load_storage_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> StorageSettings:
    storage_defaults = mapping_defaults(defaults)
    default_index_cache_dir = str(storage_defaults.get("index_cache_dir", "storage/indexes"))
    index_cache_dir = source.get_str(
        "INDEX_CACHE_DIR",
        default_index_cache_dir,
    )
    default_artifact_manifest_path = str(
        storage_defaults.get(
            "artifact_manifest_path",
            os.path.join(default_index_cache_dir, "artifact_manifest.json"),
        )
    )
    if default_artifact_manifest_path == os.path.join(
        default_index_cache_dir,
        "artifact_manifest.json",
    ):
        default_artifact_manifest_path = os.path.join(index_cache_dir, "artifact_manifest.json")
    artifact_manifest_path = source.get_str(
        "ARTIFACT_MANIFEST_PATH",
        default_artifact_manifest_path,
    )
    default_build_job_store_path = str(
        storage_defaults.get(
            "build_job_store_path",
            os.path.join(os.path.dirname(default_artifact_manifest_path), "build_jobs.json"),
        )
    )
    if default_build_job_store_path == os.path.join(
        os.path.dirname(default_artifact_manifest_path),
        "build_jobs.json",
    ):
        default_build_job_store_path = os.path.join(
            os.path.dirname(artifact_manifest_path),
            "build_jobs.json",
        )
    return StorageSettings(
        neo4j_uri=source.get_str(
            "NEO4J_URI", str(storage_defaults.get("neo4j_uri", "bolt://localhost:7687"))
        ),
        neo4j_user=source.get_str("NEO4J_USER", str(storage_defaults.get("neo4j_user", "neo4j"))),
        neo4j_password=source.get_str(
            "NEO4J_PASSWORD", str(storage_defaults.get("neo4j_password", "password"))
        ),
        neo4j_database=source.get_str(
            "NEO4J_DATABASE", str(storage_defaults.get("neo4j_database", "neo4j"))
        ),
        milvus_host=source.get_str(
            "MILVUS_HOST", str(storage_defaults.get("milvus_host", "localhost"))
        ),
        milvus_port=source.get_int("MILVUS_PORT", int(storage_defaults.get("milvus_port", 19530))),
        milvus_collection_name=source.get_str(
            "MILVUS_COLLECTION_NAME",
            str(storage_defaults.get("milvus_collection_name", "cooking_knowledge")),
        ),
        milvus_dimension=source.get_int(
            "MILVUS_DIMENSION", int(storage_defaults.get("milvus_dimension", 1024))
        ),
        enable_index_cache=source.get_bool(
            "ENABLE_INDEX_CACHE",
            bool(storage_defaults.get("enable_index_cache", True)),
        ),
        index_cache_dir=index_cache_dir,
        artifact_manifest_path=artifact_manifest_path,
        milvus_blue_green_enabled=source.get_bool(
            "MILVUS_BLUE_GREEN_ENABLED",
            bool(storage_defaults.get("milvus_blue_green_enabled", True)),
        ),
        milvus_collection_alias_suffix=source.get_str(
            "MILVUS_COLLECTION_ALIAS_SUFFIX",
            str(storage_defaults.get("milvus_collection_alias_suffix", "__active")),
        ),
        build_job_store_path=source.get_str(
            "BUILD_JOB_STORE_PATH",
            default_build_job_store_path,
        ),
        neo4j_max_connection_pool_size=max(
            1,
            source.get_int(
                "NEO4J_MAX_CONNECTION_POOL_SIZE",
                int(storage_defaults.get("neo4j_max_connection_pool_size", 50)),
            ),
        ),
        neo4j_connection_acquisition_timeout_seconds=source.get_float(
            "NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",
            float(
                storage_defaults.get(
                    "neo4j_connection_acquisition_timeout_seconds",
                    30.0,
                )
            ),
        ),
        neo4j_max_connection_lifetime_seconds=source.get_float(
            "NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",
            float(storage_defaults.get("neo4j_max_connection_lifetime_seconds", 3600.0)),
        ),
        neo4j_connection_timeout_seconds=source.get_float(
            "NEO4J_CONNECTION_TIMEOUT_SECONDS",
            float(storage_defaults.get("neo4j_connection_timeout_seconds", 15.0)),
        ),
    )


__all__ = ["load_storage_settings"]
