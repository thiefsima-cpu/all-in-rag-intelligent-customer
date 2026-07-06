"""Versioned artifact registry over the persisted manifest store."""

from __future__ import annotations

from dataclasses import dataclass

from ...kernel.artifacts import ArtifactManifest
from ..artifact_ports import ArtifactManifestStorePort


@dataclass(frozen=True, slots=True)
class ArtifactRegistrySnapshot:
    active: ArtifactManifest
    candidate: ArtifactManifest | None
    versions: tuple[int, ...]


class ArtifactRegistry:
    """Resolve active, candidate, and immutable artifact manifest versions."""

    def __init__(self, manifest_store: ArtifactManifestStorePort) -> None:
        self.manifest_store = manifest_store

    def active(self) -> ArtifactManifest:
        return self.manifest_store.load()

    def candidate(self) -> ArtifactManifest | None:
        return self.manifest_store.load_candidate()

    def versions(self) -> tuple[int, ...]:
        return tuple(int(version) for version in self.manifest_store.list_versions())

    def get(self, manifest_version: int) -> ArtifactManifest:
        return self.manifest_store.load_version(int(manifest_version))

    def list(self) -> list[ArtifactManifest]:
        manifests: list[ArtifactManifest] = []
        for version in reversed(self.versions()):
            try:
                manifests.append(self.get(version))
            except (OSError, ValueError, TypeError):
                continue
        return manifests

    def has_newer_active(self, manifest: ArtifactManifest | int | None) -> bool:
        current_version = (
            int(manifest.manifest_version)
            if isinstance(manifest, ArtifactManifest)
            else int(manifest or 0)
        )
        active = self.active()
        return active.is_ready and active.manifest_version > current_version

    def snapshot(self) -> ArtifactRegistrySnapshot:
        return ArtifactRegistrySnapshot(
            active=self.active(),
            candidate=self.candidate(),
            versions=self.versions(),
        )


__all__ = [
    "ArtifactRegistry",
    "ArtifactRegistrySnapshot",
]
