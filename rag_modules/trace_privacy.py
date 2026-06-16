"""Privacy-preserving serialization for structured query traces."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping, Sequence
from typing import Any

from .runtime import QueryTraceEvent

_CONTENT_KEYS = frozenset(
    {
        "answer",
        "authorization",
        "category_terms",
        "content",
        "cookie",
        "cuisine_terms",
        "entity_keywords",
        "error",
        "excluded_category_terms",
        "excluded_cuisine_terms",
        "excluded_ingredients",
        "excluded_terms",
        "exclude_terms",
        "health_terms",
        "include_terms",
        "ingredients",
        "matched_terms",
        "password",
        "preference_terms",
        "preview",
        "prompt",
        "query",
        "question",
        "secret",
        "source_entities",
        "sub_questions",
        "target_entities",
        "token",
        "topic_keywords",
    }
)
_CREDENTIAL_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "api_token",
        "auth_token",
        "client_secret",
        "neo4j_password",
        "refresh_token",
    }
)
_SENSITIVE_SUFFIXES = (
    "_answer",
    "_authorization",
    "_content",
    "_error",
    "_password",
    "_preview",
    "_prompt",
    "_query",
    "_question",
    "_secret",
)


class TraceSanitizer:
    """Replace trace content with salted fingerprints while preserving structure."""

    def __init__(self, salt: str = "") -> None:
        self._salt = (str(salt or "") or secrets.token_hex(32)).encode("utf-8")

    def sanitize_event(self, event: QueryTraceEvent) -> QueryTraceEvent:
        payload = self.sanitize_value(event.to_dict())
        return QueryTraceEvent.from_dict(payload)

    def sanitize_value(
        self,
        value: Any,
        *,
        key: str = "",
        force_sensitive: bool = False,
    ) -> Any:
        sensitive = force_sensitive or self._is_sensitive_key(key)
        if isinstance(value, Mapping):
            protect_children = force_sensitive or self._is_credential_key(key)
            return {
                str(child_key): self.sanitize_value(
                    child_value,
                    key=str(child_key),
                    force_sensitive=protect_children,
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [
                self.sanitize_value(
                    item,
                    key=key,
                    force_sensitive=sensitive,
                )
                for item in value
            ]
        if sensitive and value not in (None, ""):
            return self.fingerprint(value)
        return value

    def fingerprint(self, value: Any) -> str:
        text = str(value)
        if text.startswith("sha256:") and ":chars=" in text:
            return text
        digest = hmac.new(
            self._salt,
            text.encode("utf-8", errors="backslashreplace"),
            hashlib.sha256,
        ).hexdigest()
        return f"sha256:{digest}:chars={len(text)}"

    @staticmethod
    def _is_sensitive_key(key: str) -> bool:
        normalized = str(key or "").strip().lower().replace("-", "_")
        return (
            normalized in _CONTENT_KEYS
            or normalized in _CREDENTIAL_KEYS
            or normalized.endswith(_SENSITIVE_SUFFIXES)
        )

    @staticmethod
    def _is_credential_key(key: str) -> bool:
        normalized = str(key or "").strip().lower().replace("-", "_")
        return normalized in _CREDENTIAL_KEYS


__all__ = ["TraceSanitizer"]
