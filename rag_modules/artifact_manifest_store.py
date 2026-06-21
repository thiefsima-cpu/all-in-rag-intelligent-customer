"""Durable artifact manifest store."""

from __future__ import annotations

import json
import os
from typing import Any, List, Mapping

from .artifact_json import write_json_atomic
from .artifact_manifest import (
    ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ARTIFACT_STAGE_MANIFEST_UNREADABLE,
    ArtifactManifest,
)


class ArtifactManifestStore:
    """Persist an active manifest, a candidate sidecar, and immutable versions."""

    def __init__(self, config):
        storage = config.storage
        self.manifest_path = str(storage.artifact_manifest_path)
        parent_dir = os.path.dirname(self.manifest_path)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        filename = os.path.basename(self.manifest_path)
        stem, _ = os.path.splitext(filename)
        self.candidate_path = os.path.join(
            parent_dir,
            f"{stem}.candidate.json",
        )
        self.versions_dir = os.path.join(parent_dir, f"{stem}.versions")

    def load(self) -> ArtifactManifest:
        if not os.path.exists(self.manifest_path):
            return ArtifactManifest.missing(manifest_path=self.manifest_path)
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            manifest = ArtifactManifest.from_dict(payload)
            if manifest.manifest_path != self.manifest_path:
                manifest = manifest.evolve(manifest_path=self.manifest_path)
            return manifest
        except Exception as exc:
            return ArtifactManifest.missing(
                manifest_path=self.manifest_path,
            ).evolve(
                stage=ARTIFACT_STAGE_MANIFEST_UNREADABLE,
                last_error=str(exc),
            )

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        current = self.load()
        next_version = max(
            int(current.manifest_version or 0) + 1,
            int(manifest.manifest_version or 0),
            1,
        )
        normalized = manifest.evolve(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=next_version,
            manifest_path=self.manifest_path,
        )
        self._write_json_atomic(
            self.version_path(next_version),
            normalized.to_dict(),
        )
        self._write_json_atomic(self.manifest_path, normalized.to_dict())
        return normalized

    def load_candidate(self) -> ArtifactManifest | None:
        if not os.path.exists(self.candidate_path):
            return None
        try:
            with open(self.candidate_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            manifest = ArtifactManifest.from_dict(payload)
            return manifest.evolve(
                manifest_path=self.manifest_path,
                updated_at=manifest.updated_at,
            )
        except Exception:
            return None

    def save_candidate(self, manifest: ArtifactManifest) -> ArtifactManifest:
        active = self.load()
        candidate_version = max(
            int(active.manifest_version or 0) + 1,
            int(manifest.manifest_version or 0),
            1,
        )
        normalized = manifest.evolve(
            schema_version=ARTIFACT_MANIFEST_SCHEMA_VERSION,
            manifest_version=candidate_version,
            manifest_path=self.manifest_path,
        )
        self._write_json_atomic(self.candidate_path, normalized.to_dict())
        return normalized

    def clear_candidate(self) -> None:
        try:
            os.remove(self.candidate_path)
        except FileNotFoundError:
            return

    def version_path(self, manifest_version: int) -> str:
        return os.path.join(
            self.versions_dir,
            f"v{int(manifest_version):06d}.json",
        )

    def list_versions(self) -> List[int]:
        versions: List[int] = []
        if not os.path.isdir(self.versions_dir):
            return versions
        for filename in os.listdir(self.versions_dir):
            if not (filename.startswith("v") and filename.endswith(".json")):
                continue
            try:
                versions.append(int(filename[1:-5]))
            except ValueError:
                continue
        return sorted(versions)

    def load_version(self, manifest_version: int) -> ArtifactManifest:
        path = self.version_path(manifest_version)
        with open(path, "r", encoding="utf-8") as file:
            manifest = ArtifactManifest.from_dict(json.load(file))
            return manifest.evolve(
                manifest_path=self.manifest_path,
                updated_at=manifest.updated_at,
            )

    @staticmethod
    def _write_json_atomic(path: str, payload: Mapping[str, Any]) -> None:
        write_json_atomic(path, payload)


__all__ = ["ArtifactManifestStore"]
