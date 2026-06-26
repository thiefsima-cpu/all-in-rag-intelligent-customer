"""Vector publish operations for knowledge-base build workflow."""

from __future__ import annotations

from ..runtime.artifacts import ArtifactManifest


class _KnowledgeBaseVectorPublishMixin:
    """Own vector build, publish, rollback, and discard interactions."""

    def _prepare_vector_build(
        self,
        active_manifest: ArtifactManifest,
    ) -> dict[str, str]:
        prepare = getattr(
            self.runtime_artifact_access,
            "prepare_vector_index_build",
            None,
        )
        if callable(prepare):
            target = dict(
                prepare(
                    self.index_module,
                    active_manifest.collection_name if active_manifest.is_ready else "",
                )
                or {}
            )
        else:
            target = {}
        base_name = str(
            target.get("collection_base_name")
            or getattr(self.config.storage, "milvus_collection_name", "")
            or getattr(self.index_module, "collection_name", "")
        )
        collection_name = str(
            target.get("collection_name")
            or getattr(self.index_module, "collection_name", "")
            or base_name
        )
        return {
            "collection_name": collection_name,
            "collection_base_name": base_name,
            "collection_slot": str(target.get("collection_slot") or ""),
        }

    def _build_vector_index(self, chunks, *, collection_name: str) -> bool:
        try:
            return bool(
                self.runtime_artifact_access.build_vector_index(
                    self.index_module,
                    chunks,
                    collection_name=collection_name,
                )
            )
        except TypeError:
            return bool(
                self.runtime_artifact_access.build_vector_index(
                    self.index_module,
                    chunks,
                )
            )

    def _publish_vector_index(self, collection_name: str) -> str:
        publish = getattr(
            self.runtime_artifact_access,
            "publish_vector_index",
            None,
        )
        if not callable(publish):
            return ""
        return str(publish(self.index_module, collection_name) or "")

    def _rollback_vector_publish(self, previous_collection_name: str) -> None:
        rollback = getattr(
            self.runtime_artifact_access,
            "rollback_vector_index_publish",
            None,
        )
        if callable(rollback):
            rollback(self.index_module, previous_collection_name)

    def _discard_vector_build(self, collection_name: str) -> None:
        discard = getattr(
            self.runtime_artifact_access,
            "discard_vector_index",
            None,
        )
        if callable(discard):
            discard(self.index_module, collection_name)


__all__ = ["_KnowledgeBaseVectorPublishMixin"]
