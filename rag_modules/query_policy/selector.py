"""Resolve configured query policy bundles."""

from __future__ import annotations

from .loader import DEFAULT_BUNDLE_NAME, default_policy_bundle_path, get_query_policy
from .models import QueryPolicyBundle


def resolve_query_policy_bundle(config_or_selector: object | None = None) -> QueryPolicyBundle:
    """Load the query policy bundle selected by config or selector settings."""

    if config_or_selector is None:
        return get_query_policy()

    selector = getattr(getattr(config_or_selector, "query_understanding", None), "policy", None)
    if selector is None:
        selector = config_or_selector

    bundle_path = str(getattr(selector, "bundle_path", "") or "").strip()
    if bundle_path:
        return get_query_policy(bundle_path)

    bundle_name = str(getattr(selector, "bundle", "") or "").strip() or DEFAULT_BUNDLE_NAME
    if bundle_name == DEFAULT_BUNDLE_NAME:
        return get_query_policy()
    return get_query_policy(default_policy_bundle_path().parent / bundle_name)


__all__ = ["resolve_query_policy_bundle"]
