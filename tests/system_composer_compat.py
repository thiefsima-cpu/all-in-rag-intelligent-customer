"""Test-only adapters for retired flat system-composer override keywords."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from rag_modules.app.composition import (
    AdvancedGraphRAGSystemComposer,
    AdvancedGraphRAGSystemOverrides,
    SystemBootstrapperOverrides,
    SystemBootstrapperSurfaceComposer,
    SystemFacadeOverrides,
    SystemRuntimeOverrides,
)

_BOOTSTRAPPER_OVERRIDE_KEYS = frozenset(SystemBootstrapperOverrides.__dataclass_fields__)
_RUNTIME_OVERRIDE_KEYS = frozenset(SystemRuntimeOverrides.__dataclass_fields__)
_FACADE_OVERRIDE_KEYS = frozenset(SystemFacadeOverrides.__dataclass_fields__)
_COMPOSER_OVERRIDE_KEYS = frozenset(
    {
        "bootstrapper_surface_composer",
        "lifecycle_service_composer",
        "runtime_infrastructure_composer",
    }
)
_SYSTEM_LEGACY_OVERRIDE_KEYS = (
    _BOOTSTRAPPER_OVERRIDE_KEYS
    | _RUNTIME_OVERRIDE_KEYS
    | _FACADE_OVERRIDE_KEYS
    | _COMPOSER_OVERRIDE_KEYS
)


def _reject_unknown_overrides(
    legacy_overrides: Mapping[str, object],
    allowed_keys: frozenset[str],
) -> None:
    unknown_keys = sorted(set(legacy_overrides) - allowed_keys)
    if unknown_keys:
        names = ", ".join(unknown_keys)
        raise TypeError(f"Unexpected system composer override(s): {names}")


def _replacement_values(
    legacy_overrides: Mapping[str, object],
    allowed_keys: frozenset[str],
) -> dict[str, object]:
    return {
        key: legacy_overrides[key]
        for key in allowed_keys.intersection(legacy_overrides)
        if legacy_overrides[key] is not None
    }


def legacy_bootstrapper_overrides(
    overrides: SystemBootstrapperOverrides | None = None,
    **legacy_overrides: object,
) -> SystemBootstrapperOverrides:
    _reject_unknown_overrides(legacy_overrides, _BOOTSTRAPPER_OVERRIDE_KEYS)
    values = _replacement_values(legacy_overrides, _BOOTSTRAPPER_OVERRIDE_KEYS)
    resolved = overrides or SystemBootstrapperOverrides()
    return replace(resolved, **values) if values else resolved


def legacy_system_overrides(
    overrides: AdvancedGraphRAGSystemOverrides | None = None,
    **legacy_overrides: object,
) -> AdvancedGraphRAGSystemOverrides:
    _reject_unknown_overrides(legacy_overrides, _SYSTEM_LEGACY_OVERRIDE_KEYS)
    resolved = overrides or AdvancedGraphRAGSystemOverrides()
    bootstrapper_values = _replacement_values(legacy_overrides, _BOOTSTRAPPER_OVERRIDE_KEYS)
    runtime_values = _replacement_values(legacy_overrides, _RUNTIME_OVERRIDE_KEYS)
    facade_values = _replacement_values(legacy_overrides, _FACADE_OVERRIDE_KEYS)
    composer_values = _replacement_values(legacy_overrides, _COMPOSER_OVERRIDE_KEYS)

    return replace(
        resolved,
        bootstrapper=replace(resolved.bootstrapper, **bootstrapper_values)
        if bootstrapper_values
        else resolved.bootstrapper,
        runtime=replace(resolved.runtime, **runtime_values) if runtime_values else resolved.runtime,
        facade=replace(resolved.facade, **facade_values) if facade_values else resolved.facade,
        **composer_values,
    )


class LegacySystemBootstrapperSurfaceComposerAdapter:
    """Accept flat bootstrapper kwargs and call the strict surface composer."""

    def __init__(self, composer: SystemBootstrapperSurfaceComposer | None = None) -> None:
        self.composer = composer or SystemBootstrapperSurfaceComposer()

    def compose(
        self,
        *,
        overrides: SystemBootstrapperOverrides | None = None,
        **legacy_overrides: object,
    ):
        return self.composer.compose(
            overrides=legacy_bootstrapper_overrides(overrides, **legacy_overrides),
        )


class LegacySystemComposerAdapter:
    """Accept flat system kwargs and call the strict system composer."""

    def __init__(self, composer: AdvancedGraphRAGSystemComposer | None = None) -> None:
        self.composer = composer or AdvancedGraphRAGSystemComposer()

    def resolve_bootstrapper_surface(
        self,
        *,
        overrides: SystemBootstrapperOverrides | None = None,
        bootstrapper_surface_composer: SystemBootstrapperSurfaceComposer | None = None,
        **legacy_overrides: object,
    ):
        return self.composer.resolve_bootstrapper_surface(
            overrides=legacy_bootstrapper_overrides(overrides, **legacy_overrides),
            bootstrapper_surface_composer=bootstrapper_surface_composer,
        )

    def compose(
        self,
        config=None,
        *,
        overrides: AdvancedGraphRAGSystemOverrides | None = None,
        **legacy_overrides: object,
    ):
        return self.composer.compose(
            config=config,
            overrides=legacy_system_overrides(overrides, **legacy_overrides),
        )


__all__ = [
    "LegacySystemBootstrapperSurfaceComposerAdapter",
    "LegacySystemComposerAdapter",
    "legacy_bootstrapper_overrides",
    "legacy_system_overrides",
]
