from unittest.mock import patch

import pytest

from rag_modules.contracts import QuerySemanticProfile, QuerySemanticRuntimeSettings
from rag_modules.retrieval.keyword_service import QueryKeywordExtractor
from tests.configuration_test_helpers import build_test_config


def _extractor() -> QueryKeywordExtractor:
    return QueryKeywordExtractor(QuerySemanticRuntimeSettings.from_config(build_test_config()))


def test_extract_combines_entities_constraints_relations_and_deduplicates() -> None:
    profile = QuerySemanticProfile(
        source_entities=[" tofu ", "tofu"],
        target_entities=["soup"],
        entity_keywords=["tofu", "ginger"],
        topic_keywords=["quick", "quick"],
        recommendation_hits=["healthy"],
        relation_types=["USES"],
        constraints={
            "preference_terms": ["light"],
            "health_terms": ["low-sodium"],
            "cuisine_terms": ["Sichuan"],
            "category_terms": ["soup"],
            "include_terms": ["ginger"],
        },
    )
    with (
        patch(
            "rag_modules.retrieval.keyword_service.infer_query_semantic_profile",
            return_value=profile,
        ),
        patch(
            "rag_modules.retrieval.keyword_service.relation_index_terms",
            return_value=["ingredient", "quick"],
        ),
    ):
        entities, topics = _extractor().extract("query")

    assert entities == ["tofu", "soup", "ginger"]
    assert topics == [
        "quick",
        "healthy",
        "light",
        "low-sodium",
        "Sichuan",
        "soup",
        "ginger",
        "ingredient",
    ]


def test_extract_empty_profile_returns_empty_terms() -> None:
    with patch(
        "rag_modules.retrieval.keyword_service.infer_query_semantic_profile",
        return_value=QuerySemanticProfile(),
    ):
        assert _extractor().extract("") == ([], [])


def test_extract_caps_each_output_at_eight_terms() -> None:
    profile = QuerySemanticProfile(
        entity_keywords=[f"entity-{index}" for index in range(10)],
        topic_keywords=[f"topic-{index}" for index in range(10)],
    )
    with patch(
        "rag_modules.retrieval.keyword_service.infer_query_semantic_profile",
        return_value=profile,
    ):
        entities, topics = _extractor().extract("many terms")

    assert entities == [f"entity-{index}" for index in range(8)]
    assert topics == [f"topic-{index}" for index in range(8)]


def test_dedupe_terms_removes_blank_and_duplicate_values() -> None:
    assert QueryKeywordExtractor.dedupe_terms([" tofu ", "", "tofu", "soup"]) == [
        "tofu",
        "soup",
    ]


def test_extract_propagates_semantic_profile_failures() -> None:
    with (
        patch(
            "rag_modules.retrieval.keyword_service.infer_query_semantic_profile",
            side_effect=RuntimeError("semantic dependency failed"),
        ),
        pytest.raises(RuntimeError, match="semantic dependency failed"),
    ):
        _extractor().extract("query")


def test_extract_propagates_relation_registry_failures() -> None:
    profile = QuerySemanticProfile(relation_types=["USES"])
    with (
        patch(
            "rag_modules.retrieval.keyword_service.infer_query_semantic_profile",
            return_value=profile,
        ),
        patch(
            "rag_modules.retrieval.keyword_service.relation_index_terms",
            side_effect=RuntimeError("registry failed"),
        ),
        pytest.raises(RuntimeError, match="registry failed"),
    ):
        _extractor().extract("query")
