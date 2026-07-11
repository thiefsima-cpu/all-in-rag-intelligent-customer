"""Validate protected release tags against package metadata and branch provenance."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import Sequence

TAG_PATTERN = re.compile(
    r"^v(?P<major>0|[1-9]\d*)\."
    r"(?P<minor>0|[1-9]\d*)\."
    r"(?P<patch>0|[1-9]\d*)"
    r"(?:-rc\.(?P<rc>[1-9]\d*))?$"
)


@dataclass(frozen=True)
class ReleaseTag:
    tag: str
    package_version: str
    branch: str
    prerelease: bool


def parse_release_tag(tag: str) -> ReleaseTag:
    match = TAG_PATTERN.fullmatch(tag)
    if match is None:
        raise ValueError(f"invalid release tag: {tag}")

    core = ".".join(match.group(name) for name in ("major", "minor", "patch"))
    rc = match.group("rc")
    if rc is not None:
        return ReleaseTag(
            tag=tag,
            package_version=f"{core}rc{rc}",
            branch="production",
            prerelease=True,
        )
    return ReleaseTag(tag=tag, package_version=core, branch="main", prerelease=False)


def validate_release_tag(
    *,
    tag: str,
    package_version: str,
    tag_commit: str,
    branch_commit: str,
) -> list[str]:
    parsed = parse_release_tag(tag)
    errors: list[str] = []
    if package_version != parsed.package_version:
        errors.append(
            f"tag {tag} requires package version {parsed.package_version}, got {package_version}"
        )
    if tag_commit != branch_commit:
        errors.append(f"tag {tag} must point to current {parsed.branch} tip")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--package-version", required=True)
    parser.add_argument("--tag-commit", required=True)
    parser.add_argument("--branch-commit", required=True)
    args = parser.parse_args(argv)

    try:
        parsed = parse_release_tag(args.tag)
        errors = validate_release_tag(
            tag=args.tag,
            package_version=args.package_version,
            tag_commit=args.tag_commit,
            branch_commit=args.branch_commit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    if errors:
        for error in errors:
            print(error)
        return 1
    release_kind = "prerelease" if parsed.prerelease else "final"
    print(f"validated {release_kind} {parsed.tag} from {parsed.branch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
