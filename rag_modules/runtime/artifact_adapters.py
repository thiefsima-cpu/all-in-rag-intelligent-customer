"""Default artifact lifecycle adapters shared by runtime composition."""

from __future__ import annotations

from typing import Any


class DefaultRuntimeArtifactAccess:
    """Default adapter over graph-data loading and vector-index readiness."""

    def load_graph_data(self, data_module: Any) -> Any:
        return data_module.load_graph_data()

    def configure_vector_collection(self, index_module: Any, manifest: Any) -> str:
        binder = getattr(index_module, "use_manifest", None)
        if callable(binder):
            return str(binder(manifest))
        collection_name = str(getattr(manifest, "collection_name", "") or "")
        if collection_name and hasattr(index_module, "collection_name"):
            index_module.collection_name = collection_name
        return collection_name

    def has_vector_collection(self, index_module: Any) -> bool:
        return bool(index_module.has_collection())

    def load_vector_collection(self, index_module: Any) -> bool:
        return bool(index_module.load_collection())

    def prepare_vector_index_build(
        self,
        index_module: Any,
        active_collection_name: str = "",
    ) -> dict[str, str]:
        preparer = getattr(index_module, "prepare_blue_green_build", None)
        if callable(preparer):
            return dict(preparer(active_collection_name) or {})
        return {
            "collection_name": str(getattr(index_module, "collection_name", "") or ""),
            "collection_base_name": str(getattr(index_module, "collection_name", "") or ""),
            "collection_slot": "",
        }

    def build_vector_index(
        self,
        index_module: Any,
        chunks: Any,
        *,
        collection_name: str = "",
    ) -> bool:
        if collection_name:
            try:
                return bool(
                    index_module.build_vector_index(
                        chunks,
                        collection_name=collection_name,
                    )
                )
            except TypeError:
                pass
        return bool(index_module.build_vector_index(chunks))

    def publish_vector_index(self, index_module: Any, collection_name: str) -> str:
        publisher = getattr(index_module, "publish_collection", None)
        if callable(publisher):
            return str(publisher(collection_name) or "")
        if collection_name and hasattr(index_module, "collection_name"):
            index_module.collection_name = collection_name
        return ""

    def rollback_vector_index_publish(
        self,
        index_module: Any,
        previous_collection_name: str = "",
    ) -> None:
        rollback = getattr(index_module, "rollback_collection_publish", None)
        if callable(rollback):
            rollback(previous_collection_name)

    def discard_vector_index(self, index_module: Any, collection_name: str) -> bool:
        discard = getattr(index_module, "discard_build_collection", None)
        if callable(discard):
            return bool(discard(collection_name))
        return True

    def delete_vector_collection(self, index_module: Any) -> bool:
        return bool(index_module.delete_collection())


__all__ = ["DefaultRuntimeArtifactAccess"]
