"""Console process helpers shared by executable entrypoints."""

from __future__ import annotations

import sys
from typing import Any


def _configure_stream(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="backslashreplace")


def configure_utf8_stdio(*, stdout=None, stderr=None) -> None:
    """Use deterministic UTF-8 output on Windows and other locale-bound consoles."""

    _configure_stream(sys.stdout if stdout is None else stdout)
    _configure_stream(sys.stderr if stderr is None else stderr)


__all__ = ["configure_utf8_stdio"]
