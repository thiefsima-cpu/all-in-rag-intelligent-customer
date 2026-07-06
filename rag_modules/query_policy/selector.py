"""Resolve configured query policy bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .loader import DEFAULT_BUNDLE_NAME, default_policy_bundle_path, get_query_policy
from .models import QueryPolicyBundle


class _EnvironmentSource(Protocol):
    def get_first(self, *names: str) -> str | None: ...


@dataclass(frozen=True)
class QueryPolicySelector:
    bundle: str = DEFAULT_BUNDLE_NAME
    bundle_path: str = ""


def _selector_mapping(payload: Mapping[str, object]) -> Mapping[str, object]:
    query_understanding = payload.get("query_understanding")
    if not isinstance(query_understanding, Mapping):
        return {}
    selector = query_understanding.get("policy")
    return selector if isinstance(selector, Mapping) else {}


def resolve_query_policy_selector(
    domain_payload: Mapping[str, object],
    profile_overrides: Mapping[str, object],
    env_source: _EnvironmentSource | None = None,
    overrides: Mapping[str, object] | None = None,
) -> QueryPolicySelector:
    base = _selector_mapping(domain_payload)
    profile = _selector_mapping(profile_overrides)
    explicit = _selector_mapping(overrides or {})
    bundle = str(profile.get("bundle", base.get("bundle", DEFAULT_BUNDLE_NAME)) or "").strip()
    bundle_path = str(profile.get("bundle_path", base.get("bundle_path", "")) or "").strip()
    env_bundle = env_source.get_first("QUERY_POLICY_BUNDLE") if env_source is not None else None
    env_bundle_path = (
        env_source.get_first("QUERY_POLICY_BUNDLE_PATH") if env_source is not None else None
    )
    if env_bundle is not None:
        bundle = env_bundle
    if env_bundle_path is not None:
        bundle_path = env_bundle_path
    if "bundle" in explicit:
        bundle = str(explicit["bundle"] or "")
    if "bundle_path" in explicit:
        bundle_path = str(explicit["bundle_path"] or "")
    return QueryPolicySelector(
        bundle=str(bundle).strip() or DEFAULT_BUNDLE_NAME,
        bundle_path=str(bundle_path).strip(),
    )


def resolve_query_policy_bundle_from_selector(
    selector: QueryPolicySelector,
) -> QueryPolicyBundle:
    return resolve_query_policy_bundle(selector)


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


__all__ = [
    "QueryPolicySelector",
    "resolve_query_policy_bundle",
    "resolve_query_policy_bundle_from_selector",
    "resolve_query_policy_selector",
]
