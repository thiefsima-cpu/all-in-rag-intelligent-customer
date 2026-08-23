"""
Generic query constraint extraction helpers.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..kernel.json_types import JsonObject, as_string_list, coerce_json_object


def loads_json_object(text: str) -> JsonObject:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value: object = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, Mapping):
        raise ValueError("JSON payload must be an object")
    return {str(key): item for key, item in value.items()}


@dataclass
class QueryConstraints:
    """Domain-neutral filters carried through query planning and retrieval."""

    entity_terms: list[str] = field(default_factory=list)
    excluded_entity_terms: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    temporal_filters: JsonObject = field(default_factory=dict)
    structured_filters: JsonObject = field(default_factory=dict)
    extension: JsonObject = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "QueryConstraints":
        payload = data or {}
        temporal_data = payload.get("temporal_filters")
        temporal_payload = temporal_data if isinstance(temporal_data, Mapping) else {}
        structured_data = payload.get("structured_filters")
        structured_payload = structured_data if isinstance(structured_data, Mapping) else {}
        extension_data = payload.get("extension")
        extension_payload = extension_data if isinstance(extension_data, Mapping) else {}
        return cls(
            entity_terms=as_string_list(payload.get("entity_terms")),
            excluded_entity_terms=as_string_list(payload.get("excluded_entity_terms")),
            relation_types=as_string_list(payload.get("relation_types")),
            temporal_filters=coerce_json_object(temporal_payload),
            structured_filters=coerce_json_object(structured_payload),
            extension=coerce_json_object(extension_payload),
        )

    def has_constraints(self) -> bool:
        return any(
            [
                self.entity_terms,
                self.excluded_entity_terms,
                self.relation_types,
                self.temporal_filters,
                self.structured_filters,
                self.extension,
            ]
        )

    def field_value(self, field_name: str) -> object:
        """Resolve a policy-owned meaningful-field selector without fixed domain attributes."""

        if field_name.startswith("extension."):
            return self.extension.get(field_name.removeprefix("extension."))
        if field_name.startswith("temporal_filters."):
            return self.temporal_filters.get(field_name.removeprefix("temporal_filters."))
        if field_name.startswith("structured_filters."):
            return self.structured_filters.get(field_name.removeprefix("structured_filters."))
        return {
            "entity_terms": self.entity_terms,
            "excluded_entity_terms": self.excluded_entity_terms,
            "relation_types": self.relation_types,
            "temporal_filters": self.temporal_filters,
            "structured_filters": self.structured_filters,
            "extension": self.extension,
        }.get(field_name)

    def to_dict(self) -> JsonObject:
        return coerce_json_object(
            {
                "entity_terms": self.entity_terms,
                "excluded_entity_terms": self.excluded_entity_terms,
                "relation_types": self.relation_types,
                "temporal_filters": self.temporal_filters,
                "structured_filters": self.structured_filters,
                "extension": self.extension,
            }
        )


__all__ = ["QueryConstraints", "loads_json_object"]
