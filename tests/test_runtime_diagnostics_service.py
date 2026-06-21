from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.diagnostics import StartupDiagnostics, SystemStatsDiagnostics
from rag_modules.app.services.runtime_diagnostics_service import RuntimeDiagnosticsService
from rag_modules.artifacts import ARTIFACT_HEALTH_READY, ArtifactManifest
from rag_modules.configuration.testing import build_test_config


class _FakeRuntimeStatsAccess:
    def __init__(self) -> None:
        self.graph_stats_calls = 0
        self.vector_stats_calls = 0
        self.route_stats_calls = 0
        self.profile_calls = 0
        self.trace_stats_calls = 0

    def get_graph_data_stats(self, data_module):
        self.graph_stats_calls += 1
        return dict(getattr(data_module, "stats", {}) or {})

    def get_vector_collection_stats(self, index_module):
        self.vector_stats_calls += 1
        return dict(getattr(index_module, "stats", {}) or {})

    def get_route_stats(self, routing_workflow):
        self.route_stats_calls += 1
        return dict(routing_workflow.get_route_statistics() or {})

    def get_retrieval_runtime_profile(self, retrieval_runtime_profile):
        self.profile_calls += 1
        return dict(retrieval_runtime_profile.to_dict() or {})

    def get_query_trace_stats(self, query_tracer):
        self.trace_stats_calls += 1
        stats = getattr(query_tracer, "stats", None)
        if callable(stats):
            return dict(stats() or {})
        return {}


class RuntimeDiagnosticsServiceTests(unittest.TestCase):
    def test_collect_system_stats_uses_runtime_stats_access(self) -> None:
        runtime_stats_access = _FakeRuntimeStatsAccess()
        service = RuntimeDiagnosticsService(
            build_test_config(),
            runtime_stats_access=runtime_stats_access,
        )
        manifest = ArtifactManifest(
            stage="ready",
            manifest_path="storage/indexes/artifact_manifest.json",
            total_documents=2,
            total_chunks=4,
            vector_rows=4,
            build_metadata={
                "config_profile": {
                    "name": "eval_fast",
                    "path": "profiles/eval_fast.toml",
                    "hash": "abc123",
                }
            },
        )
        runtime = SimpleNamespace(
            is_initialized=lambda: True,
            artifacts_ready=True,
            system_ready=True,
            artifact_manifest=manifest,
            serving_runtime=SimpleNamespace(retrieval_engines_initialized=True),
            infrastructure=SimpleNamespace(
                query_tracer=SimpleNamespace(
                    stats=lambda: {"dropped_events": 2, "queued_events": 1, "async_enabled": True}
                ),
                data_module=SimpleNamespace(stats={"total_recipes": 2, "total_chunks": 4}),
                index_module=SimpleNamespace(stats={"row_count": 4}),
            ),
            retrieval=SimpleNamespace(
                routing_workflow=SimpleNamespace(get_route_statistics=lambda: {"total_queries": 3}),
                retrieval_runtime_profile=SimpleNamespace(
                    to_dict=lambda: {"planner": {"max_candidates": 8}}
                ),
            ),
        )

        stats = service.collect_system_stats(
            runtime=runtime,
            build_initialized=True,
            serving_initialized=True,
        )

        self.assertIsInstance(stats, SystemStatsDiagnostics)
        self.assertEqual(runtime_stats_access.graph_stats_calls, 1)
        self.assertEqual(runtime_stats_access.vector_stats_calls, 1)
        self.assertEqual(runtime_stats_access.route_stats_calls, 1)
        self.assertEqual(runtime_stats_access.profile_calls, 1)
        self.assertEqual(runtime_stats_access.trace_stats_calls, 1)
        self.assertEqual(stats.data_stats["total_recipes"], 2)
        self.assertEqual(stats.index_stats["row_count"], 4)
        self.assertEqual(stats.route_stats["total_queries"], 3)
        self.assertEqual(stats.trace_stats["dropped_events"], 2)
        self.assertEqual(stats.manifest.stage, "ready")
        self.assertEqual(stats.manifest.health, ARTIFACT_HEALTH_READY)
        self.assertEqual(
            stats.manifest.build_metadata["config_profile"]["name"],
            "eval_fast",
        )

    def test_collect_startup_diagnostics_returns_typed_snapshot(self) -> None:
        service = RuntimeDiagnosticsService(build_test_config())
        manifest = ArtifactManifest(
            stage="ready",
            manifest_path="storage/indexes/artifact_manifest.json",
            vector_rows=6,
        )
        runtime = SimpleNamespace(
            artifacts_ready=True,
            system_ready=True,
            artifact_manifest=manifest,
            infrastructure=SimpleNamespace(
                query_tracer=SimpleNamespace(
                    stats=lambda: {"dropped_events": 0, "queued_events": 0, "async_enabled": True}
                )
            ),
            serving_runtime=SimpleNamespace(retrieval_engines_initialized=True),
        )

        diagnostics = service.collect_startup_diagnostics(
            mode="serve",
            runtime=runtime,
            build_initialized=True,
            serving_initialized=True,
        )

        self.assertIsInstance(diagnostics, StartupDiagnostics)
        self.assertEqual(diagnostics.mode, "serve")
        self.assertTrue(diagnostics.retrieval_engines_initialized)
        self.assertEqual(diagnostics.trace_stats["dropped_events"], 0)
        self.assertEqual(diagnostics.manifest.vector_rows, 6)
        self.assertEqual(diagnostics.manifest.health, ARTIFACT_HEALTH_READY)


if __name__ == "__main__":
    unittest.main()
