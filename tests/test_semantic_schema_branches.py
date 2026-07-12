from __future__ import annotations

from rag_modules.domain.shared import semantic_schema as schema


def test_tag_normalization_and_unique_helpers_handle_supported_shapes() -> None:
    assert schema._normalize_tags(None) == []
    assert schema._normalize_tags([" quick ", "", "vegan"]) == ["quick", "vegan"]
    assert schema._normalize_tags("quick, vegan") == ["quick", "vegan"]
    assert schema._unique(["tofu", "", "tofu", " pepper "]) == ["tofu", "pepper"]


def test_time_profile_inference_covers_summed_fallback_and_threshold_bands() -> None:
    assert schema._infer_total_minutes({"prepTime": 5, "cookTime": 5}) == 10
    assert schema._infer_total_minutes({"timeEstimate": "20 minutes"}) == 20
    assert schema._infer_total_minutes({}) is None

    bands = [
        schema._extract_time_profiles({"cookingTime": 10}, ""),
        schema._extract_time_profiles({"cookingTime": 20}, ""),
        schema._extract_time_profiles({"cookingTime": 45}, ""),
        schema._extract_time_profiles({"cookingTime": 90}, ""),
    ]
    assert all(band for band in bands)
    assert len({tuple(band) for band in bands}) == 4

    marker = schema._extract_time_profiles(
        {}, schema._extract_time_profiles({"cookingTime": 10}, "")[0]
    )
    assert marker


def test_difficulty_inference_covers_numeric_bands_and_text_fallback() -> None:
    easy = schema._extract_difficulty_levels({"difficulty": 1}, "")
    medium = schema._extract_difficulty_levels({"difficulty": 3}, "")
    hard = schema._extract_difficulty_levels({"difficulty": 5}, "")
    invalid = schema._extract_difficulty_levels({"difficulty": "unknown"}, "")

    assert easy and medium and hard
    assert easy != medium != hard
    assert invalid == []
    assert schema._extract_difficulty_levels({}, easy[0])


def test_recipe_semantics_builds_contribution_and_technique_relationships() -> None:
    contribution_effect, causes = next(iter(schema._CONTRIBUTION_HINTS.items()))
    technique_effect, techniques = next(iter(schema._TECHNIQUE_EFFECT_HINTS.items()))
    content = " ".join(
        [
            causes[0],
            techniques[0],
            schema._FLAVOR_TERMS[0],
            schema._DIET_TAG_TERMS[0],
            schema._HEALTH_TAG_TERMS[0],
            schema._CUISINE_STYLE_TERMS[0],
            schema._INGREDIENT_CATEGORY_TERMS[0],
        ]
    )

    result = schema.infer_recipe_semantics(
        {"tags": ["quick", "quick"], "difficulty": 2, "cookingTime": 15},
        [schema._INGREDIENT_CATEGORY_TERMS[0]],
        [techniques[0]],
        content,
    )

    relations = result["semantic_relations"]
    assert result["flavor_tags"]
    assert result["diet_tags"]
    assert result["health_tags"]
    assert result["cuisine_style_tags"]
    assert result["ingredient_category_tags"]
    assert relations["CONTRIBUTES_TO"][0]["effect"] == contribution_effect
    assert any(
        item["effect"] == contribution_effect for item in relations["INGREDIENT_CONTRIBUTES_TO"]
    )
    assert any(
        item["effect"] == technique_effect for item in relations["TECHNIQUE_MODIFIES_TEXTURE"]
    )

    empty = schema.infer_recipe_semantics({}, [], [], "")
    assert empty["semantic_relations"]["CONTRIBUTES_TO"] == []
    assert empty["semantic_relations"]["TECHNIQUE_MODIFIES_TEXTURE"] == []
