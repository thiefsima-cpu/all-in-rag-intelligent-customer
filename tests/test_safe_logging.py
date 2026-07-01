from __future__ import annotations

import ast
import logging
import unittest
from pathlib import Path

from rag_modules.observability.tracing_sinks import AsyncQueryTraceSink
from rag_modules.retrieval.adapters.bm25_retriever import BM25Retriever
from rag_modules.runtime import QueryTraceEvent
from rag_modules.safe_logging import log_failure
from rag_modules.text_document import TextDocument

_LOGGER_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_FORBIDDEN_NAMES = {
    "access_token",
    "api_key",
    "authorization",
    "cookie",
    "e",
    "error",
    "exc",
    "fallback_exc",
    "password",
    "plan",
    "prompt",
    "query",
    "question",
    "secret",
    "text",
    "tokenized_query",
    "tokens",
    "constraints",
    "source_entities",
    "target_entities",
}


class _FailingTraceSink:
    def __init__(self, secret: str) -> None:
        self.secret = secret

    def write(self, event: QueryTraceEvent) -> None:
        del event
        raise RuntimeError(self.secret)

    def close(self) -> None:
        raise RuntimeError(self.secret)


class SafeLoggingTests(unittest.TestCase):
    def test_log_failure_omits_exception_message(self) -> None:
        logger = logging.getLogger("tests.safe_logging")
        secret = "provider-api-key-secret"

        with self.assertLogs(logger, level="ERROR") as captured:
            log_failure(
                logger,
                logging.ERROR,
                "answer_failed",
                code="ANSWER_FAILED",
                error=RuntimeError(secret),
                request_id="request-42",
            )

        output = "\n".join(captured.output)
        self.assertIn("ANSWER_FAILED", output)
        self.assertIn("RuntimeError", output)
        self.assertIn("request-42", output)
        self.assertNotIn(secret, output)

    def test_bm25_log_contains_counts_but_not_query_or_tokens(self) -> None:
        secret = "private_query_token_7281"
        retriever = BM25Retriever()
        retriever.build([TextDocument(content=secret, metadata={"recipe_name": "safe"})])

        with self.assertLogs(
            "rag_modules.retrieval.adapters.bm25_retriever",
            level="INFO",
        ) as captured:
            retriever.search(secret, top_k=1)

        output = "\n".join(captured.output)
        self.assertIn("returned=", output)
        self.assertNotIn(secret, output)
        self.assertNotIn("query_tokens", output)
        self.assertNotIn("private", output)

    def test_trace_sink_logs_exception_type_without_message(self) -> None:
        secret = "trace-sink-api-key"
        sink = AsyncQueryTraceSink(_FailingTraceSink(secret), max_queue_size=1)

        with self.assertLogs(
            "rag_modules.observability.tracing_sinks", level="WARNING"
        ) as captured:
            sink.write(QueryTraceEvent(query_id="safe", timestamp=1, query="private query"))
            sink.close()

        output = "\n".join(captured.output)
        self.assertIn("RuntimeError", output)
        self.assertNotIn(secret, output)

    def test_production_logger_calls_do_not_receive_sensitive_objects(self) -> None:
        violations: list[str] = []
        for path in Path("rag_modules").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "logger":
                    continue
                if node.func.attr not in _LOGGER_METHODS:
                    continue
                if node.func.attr == "exception":
                    violations.append(f"{path}:{node.lineno}: logger.exception")
                for argument in [*node.args[1:], *(item.value for item in node.keywords)]:
                    for child in ast.walk(argument):
                        name = ""
                        if isinstance(child, ast.Name):
                            name = child.id
                        elif isinstance(child, ast.Attribute):
                            name = child.attr
                        if name in _FORBIDDEN_NAMES:
                            violations.append(f"{path}:{node.lineno}: {name}")
        self.assertEqual([], sorted(set(violations)))


if __name__ == "__main__":
    unittest.main()
