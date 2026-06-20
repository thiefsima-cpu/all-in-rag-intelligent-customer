"""Audit repository text files for UTF-8 decoding issues and mojibake markers."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List


DEFAULT_TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".csv",
    ".env",
    ".example",
    ".cypher",
}

DEFAULT_NAMES = {
    ".env",
    ".env.example",
    "Dockerfile",
    "docker-compose.yml",
}

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
}

MOJIBAKE_TOKENS = [
    "鍏崇",
    "鑿滆氨",
    "渚濇嵁",
    "楹昏荆",
    "涓轰粈涔",
    "鏃堕棿",
    "鍙ｆ劅",
    "椋庡懗",
    "鎺ㄨ崘",
    "鍥捐氨",
    "鐭ヨ瘑瀛愬浘",
]

ALLOWLISTED_MOJIBAKE_PATHS = {
    "scripts/check_encoding.py",
    "tests/test_eval_queries.py",
    "tests/test_query_policy.py",
}


@dataclass
class AuditIssue:
    path: str
    kind: str
    line: int = 0
    detail: str = ""


@dataclass
class AuditReport:
    scanned_files: int = 0
    issues: List[AuditIssue] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    def to_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "issues": [asdict(issue) for issue in self.issues],
        }


def is_text_candidate(path: Path) -> bool:
    if path.name in DEFAULT_NAMES:
        return True
    if path.suffix.lower() in DEFAULT_TEXT_SUFFIXES:
        return True
    return False


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        if is_text_candidate(path):
            yield path


def audit_file(path: Path, root: Path) -> List[AuditIssue]:
    issues: List[AuditIssue] = []
    relative_path = path.relative_to(root).as_posix()
    allowlisted_tokens = relative_path in ALLOWLISTED_MOJIBAKE_PATHS
    raw = path.read_bytes()

    if b"\x00" in raw:
        return issues

    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(AuditIssue(path=relative_path, kind="utf8_bom", detail="UTF-8 BOM present"))

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        issues.append(
            AuditIssue(
                path=relative_path,
                kind="decode_error",
                detail=f"UTF-8 decode failed at byte {exc.start}: {exc.reason}",
            )
        )
        return issues

    for line_no, line in enumerate(text.splitlines(), start=1):
        if "\ufffd" in line:
            issues.append(
                AuditIssue(
                    path=relative_path,
                    kind="replacement_char",
                    line=line_no,
                    detail=line.strip()[:160],
                )
            )
        for token in MOJIBAKE_TOKENS:
            if token in line and not allowlisted_tokens:
                issues.append(
                    AuditIssue(
                        path=relative_path,
                        kind="mojibake",
                        line=line_no,
                        detail=line.strip()[:160],
                    )
                )
                break

    return issues


def run_audit(root: Path) -> AuditReport:
    report = AuditReport()
    for path in iter_text_files(root):
        report.scanned_files += 1
        report.issues.extend(audit_file(path, root))
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Audit repository text files for UTF-8 and mojibake issues."
    )
    parser.add_argument("--root", default=".", help="Repository root to scan.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of plain text.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = run_audit(root)

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Scanned files: {report.scanned_files}")
        if not report.issues:
            print("No UTF-8 or mojibake issues found.")
        else:
            for issue in report.issues:
                location = f"{issue.path}:{issue.line}" if issue.line else issue.path
                print(f"[{issue.kind}] {location} {issue.detail}")

    return 1 if report.has_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
