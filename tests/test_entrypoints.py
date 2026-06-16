from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import main
import main_build_service

ROOT = Path(__file__).resolve().parents[1]


class _ReconfigurableStream:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def reconfigure(self, **kwargs) -> None:
        self.calls.append(dict(kwargs))


class EntrypointTests(unittest.TestCase):
    def test_runtime_entrypoints_are_api_only(self) -> None:
        self.assertEqual(
            {path.name for path in ROOT.glob("main*.py")},
            {"main.py", "main_build_service.py"},
        )

    def test_console_runtime_configures_stdout_and_stderr_as_utf8(self) -> None:
        from rag_modules.interfaces.console_runtime import configure_utf8_stdio

        stdout = _ReconfigurableStream()
        stderr = _ReconfigurableStream()

        configure_utf8_stdio(stdout=stdout, stderr=stderr)

        self.assertEqual(stdout.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])
        self.assertEqual(stderr.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}])

    def test_serving_entrypoint_returns_nonzero_when_uvicorn_fails(self) -> None:
        with patch("uvicorn.run", side_effect=RuntimeError("boom")):
            exit_code = main.main()

        self.assertEqual(exit_code, 1)

    def test_build_entrypoint_returns_nonzero_when_uvicorn_fails(self) -> None:
        with patch("uvicorn.run", side_effect=RuntimeError("boom")):
            exit_code = main_build_service.main()

        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
