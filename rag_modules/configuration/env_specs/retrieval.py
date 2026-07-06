"""Retrieval environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

RETRIEVAL_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec("TOP_K", ("retrieval", "top_k"), "int"),
    _spec("VECTOR_SEARCH_EF", ("retrieval", "vector_search_ef"), "int"),
    _spec("VECTOR_SEARCH_MAX_K", ("retrieval", "vector_search_max_k"), "int"),
    _spec("RRF_K", ("retrieval", "rrf_k"), "int"),
    _spec(
        "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_default_candidate_multiplier"),
        "int",
    ),
    _spec(
        "HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_default_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",
        ("retrieval", "hybrid_constraint_candidate_multiplier"),
        "int",
    ),
    _spec(
        "HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "hybrid_constraint_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "ROUTER_COMBINED_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_combined_candidate_multiplier"),
        "int",
    ),
    _spec(
        "ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_combined_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
        ("retrieval", "router_graph_supplement_candidate_multiplier"),
        "int",
    ),
    _spec(
        "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
        ("retrieval", "router_graph_supplement_candidate_min_candidates"),
        "int",
    ),
    _spec(
        "RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",
        ("retrieval", "retrieval_preserve_graph_evidence"),
        "bool",
    ),
    _spec(
        "ENABLE_PARENT_DOC_RETRIEVAL",
        ("retrieval", "enable_parent_doc_retrieval"),
        "bool",
    ),
    _spec("PARENT_DOC_TOP_N", ("retrieval", "parent_doc_top_n"), "int"),
    _spec("PARENT_DOC_MAX_CHARS", ("retrieval", "parent_doc_max_chars"), "int"),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",
        ("retrieval", "candidate_source_failure_threshold"),
        "int",
    ),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",
        ("retrieval", "candidate_source_recovery_seconds"),
        "float",
    ),
    _spec(
        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",
        ("retrieval", "candidate_source_degradation_strategy"),
        "str",
    ),
)


__all__ = ["RETRIEVAL_ENV_FIELD_SPECS"]
