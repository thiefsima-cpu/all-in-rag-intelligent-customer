from __future__ import annotations

import tempfile
import unittest

from rag_modules.app.provider_components.diagnostics import DefaultDiagnosticsComponentProvider
from rag_modules.app.provider_components.infrastructure import (
    DefaultInfrastructureComponentProvider,
)
from rag_modules.artifacts import ArtifactManifestStore
from rag_modules.build_pipeline.document_artifacts import DocumentIndexCache
from rag_modules.configuration.testing import build_test_config
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.tracing_sinks import (
    AsyncQueryTraceSink,
    JsonlQueryTraceSinkFactory,
    NullQueryTraceSink,
)


class _CapturingSink:
    def __init__(self) -> None:
        self.events = []
        self.closed = False

    def write(self, event) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True


class _CapturingSinkFactory:
    def __init__(self, sink) -> None:
        self.sink = sink
        self.paths: list[str] = []

    def create(self, path: str):
        self.paths.append(path)
        return self.sink


class InfrastructureTraceProviderTests(unittest.TestCase):
    def test_provider_builds_query_tracer_from_sink_factory(self) -> None:
        sink = _CapturingSink()
        provider = DefaultInfrastructureComponentProvider(
            query_trace_sink_factory=_CapturingSinkFactory(sink)
        )
        config = build_test_config(
            {
                "observability": {
                    "enable_query_tracing": True,
                    "query_trace_path": "custom-trace.jsonl",
                }
            }
        )

        tracer = provider.provide_query_tracer(config)
        tracer.record(
            query="trace me",
            analysis=None,
            documents=[EvidenceDocument(content="doc")],
            latency_ms=1.5,
            answer="ok",
        )

        self.assertEqual(len(sink.events), 1)
        self.assertNotEqual(sink.events[0].query, "trace me")
        self.assertTrue(sink.events[0].query.startswith("sha256:"))

    def test_provider_returns_null_sink_when_tracing_disabled(self) -> None:
        sink = _CapturingSink()
        factory = _CapturingSinkFactory(sink)
        provider = DefaultInfrastructureComponentProvider(query_trace_sink_factory=factory)
        config = build_test_config(
            {
                "observability": {
                    "enable_query_tracing": False,
                    "query_trace_path": "ignored.jsonl",
                }
            }
        )

        trace_sink = provider.provide_query_trace_sink(config)

        self.assertIsInstance(trace_sink, NullQueryTraceSink)
        self.assertEqual(factory.paths, [])

    def test_jsonl_sink_factory_can_expose_async_sink_boundary(self) -> None:
        sink = JsonlQueryTraceSinkFactory(async_enabled=True, max_queue_size=4).create(
            "trace.jsonl"
        )

        self.assertIsInstance(sink, AsyncQueryTraceSink)
        sink.close()

    def test_provider_uses_configured_async_trace_sink_by_default(self) -> None:
        provider = DefaultInfrastructureComponentProvider()
        config = build_test_config(
            {
                "observability": {
                    "enable_query_tracing": True,
                    "query_trace_path": "async-trace.jsonl",
                    "query_trace_async_enabled": True,
                    "query_trace_max_queue_size": 8,
                }
            }
        )

        sink = provider.provide_query_trace_sink(config)

        self.assertIsInstance(sink, AsyncQueryTraceSink)
        sink.close()

    def test_provider_can_disable_async_trace_sink_from_config(self) -> None:
        provider = DefaultInfrastructureComponentProvider()
        config = build_test_config(
            {
                "observability": {
                    "enable_query_tracing": True,
                    "query_trace_path": "sync-trace.jsonl",
                    "query_trace_async_enabled": False,
                    "query_trace_max_queue_size": 0,
                }
            }
        )

        sink = provider.provide_query_trace_sink(config)

        self.assertNotIsInstance(sink, AsyncQueryTraceSink)
        sink.close()

    def test_provider_exposes_runtime_artifact_lifecycle_ports(self) -> None:
        provider = DefaultInfrastructureComponentProvider()
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "storage": {
                        "index_cache_dir": temp_dir,
                        "artifact_manifest_path": f"{temp_dir}/artifact_manifest.json",
                    }
                }
            )

            manifest_store = provider.provide_artifact_manifest_store(config)
            cache = provider.provide_document_artifact_cache(
                config,
                manifest_store=manifest_store,
            )
            runtime_artifact_access = provider.provide_runtime_artifact_access(config)

            self.assertIsInstance(manifest_store, ArtifactManifestStore)
            self.assertIsInstance(cache, DocumentIndexCache)
            self.assertIs(cache.manifest_store, manifest_store)
            self.assertTrue(callable(getattr(runtime_artifact_access, "load_graph_data", None)))
            self.assertTrue(
                callable(getattr(runtime_artifact_access, "has_vector_collection", None))
            )
            self.assertTrue(
                callable(getattr(runtime_artifact_access, "load_vector_collection", None))
            )
            self.assertTrue(callable(getattr(runtime_artifact_access, "build_vector_index", None)))
            self.assertTrue(
                callable(getattr(runtime_artifact_access, "delete_vector_collection", None))
            )

    def test_diagnostics_provider_exposes_runtime_stats_access(self) -> None:
        provider = DefaultDiagnosticsComponentProvider()

        stats_access = provider.provide_runtime_stats_access(config=build_test_config())

        self.assertTrue(callable(getattr(stats_access, "get_graph_data_stats", None)))
        self.assertTrue(callable(getattr(stats_access, "get_vector_collection_stats", None)))
        self.assertTrue(callable(getattr(stats_access, "get_route_stats", None)))
        self.assertTrue(callable(getattr(stats_access, "get_retrieval_runtime_profile", None)))


if __name__ == "__main__":
    unittest.main()
