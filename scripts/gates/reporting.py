from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import StrEnum
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
        return {json_safe(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe(item) for item in value]

    return value


def write_json_report(report: Any, path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path
