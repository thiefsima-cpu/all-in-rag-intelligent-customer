"""Versioned domain packs for GraphRAG product semantics."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast

from ..kernel.json_types import JsonObject
from .contracts import (
    CitationProjection,
    DomainDocumentMapper,
    DomainExtraction,
    DomainOntology,
    DomainPack,
    ExtractedEntity,
    ExtractedRelation,
    GraphNodeType,
    GraphRelationType,
)
from .customer_service import CUSTOMER_SERVICE_DOMAIN_PACK
from .recipe import RECIPE_DOMAIN_PACK

_DOMAIN_PACKS = {
    CUSTOMER_SERVICE_DOMAIN_PACK.name: CUSTOMER_SERVICE_DOMAIN_PACK,
    RECIPE_DOMAIN_PACK.name: RECIPE_DOMAIN_PACK,
}


def register_domain_pack(pack: DomainPack, *, replace: bool = False) -> None:
    """Register a validated domain pack without coupling policy selection to domain names."""
    normalized = str(pack.name or "").strip().casefold().replace("-", "_")
    if not normalized or not normalized.isidentifier() or normalized != pack.name:
        raise ValueError(f"Invalid domain pack name: {pack.name!r}")
    existing = _DOMAIN_PACKS.get(normalized)
    if existing is not None and existing is not pack and not replace:
        raise ValueError(f"Domain pack is already registered: {pack.name!r}")
    _DOMAIN_PACKS[normalized] = pack


def get_domain_pack(name: str) -> DomainPack:
    normalized = str(name or "").strip().casefold().replace("-", "_")
    normalized = {"customer_support": "customer_service"}.get(normalized, normalized)
    try:
        return _DOMAIN_PACKS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown domain pack: {name!r}") from exc


def domain_pack_names() -> tuple[str, ...]:
    return tuple(sorted(_DOMAIN_PACKS))


def load_domain_evaluation(pack: DomainPack) -> JsonObject:
    resource = files(f"rag_modules.domains.{pack.name}").joinpath(pack.evaluation_resource)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Domain evaluation resource must contain an object.")
    if payload.get("domain") != pack.name:
        raise ValueError("Domain evaluation resource does not match its domain pack.")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Domain evaluation resource must contain cases.")
    grounded = [
        case
        for case in cases
        if isinstance(case, dict) and case.get("expected_response_mode") == "grounded_answer"
    ]
    if not grounded:
        raise ValueError("Domain evaluation resource must contain grounded-answer cases.")
    return cast(JsonObject, payload)


__all__ = [
    "CitationProjection",
    "DomainDocumentMapper",
    "DomainExtraction",
    "DomainOntology",
    "DomainPack",
    "ExtractedEntity",
    "ExtractedRelation",
    "GraphNodeType",
    "GraphRelationType",
    "domain_pack_names",
    "get_domain_pack",
    "load_domain_evaluation",
    "register_domain_pack",
]
