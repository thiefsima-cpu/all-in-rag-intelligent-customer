"""Profile-based configuration override loading."""

from __future__ import annotations

import hashlib
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .assembly import apply_overrides, build_config_from_domain_dict
from .models import default_domain_payload


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_profiles_dir() -> Path:
    return _repo_root() / "profiles"


@dataclass(frozen=True, slots=True)
class ConfigProfile:
    """Resolved profile metadata and overrides."""

    name: str = ""
    path: str = ""
    profile_hash: str = ""
    overrides: dict[str, Any] | None = None
    loaded_files: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "hash": self.profile_hash,
            "loaded_files": list(self.loaded_files),
        }


def _merge_nested(target: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        key_text = str(key)
        if isinstance(value, Mapping):
            child = target.get(key_text)
            if not isinstance(child, dict):
                child = {}
                target[key_text] = child
            _merge_nested(child, value)
        else:
            target[key_text] = value
    return target


def _read_profile_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Profile at {path} must decode to a TOML table.")
    result = dict(payload)
    _validate_profile_payload(path, result)
    return result


def _validate_profile_payload(path: Path, payload: Mapping[str, Any]) -> None:
    domain_payload = default_domain_payload()
    apply_overrides(domain_payload, payload)
    build_config_from_domain_dict(
        domain_payload,
        source_kind="profile",
        source=str(path),
    )


def _profile_path(*, profile: str, profiles_dir: Path) -> Path:
    profile_name = str(profile or "").strip()
    if not profile_name:
        raise ValueError("Profile name must not be empty.")
    return profiles_dir / f"{profile_name}.toml"


def load_profile(
    *,
    profile: str | None = None,
    profile_path: str | Path | None = None,
    profiles_dir: str | Path | None = None,
) -> ConfigProfile:
    resolved_profiles_dir = (
        Path(profiles_dir) if profiles_dir is not None else default_profiles_dir()
    )
    merged: dict[str, Any] = {}
    loaded_files: list[str] = []
    selected_name = str(profile or "").strip()
    selected_path = Path(profile_path).resolve() if profile_path is not None else None

    base_path = (resolved_profiles_dir / "base.toml").resolve()
    if base_path.exists():
        _merge_nested(merged, _read_profile_file(base_path))
        loaded_files.append(str(base_path))

    if selected_path is None and selected_name:
        selected_path = _profile_path(
            profile=selected_name, profiles_dir=resolved_profiles_dir
        ).resolve()

    if selected_path is not None:
        if not selected_path.exists():
            raise FileNotFoundError(f"Config profile not found: {selected_path}")
        if str(selected_path) != str(base_path):
            _merge_nested(merged, _read_profile_file(selected_path))
            loaded_files.append(str(selected_path))
        if not selected_name:
            selected_name = selected_path.stem

    profile_hash = ""
    if merged:
        profile_hash = hashlib.sha256(
            json.dumps(merged, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    profile_display_path = selected_path or (base_path if loaded_files else None)
    return ConfigProfile(
        name=selected_name or ("base" if loaded_files else ""),
        path=str(profile_display_path or ""),
        profile_hash=profile_hash,
        overrides=merged or {},
        loaded_files=tuple(loaded_files),
    )


__all__ = ["ConfigProfile", "default_profiles_dir", "load_profile"]
