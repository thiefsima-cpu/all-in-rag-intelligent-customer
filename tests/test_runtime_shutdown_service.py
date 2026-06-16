from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.services.runtime_shutdown_service import RuntimeShutdownService


class _FakeClosable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class RuntimeShutdownServiceTests(unittest.TestCase):
    def test_close_shuts_down_serving_resources_and_build_service(self) -> None:
        query_tracer = _FakeClosable()
        traditional_retrieval = _FakeClosable()
        graph_rag_retrieval = _FakeClosable()
        knowledge_base_service = _FakeClosable()
        serving_runtime = SimpleNamespace(retrieval_engines_initialized=True)
        runtime = SimpleNamespace(
            serving_runtime=serving_runtime,
            infrastructure=SimpleNamespace(
                query_tracer=query_tracer,
                neo4j_manager=_FakeClosable(),
            ),
            retrieval=SimpleNamespace(
                traditional_retrieval=traditional_retrieval,
                graph_rag_retrieval=graph_rag_retrieval,
            ),
            services=SimpleNamespace(
                knowledge_base_service=knowledge_base_service,
            ),
        )

        RuntimeShutdownService().close(runtime=runtime)

        self.assertTrue(query_tracer.closed)
        self.assertTrue(traditional_retrieval.closed)
        self.assertTrue(graph_rag_retrieval.closed)
        self.assertTrue(knowledge_base_service.closed)
        self.assertFalse(runtime.infrastructure.neo4j_manager.closed)
        self.assertFalse(serving_runtime.retrieval_engines_initialized)

    def test_close_falls_back_to_neo4j_manager_when_build_service_missing(self) -> None:
        neo4j_manager = _FakeClosable()
        runtime = SimpleNamespace(
            serving_runtime=None,
            infrastructure=SimpleNamespace(
                query_tracer=None,
                neo4j_manager=neo4j_manager,
            ),
            retrieval=SimpleNamespace(
                traditional_retrieval=None,
                graph_rag_retrieval=None,
            ),
            services=SimpleNamespace(
                knowledge_base_service=None,
            ),
        )

        RuntimeShutdownService().close(runtime=runtime)

        self.assertTrue(neo4j_manager.closed)


if __name__ == "__main__":
    unittest.main()
