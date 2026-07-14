"""Validate allowed pull-request flows between governed branches."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence

GOVERNED_TARGETS = {"development", "production", "main"}
EXACT_ALLOWED_SOURCES: dict[str, set[str]] = {
    "main": {"production"},
    "production": {"development", "main"},
    "development": {"production"},
}
PREFIX_ALLOWED_SOURCES: dict[str, tuple[str, ...]] = {
    "main": ("hotfix/", "codex/sync-"),
    "production": ("codex/sync-",),
    "development": ("feature/", "fix/", "hotfix/", "codex/", "dependabot/"),
}


@dataclass(frozen=True)
class FlowDecision:
    allowed: bool
    message: str


def _normalize_ref(ref: str) -> str:
    return ref.removeprefix("refs/heads/").strip()


def evaluate_branch_flow(base: str, head: str) -> FlowDecision:
    normalized_base = _normalize_ref(base)
    normalized_head = _normalize_ref(head)

    if normalized_base not in GOVERNED_TARGETS:
        return FlowDecision(
            allowed=True,
            message=f"allowed: {normalized_base} is not a governed target",
        )

    exact_sources = EXACT_ALLOWED_SOURCES[normalized_base]
    prefix_sources = PREFIX_ALLOWED_SOURCES[normalized_base]
    if normalized_head in exact_sources or normalized_head.startswith(prefix_sources):
        return FlowDecision(
            allowed=True,
            message=f"allowed: {normalized_head} -> {normalized_base}",
        )

    rendered_sources = sorted(exact_sources) + [f"{prefix}*" for prefix in prefix_sources]
    return FlowDecision(
        allowed=False,
        message=(
            f"rejected: {normalized_head} -> {normalized_base}; "
            f"allowed sources: {', '.join(rendered_sources)}"
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Pull-request target branch.")
    parser.add_argument("--head", required=True, help="Pull-request source branch.")
    parser.add_argument("--mode", choices=("report", "enforce"), default="enforce")
    args = parser.parse_args(argv)

    decision = evaluate_branch_flow(args.base, args.head)
    suffix = " (report-only)" if args.mode == "report" and not decision.allowed else ""
    print(f"{decision.message}{suffix}")
    if decision.allowed or args.mode == "report":
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
