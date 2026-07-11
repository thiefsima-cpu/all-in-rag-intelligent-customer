"""Encoding helpers for build-job repository storage."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import datetime


def encode_cursor(created_at: str, job_id: str) -> str:
    payload = json.dumps(
        {"created_at": created_at, "job_id": job_id},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, Mapping):
            raise ValueError
        if set(payload) != {"created_at", "job_id"}:
            raise ValueError
        created_at = str(payload.get("created_at") or "")
        job_id = str(payload.get("job_id") or "")
        if not created_at or not job_id:
            raise ValueError
        return created_at, job_id
    except (OSError, TypeError, ValueError):
        raise ValueError("invalid build job cursor") from None


def datetime_from_json(value: object) -> datetime:
    text = str(value or "")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


__all__ = ["datetime_from_json", "decode_cursor", "encode_cursor"]
