from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import StrEnum
from numbers import Integral, Real
from pathlib import Path
from typing import Any


def json_safe(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value

    if is_dataclass(value) and not isinstance(value, type):
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return json_safe(to_dict())
        return {field.name: json_safe(getattr(value, field.name)) for field in fields(value)}

    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    if isinstance(value, (set, frozenset)):
        items = [json_safe(item) for item in value]
        try:
            return sorted(items)
        except TypeError:
            return sorted(
                items,
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, allow_nan=False
                ),
            )

    if isinstance(value, bool):
        return value

    if isinstance(value, Integral):
        return int(value)

    if isinstance(value, Real):
        try:
            if not math.isfinite(value):
                return str(value)
            return float(value)
        except OverflowError:
            return str(value)

    return value


def write_json_report(report: Any, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return output_path
