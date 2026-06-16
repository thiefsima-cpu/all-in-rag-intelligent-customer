"""Environment-backed configuration helpers."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Mapping


@dataclass(slots=True)
class EnvConfigSource:
    """Typed access helpers over environment variables."""

    environ: Mapping[str, str | None]

    def get_str(self, name: str, default: str = "") -> str:
        value = self.environ.get(name)
        return str(value) if value not in (None, "") else default

    def get_int(self, name: str, default: int) -> int:
        value = self.environ.get(name)
        return int(value) if value not in (None, "") else default

    def get_float(self, name: str, default: float) -> float:
        value = self.environ.get(name)
        return float(value) if value not in (None, "") else default

    def get_bool(self, name: str, default: bool) -> bool:
        value = self.environ.get(name)
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def get_first(self, *names: str) -> str | None:
        for name in names:
            value = self.environ.get(name)
            if value not in (None, ""):
                return str(value)
        return None

    def get_int_alias(self, *names: str, default: int) -> int:
        value = self.get_first(*names)
        return int(value) if value is not None else default

    def get_float_alias(self, *names: str, default: float) -> float:
        value = self.get_first(*names)
        return float(value) if value is not None else default

    def get_json_dict(self, name: str, default: Dict[str, List[str]]) -> Dict[str, List[str]]:
        value = self.environ.get(name)
        if value in (None, ""):
            return {key: list(items) for key, items in default.items()}
        try:
            parsed = json.loads(str(value))
        except json.JSONDecodeError:
            return {key: list(items) for key, items in default.items()}
        if not isinstance(parsed, dict):
            return {key: list(items) for key, items in default.items()}

        normalized: Dict[str, List[str]] = {}
        for key, items in parsed.items():
            if isinstance(items, list):
                normalized[str(key)] = [str(item).strip() for item in items if str(item).strip()]
        return normalized or {key: list(items) for key, items in default.items()}


def default_env_source() -> EnvConfigSource:
    return EnvConfigSource(environ=os.environ)
