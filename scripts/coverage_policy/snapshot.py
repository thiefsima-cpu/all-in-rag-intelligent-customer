from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from .models import CoverageCounts


class CoverageSnapshot:
    def __init__(self, files: Mapping[str, CoverageCounts]) -> None:
        self._files = dict(files)

    @classmethod
    def from_json(cls, path: Path) -> CoverageSnapshot:
        return cls.from_payload(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_payload(cls, payload: object) -> CoverageSnapshot:
        if not isinstance(payload, Mapping):
            raise ValueError("coverage report must contain a files mapping")
        raw_files = payload.get("files")
        if not isinstance(raw_files, Mapping):
            raise ValueError("coverage report must contain a files mapping")
        files: dict[str, CoverageCounts] = {}
        for filename, file_payload in raw_files.items():
            normalized = str(filename).replace("\\", "/")
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if normalized in files:
                raise ValueError(f"duplicate normalized coverage path: {normalized}")
            summary = _required_summary(file_payload, normalized)
            files[normalized] = _counts_from_summary(summary, normalized)
        return cls(files)

    def file_counts(self, path: str) -> CoverageCounts:
        try:
            return self._files[path]
        except KeyError as exc:
            raise ValueError(f"missing configured risk file in coverage report: {path}") from exc

    def package_counts(self, path: str) -> CoverageCounts:
        prefix = path.rstrip("/") + "/"
        matching = [counts for name, counts in self._files.items() if name.startswith(prefix)]
        if not matching:
            raise ValueError(f"coverage report contains no matching files for package: {path}")
        return CoverageCounts(
            covered_lines=sum(item.covered_lines for item in matching),
            num_statements=sum(item.num_statements for item in matching),
            covered_branches=sum(item.covered_branches for item in matching),
            num_branches=sum(item.num_branches for item in matching),
        )


def _required_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _required_summary(file_payload: object, filename: str) -> Mapping[str, object]:
    if not isinstance(file_payload, Mapping):
        raise ValueError(f"coverage file is missing a summary mapping: {filename}")
    summary = file_payload.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError(f"coverage file is missing a summary mapping: {filename}")
    return summary


def _counts_from_summary(summary: Mapping[str, object], filename: str) -> CoverageCounts:
    covered_lines = _required_non_negative_int(
        summary.get("covered_lines"), f"{filename}.covered_lines"
    )
    num_statements = _required_non_negative_int(
        summary.get("num_statements"), f"{filename}.num_statements"
    )
    covered_branches = _required_non_negative_int(
        summary.get("covered_branches"), f"{filename}.covered_branches"
    )
    num_branches = _required_non_negative_int(
        summary.get("num_branches"), f"{filename}.num_branches"
    )
    if covered_lines > num_statements:
        raise ValueError(f"{filename}.covered_lines cannot exceed num_statements")
    if covered_branches > num_branches:
        raise ValueError(f"{filename}.covered_branches cannot exceed num_branches")
    return CoverageCounts(
        covered_lines=covered_lines,
        num_statements=num_statements,
        covered_branches=covered_branches,
        num_branches=num_branches,
    )
