"""Support helpers for the public application facade over runtime state."""

from __future__ import annotations

from typing import Any

from ...artifacts import ArtifactManifest
from ..legacy_surface import (
    GROUPED_LEGACY_ATTRIBUTE_MAP,
    GroupedLegacyAttributeMap,
    merge_legacy_dir_names,
    resolve_grouped_legacy_attribute,
)
from ..runtime_state import BuildRuntime, ServingRuntime
from ..runtime_view import SystemInfrastructureView, SystemRetrievalView, SystemRuntime, SystemServicesView
from .runtime_state_store import RuntimeStateStore


class SystemFacadeSupport:
    """Centralize runtime access and legacy surface behavior for the public facade."""

    def __init__(
        self,
        *,
        runtime_state_store: RuntimeStateStore,
        legacy_attribute_map: GroupedLegacyAttributeMap = GROUPED_LEGACY_ATTRIBUTE_MAP,
    ) -> None:
        self.runtime_state_store = runtime_state_store
        self.legacy_attribute_map = legacy_attribute_map

    def resolve_legacy_attribute(self, owner: object, name: str) -> Any:
        return resolve_grouped_legacy_attribute(owner, self.legacy_attribute_map, name)

    def legacy_dir(self, owner: object) -> list[str]:
        return merge_legacy_dir_names(object.__dir__(owner), self.legacy_attribute_map)

    @property
    def runtime(self) -> SystemRuntime:
        return self.runtime_state_store.runtime

    @property
    def build_runtime(self) -> BuildRuntime | None:
        return self.runtime_state_store.build_runtime

    @property
    def serving_runtime(self) -> ServingRuntime | None:
        return self.runtime_state_store.serving_runtime

    @property
    def infrastructure(self) -> SystemInfrastructureView:
        return self.runtime_state_store.runtime_view().infrastructure

    @property
    def retrieval(self) -> SystemRetrievalView:
        return self.runtime_state_store.runtime_view().retrieval

    @property
    def services(self) -> SystemServicesView:
        return self.runtime_state_store.runtime_view().services

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.runtime_state_store.artifact_manifest

    @property
    def artifacts_ready(self) -> bool:
        return self.runtime_state_store.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self.runtime_state_store.system_ready


__all__ = ["SystemFacadeSupport"]
