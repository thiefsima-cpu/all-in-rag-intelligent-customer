from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api.services import GraphRAGServingApiService
from rag_modules.interfaces.api.services.errors import SystemNotReadyError
from rag_modules.runtime.artifacts import (
    ARTIFACT_STAGE_READY,
    ArtifactManifest,
    ArtifactManifestStore,
)
from rag_modules.runtime.artifacts.registry import ArtifactRegistry

ROOT = Path(__file__).resolve().parents[1]


class _MinimalServingSystem:
    def __init__(self) -> None:
        self.config = build_test_config()
        self.system_ready = False
        self.serving_initialized = False
        self.initialize_serving_calls = 0

    def is_serving_initialized(self) -> bool:
        return self.serving_initialized

    def initialize_serving_runtime(self) -> None:
        self.initialize_serving_calls += 1
        self.serving_initialized = True

    def collect_startup_diagnostics(self, mode: str):
        class _Diagnostics:
            def to_dict(self) -> dict:
                return {
                    "mode": mode,
                    "system_ready": False,
                    "serving_initialized": False,
                }

        return _Diagnostics()

    def collect_system_stats(self) -> dict:
        return {"ready": self.system_ready}

    def close(self) -> None:
        return None


class ServingApiCollaboratorTests(unittest.TestCase):
    def test_service_wires_configured_serving_collaborators(self) -> None:
        from rag_modules.interfaces.api.services.serving_admission import (
            ServingAnswerAdmissionController,
        )
        from rag_modules.interfaces.api.services.serving_hot_refresh import (
            ServingHotRefreshCoordinator,
        )
        from rag_modules.interfaces.api.services.serving_readiness import (
            ServingRuntimeReadinessGuard,
        )
        from rag_modules.interfaces.api.services.serving_streams import ServingSseRunner

        config = build_test_config(
            {
                "api": {
                    "max_concurrent_answers": 3,
                    "answer_acquire_timeout_seconds": 0.05,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 7,
                    "serving_hot_refresh_enabled": False,
                    "serving_hot_refresh_interval_seconds": 0.5,
                }
            }
        )

        service = GraphRAGServingApiService(system=_MinimalServingSystem(), config=config)

        self.assertIsInstance(service._answer_admission, ServingAnswerAdmissionController)
        self.assertEqual(service._answer_admission.max_concurrent_answers, 3)
        self.assertEqual(service._answer_admission.acquire_timeout_seconds, 0.05)
        self.assertIsInstance(service._stream_runner, ServingSseRunner)
        self.assertEqual(service._stream_runner.max_workers, 2)
        self.assertEqual(service._stream_runner.queue_max_size, 7)
        self.assertIsInstance(service._hot_refresh, ServingHotRefreshCoordinator)
        self.assertFalse(service._hot_refresh.enabled)
        self.assertEqual(service._hot_refresh.interval_seconds, 0.5)
        self.assertIsInstance(service._runtime_readiness, ServingRuntimeReadinessGuard)

    def test_runtime_readiness_guard_initializes_and_reports_diagnostics(self) -> None:
        from rag_modules.interfaces.api.services.serving_readiness import (
            ServingRuntimeReadinessGuard,
        )

        system = _MinimalServingSystem()
        diagnostics = {"mode": "serve", "system_ready": False}

        def ensure_runtime_initialized(*, is_initialized, initializer) -> None:
            if not is_initialized():
                initializer()

        guard = ServingRuntimeReadinessGuard(
            system=system,
            ensure_runtime_initialized=ensure_runtime_initialized,
            collect_startup_diagnostics=lambda mode: diagnostics,
            mode="serve",
        )

        guard.ensure_initialized()

        self.assertTrue(system.serving_initialized)
        self.assertEqual(system.initialize_serving_calls, 1)
        with self.assertRaises(SystemNotReadyError) as raised:
            guard.raise_if_system_not_ready()
        self.assertEqual(raised.exception.diagnostics, diagnostics)

    def test_hot_refresh_coordinator_refreshes_new_active_manifest_and_invalidates_cache(
        self,
    ) -> None:
        from rag_modules.interfaces.api.services.serving_hot_refresh import (
            ServingHotRefreshCoordinator,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {"storage": {"artifact_manifest_path": str(Path(temp_dir) / "manifest.json")}}
            )
            store = ArtifactManifestStore(config)
            first = store.save(
                ArtifactManifest(stage=ARTIFACT_STAGE_READY, collection_name="recipes__blue")
            )

            class _RefreshSystem(_MinimalServingSystem):
                def __init__(self) -> None:
                    super().__init__()
                    self.config = config
                    self.artifact_manifest = store.load()
                    self.refresh_calls = 0

                def refresh_serving_runtime(self, progress=None, *, force: bool = True):
                    del progress, force
                    self.refresh_calls += 1
                    self.artifact_manifest = store.load()

            lifecycle_entries: list[str] = []
            cache_invalidations: list[str] = []

            @contextmanager
            def exclusive_runtime_operation():
                lifecycle_entries.append("entered")
                yield

            system = _RefreshSystem()
            coordinator = ServingHotRefreshCoordinator(
                system=system,
                artifact_registry=ArtifactRegistry(store),
                enabled=True,
                interval_seconds=60.0,
                exclusive_runtime_operation=exclusive_runtime_operation,
                invalidate_runtime_cache=lambda: cache_invalidations.append("invalidated"),
            )
            second = store.save(first.evolve(collection_name="recipes__green"))

            refreshed = coordinator.refresh_if_stale(force_check=True)

            self.assertTrue(refreshed)
            self.assertEqual(system.refresh_calls, 1)
            self.assertEqual(system.artifact_manifest.manifest_version, second.manifest_version)
            self.assertEqual(lifecycle_entries, ["entered"])
            self.assertEqual(cache_invalidations, ["invalidated"])

    def test_manual_refresh_builds_operation_response_inside_lifecycle_lock(self) -> None:
        class _RefreshSystem(_MinimalServingSystem):
            def __init__(self) -> None:
                super().__init__()
                self.system_ready = True
                self.serving_initialized = True
                self.refresh_calls = 0

            def refresh_serving_runtime(self, progress=None, *, force: bool = True):
                del progress, force
                self.refresh_calls += 1

        service = GraphRAGServingApiService(system=_RefreshSystem())
        response_lifecycle_states: list[bool] = []

        def observed_operation_response(*, message: str, mode: str) -> dict:
            del message, mode
            response_lifecycle_states.append(service._locks.lifecycle_active())
            return {"ok": True}

        service._operation_response = observed_operation_response

        self.assertEqual(service.refresh_serving_runtime(), {"ok": True})
        self.assertEqual(response_lifecycle_states, [True])

    def test_serving_api_service_delegates_low_level_collaborators(self) -> None:
        source = (
            ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving.py"
        ).read_text(encoding="utf-8")

        self.assertIn("ServingAnswerAdmissionController", source)
        self.assertIn("ServingSseRunner", source)
        self.assertIn("ServingHotRefreshCoordinator", source)
        self.assertIn("ServingRuntimeReadinessGuard", source)
        self.assertNotIn("ThreadPoolExecutor", source)
        self.assertNotIn("queue.Queue", source)
        self.assertNotIn("BoundedSemaphore", source)
        self.assertNotIn("time.monotonic", source)


if __name__ == "__main__":
    unittest.main()
