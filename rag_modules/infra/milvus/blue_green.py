"""Milvus blue-green collection publish operations."""

from __future__ import annotations

from typing import Dict


class _MilvusBlueGreenOperations:
    def use_manifest(self, manifest) -> str:
        """Bind reads to the collection published by an artifact manifest."""

        published_collection = str(getattr(manifest, "collection_name", "") or "")
        published_slot = str(getattr(manifest, "collection_slot", "") or "")
        self.active_collection_name = published_collection
        self.active_collection_slot = published_slot
        if not published_collection:
            self.collection_name = self.base_collection_name
            return self.collection_name

        alias_target = self.alias_target()
        if self.blue_green_enabled and alias_target == published_collection:
            self.collection_name = self.collection_alias
        else:
            self.collection_name = published_collection
        return self.collection_name

    def prepare_blue_green_build(self, active_collection_name: str = "") -> Dict[str, str]:
        """Select the inactive physical collection for the next build."""

        if not self.blue_green_enabled:
            self.build_collection_name = self.base_collection_name
            self.collection_name = self.build_collection_name
            return {
                "collection_name": self.build_collection_name,
                "collection_base_name": self.base_collection_name,
                "collection_slot": "",
            }

        active_name = active_collection_name or self.active_collection_name
        active_slot = self._collection_slot(active_name)
        target_slot = "green" if active_slot == "blue" else "blue"
        target_collection = self.physical_collection_name(target_slot)
        self.build_collection_name = target_collection
        self.collection_name = target_collection
        return {
            "collection_name": target_collection,
            "collection_base_name": self.base_collection_name,
            "collection_slot": target_slot,
        }

    def publish_collection(self, collection_name: str) -> str:
        """Atomically point the stable Milvus alias at a built collection."""

        target_collection = str(collection_name)
        if not self.client.has_collection(target_collection):
            raise ValueError(f"Cannot publish missing Milvus collection: {target_collection}")

        previous_target = self.alias_target()
        if self.blue_green_enabled:
            if previous_target:
                self.client.alter_alias(
                    collection_name=target_collection,
                    alias=self.collection_alias,
                )
            else:
                self.client.create_alias(
                    collection_name=target_collection,
                    alias=self.collection_alias,
                )
            self.collection_name = self.collection_alias
        else:
            self.collection_name = target_collection

        self.active_collection_name = target_collection
        self.active_collection_slot = self._collection_slot(target_collection)
        self.collection_created = True
        return previous_target

    def rollback_collection_publish(self, previous_collection_name: str = "") -> None:
        """Restore the alias target when manifest publication fails."""

        if not self.blue_green_enabled:
            if previous_collection_name:
                self.collection_name = previous_collection_name
            return

        current_target = self.alias_target()
        if previous_collection_name:
            if current_target:
                self.client.alter_alias(
                    collection_name=previous_collection_name,
                    alias=self.collection_alias,
                )
            else:
                self.client.create_alias(
                    collection_name=previous_collection_name,
                    alias=self.collection_alias,
                )
            self.collection_name = self.collection_alias
            self.active_collection_name = previous_collection_name
            self.active_collection_slot = self._collection_slot(previous_collection_name)
        elif current_target:
            self.client.drop_alias(alias=self.collection_alias)
            self.collection_name = self.base_collection_name
            self.active_collection_name = ""
            self.active_collection_slot = ""

    def discard_build_collection(self, collection_name: str) -> bool:
        target_collection = str(collection_name or "")
        if not target_collection or target_collection == self.active_collection_name:
            return True
        return self.delete_collection(target_collection)

    def alias_target(self) -> str:
        if not self.blue_green_enabled:
            return ""
        try:
            payload = self.client.describe_alias(alias=self.collection_alias) or {}
        except Exception:
            return ""
        return str(
            payload.get("collection")
            or payload.get("collection_name")
            or ""
        )

    def physical_collection_name(self, slot: str) -> str:
        normalized_slot = "green" if str(slot).lower() == "green" else "blue"
        return f"{self.base_collection_name}__{normalized_slot}"

    def _collection_slot(self, collection_name: str) -> str:
        name = str(collection_name or "")
        if name == self.physical_collection_name("blue"):
            return "blue"
        if name == self.physical_collection_name("green"):
            return "green"
        return ""
