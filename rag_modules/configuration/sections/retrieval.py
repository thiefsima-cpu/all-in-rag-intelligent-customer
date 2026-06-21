"""Retrieval configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import RetrievalSettings
from .common import mapping_defaults


def load_retrieval_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> RetrievalSettings:
    retrieval_defaults = mapping_defaults(defaults)
    candidate_source_degradation_strategy = (
        source.get_str(
            "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",
            str(retrieval_defaults.get("candidate_source_degradation_strategy", "continue")),
        )
        .strip()
        .lower()
    )
    return RetrievalSettings(
        top_k=source.get_int("TOP_K", int(retrieval_defaults.get("top_k", 5))),
        vector_search_ef=source.get_int(
            "VECTOR_SEARCH_EF",
            int(retrieval_defaults.get("vector_search_ef", 128)),
        ),
        vector_search_max_k=source.get_int(
            "VECTOR_SEARCH_MAX_K",
            int(retrieval_defaults.get("vector_search_max_k", 50)),
        ),
        rrf_k=source.get_int("RRF_K", int(retrieval_defaults.get("rrf_k", 60))),
        hybrid_default_candidate_multiplier=source.get_int(
            "HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("hybrid_default_candidate_multiplier", 2)),
        ),
        hybrid_default_candidate_min_candidates=source.get_int(
            "HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("hybrid_default_candidate_min_candidates", 10)),
        ),
        hybrid_constraint_candidate_multiplier=source.get_int(
            "HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("hybrid_constraint_candidate_multiplier", 6)),
        ),
        hybrid_constraint_candidate_min_candidates=source.get_int(
            "HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("hybrid_constraint_candidate_min_candidates", 30)),
        ),
        router_combined_candidate_multiplier=source.get_int(
            "ROUTER_COMBINED_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("router_combined_candidate_multiplier", 6)),
        ),
        router_combined_candidate_min_candidates=source.get_int(
            "ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("router_combined_candidate_min_candidates", 30)),
        ),
        router_graph_supplement_candidate_multiplier=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",
            int(retrieval_defaults.get("router_graph_supplement_candidate_multiplier", 2)),
        ),
        router_graph_supplement_candidate_min_candidates=source.get_int(
            "ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",
            int(retrieval_defaults.get("router_graph_supplement_candidate_min_candidates", 10)),
        ),
        retrieval_preserve_graph_evidence=source.get_bool(
            "RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",
            bool(retrieval_defaults.get("retrieval_preserve_graph_evidence", True)),
        ),
        enable_parent_doc_retrieval=source.get_bool(
            "ENABLE_PARENT_DOC_RETRIEVAL",
            bool(retrieval_defaults.get("enable_parent_doc_retrieval", True)),
        ),
        parent_doc_top_n=source.get_int(
            "PARENT_DOC_TOP_N",
            int(retrieval_defaults.get("parent_doc_top_n", 3)),
        ),
        parent_doc_max_chars=source.get_int(
            "PARENT_DOC_MAX_CHARS",
            int(retrieval_defaults.get("parent_doc_max_chars", 4000)),
        ),
        candidate_source_failure_threshold=max(
            1,
            source.get_int(
                "RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",
                int(retrieval_defaults.get("candidate_source_failure_threshold", 1)),
            ),
        ),
        candidate_source_recovery_seconds=max(
            0.1,
            source.get_float(
                "RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",
                float(retrieval_defaults.get("candidate_source_recovery_seconds", 30.0)),
            ),
        ),
        candidate_source_degradation_strategy=(candidate_source_degradation_strategy or "continue"),
    )


__all__ = ["load_retrieval_settings"]
