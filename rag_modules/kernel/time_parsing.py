"""Low-level duration parsing helpers."""

from __future__ import annotations

import re
from typing import Any, Optional


def parse_minutes(value: Any) -> Optional[int]:
    """Parse loose Chinese/English duration text into minutes."""

    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None

    total = 0.0
    hour_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:灏忔椂|灏忔檪|h|hr|hour)",
        text,
        flags=re.I,
    )
    minute_matches = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:鍒嗛挓|鍒嗛嵕|min|minute)",
        text,
        flags=re.I,
    )
    if hour_matches or minute_matches:
        total += sum(float(x) * 60 for x in hour_matches)
        total += sum(float(x) for x in minute_matches)
        return int(round(total)) if total > 0 else None

    # For ranges like "15-20", use the upper bound to avoid violating max-time constraints.
    return int(round(max(nums)))


__all__ = ["parse_minutes"]
