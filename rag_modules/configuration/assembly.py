"""Configuration assembly helpers."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Mapping

from .models import (
    SECTION_ORDER,
    ApiSettings,
    GenerationSettings,
    GraphRAGConfig,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    QueryUnderstandingSettings,
    RetrievalSettings,
    StorageSettings,
)


def _merge_nested_mapping(
    target: Dict[str, Any],
    updates: Mapping[str, Any],
    *,
    path: str,
    unknown_fields: List[str],
) -> None:
    for key, value in updates.items():
        key_text = str(key)
        dotted = f"{path}.{key_text}" if path else key_text

        if key_text not in target:
            unknown_fields.append(dotted)
            continue

        current = target[key_text]
        if isinstance(current, dict):
            if not isinstance(value, Mapping):
                raise TypeError(f"Config section {dotted!r} must be a mapping.")
            _merge_nested_mapping(
                current,
                value,
                path=dotted,
                unknown_fields=unknown_fields,
            )
            continue

        if isinstance(value, Mapping):
            raise TypeError(f"Config field {dotted!r} does not accept nested mappings.")
        target[key_text] = value


def apply_overrides(
    domain_payload: Dict[str, Dict[str, Any]],
    overrides: Mapping[str, Any],
) -> None:
    unknown_fields: List[str] = []
    previous_index_cache_dir = str(domain_payload["storage"].get("index_cache_dir", ""))
    previous_artifact_manifest_path = str(
        domain_payload["storage"].get("artifact_manifest_path", "")
    )
    artifact_manifest_overridden = False
    build_job_store_path_overridden = False

    for section_name in SECTION_ORDER:
        nested = overrides.get(section_name)
        if nested is None:
            continue
        if not isinstance(nested, Mapping):
            raise TypeError(f"Config section {section_name!r} must be a mapping.")
        _merge_nested_mapping(
            domain_payload[section_name],
            nested,
            path=section_name,
            unknown_fields=unknown_fields,
        )
        if section_name == "storage" and "artifact_manifest_path" in nested:
            artifact_manifest_overridden = True
        if section_name == "storage" and "build_job_store_path" in nested:
            build_job_store_path_overridden = True

    for key in overrides:
        if key in SECTION_ORDER:
            continue
        unknown_fields.append(str(key))

    if not artifact_manifest_overridden:
        previous_default_manifest_path = os.path.join(
            previous_index_cache_dir,
            "artifact_manifest.json",
        )
        if previous_artifact_manifest_path == previous_default_manifest_path:
            domain_payload["storage"]["artifact_manifest_path"] = os.path.join(
                str(domain_payload["storage"].get("index_cache_dir", previous_index_cache_dir)),
                "artifact_manifest.json",
            )
    if not build_job_store_path_overridden:
        domain_payload["storage"]["build_job_store_path"] = os.path.join(
            os.path.dirname(str(domain_payload["storage"].get("artifact_manifest_path", ""))),
            "build_jobs.json",
        )

    if unknown_fields:
        unknown_fields.sort()
        raise KeyError(f"Unknown configuration fields: {', '.join(unknown_fields)}")


def build_config_from_domain_dict(
    domain_payload: Mapping[str, Mapping[str, Any]],
) -> GraphRAGConfig:
    return GraphRAGConfig(
        storage=StorageSettings(**dict(domain_payload["storage"])),
        models=ModelSettings(**dict(domain_payload["models"])),
        retrieval=RetrievalSettings(**dict(domain_payload["retrieval"])),
        query_understanding=QueryUnderstandingSettings.from_dict(
            domain_payload["query_understanding"]
        ),
        generation=GenerationSettings(**dict(domain_payload["generation"])),
        graph=GraphSettings(**dict(domain_payload["graph"])),
        observability=ObservabilitySettings(**dict(domain_payload["observability"])),
        api=ApiSettings(**dict(domain_payload["api"])),
    )


__all__ = ["apply_overrides", "build_config_from_domain_dict"]
