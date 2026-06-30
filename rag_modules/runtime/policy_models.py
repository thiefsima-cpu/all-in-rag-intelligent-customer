"""Policy metadata snapshots for traces and reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .json_types import JsonObject


@dataclass
class PolicySnapshot:
    schema_version: str = ""
    policy_version: str = ""
    prompt_version: str = ""
    policy_hash: str = ""
    prompt_hash: str = ""
    bundle_name: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, object] | None) -> "PolicySnapshot":
        payload = dict(data or {})
        return cls(
            schema_version=str(payload.get("schema_version") or ""),
            policy_version=str(payload.get("policy_version") or ""),
            prompt_version=str(payload.get("prompt_version") or ""),
            policy_hash=str(payload.get("policy_hash") or ""),
            prompt_hash=str(payload.get("prompt_hash") or ""),
            bundle_name=str(payload.get("bundle_name") or ""),
        )

    @classmethod
    def from_metadata(cls, metadata: object) -> "PolicySnapshot":
        to_dict = getattr(metadata, "to_dict", None)
        return cls.from_dict(to_dict() if callable(to_dict) else {})

    def to_dict(self) -> JsonObject:
        return {
            "schema_version": self.schema_version,
            "policy_version": self.policy_version,
            "prompt_version": self.prompt_version,
            "policy_hash": self.policy_hash,
            "prompt_hash": self.prompt_hash,
            "bundle_name": self.bundle_name,
        }

    def is_recorded(self) -> bool:
        return bool(self.policy_version and self.prompt_version and self.policy_hash)


__all__ = ["PolicySnapshot"]
