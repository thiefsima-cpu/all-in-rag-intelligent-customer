"""Enforce package and risk-module coverage policy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.coverage_policy.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
