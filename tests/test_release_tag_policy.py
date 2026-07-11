from __future__ import annotations

import pytest

from scripts.validate_release_tag import parse_release_tag, validate_release_tag


def test_parse_release_candidate_tag() -> None:
    parsed = parse_release_tag("v0.4.0-rc.2")
    assert parsed.package_version == "0.4.0rc2"
    assert parsed.branch == "production"
    assert parsed.prerelease is True


def test_parse_final_tag() -> None:
    parsed = parse_release_tag("v0.4.0")
    assert parsed.package_version == "0.4.0"
    assert parsed.branch == "main"
    assert parsed.prerelease is False


@pytest.mark.parametrize(
    "tag",
    ["0.4.0", "v0.4", "v0.4.0rc1", "v0.4.0-rc.0", "v01.4.0", "v0.4.0-beta.1"],
)
def test_reject_invalid_tag_grammar(tag: str) -> None:
    with pytest.raises(ValueError, match="invalid release tag"):
        parse_release_tag(tag)


def test_validate_rejects_package_version_mismatch() -> None:
    errors = validate_release_tag(
        tag="v0.4.0-rc.1",
        package_version="0.4.0rc2",
        tag_commit="a" * 40,
        branch_commit="a" * 40,
    )
    assert errors == ["tag v0.4.0-rc.1 requires package version 0.4.0rc1, got 0.4.0rc2"]


def test_validate_rejects_wrong_branch_tip() -> None:
    errors = validate_release_tag(
        tag="v0.4.0",
        package_version="0.4.0",
        tag_commit="a" * 40,
        branch_commit="b" * 40,
    )
    assert errors == ["tag v0.4.0 must point to current main tip"]


def test_validate_accepts_matching_tag_version_and_branch() -> None:
    errors = validate_release_tag(
        tag="v0.4.0-rc.1",
        package_version="0.4.0rc1",
        tag_commit="a" * 40,
        branch_commit="a" * 40,
    )
    assert errors == []
