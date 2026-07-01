from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.composition import (
    BuildRuntimeLifecycleService,
    RuntimeInitializationService,
    RuntimeLifecycleServiceBundle,
    RuntimeLifecycleServiceComposer,
    RuntimeReadinessService,
    ServingRuntimeLifecycleService,
    SystemRuntimeManager,
)
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.services.runtime_diagnostics_service import RuntimeDiagnosticsService
from rag_modules.app.services.runtime_shutdown_service import RuntimeShutdownService
from rag_modules.configuration.testing import build_test_config
from rag_modules.runtime.artifacts import ArtifactManifest


class _FakeBuildBootstrapper:
    def __init__(self, runtime: BuildRuntime) -> None:
        self.runtime = runtime
        self.build_calls = 0
        self.build_knowledge_base_calls = 0
        self.rebuild_knowledge_base_calls = 0

    def build(self, config=None, **kwargs) -> BuildRuntime:
        del config, kwargs
        self.build_calls += 1
        return self.runtime

    def build_knowledge_base(self, runtime: BuildRuntime, *, progress=None) -> BuildRuntime:
        del progress
        self.build_knowledge_base_calls += 1
        return runtime

    def rebuild_knowledge_base(self, runtime: BuildRuntime, *, progress=None) -> BuildRuntime:
        del progress
        self.rebuild_knowledge_base_calls += 1
        return runtime


class _FakeServingBootstrapper:
    def __init__(self, runtime: ServingRuntime) -> None:
        self.runtime = runtime
        self.build_calls = 0
        self.prepare_calls: list[dict] = []

    def build(self, config=None, **kwargs) -> ServingRuntime:
        del config, kwargs
        self.build_calls += 1
        return self.runtime

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress=None,
        force: bool = False,
    ) -> ServingRuntime:
        del progress
        self.prepare_calls.append(
            {
                "runtime": runtime,
                "shared_runtime": shared_runtime,
                "force": force,
            }
        )
        if shared_runtime is not None:
            runtime.artifact_manifest = shared_runtime.artifact_manifest
        runtime.retrieval_engines_initialized = True
        return runtime


def _ready_manifest() -> ArtifactManifest:
    return ArtifactManifest(
        stage="ready",
        manifest_path="storage/indexes/artifact_manifest.json",
        total_documents=2,
        total_chunks=4,
        vector_rows=4,
    )


def _build_runtime() -> BuildRuntime:
    return BuildRuntime(
        config=build_test_config(),
        neo4j_manager=SimpleNamespace(),
        data_module=SimpleNamespace(chunks=[SimpleNamespace(content="c1")]),
        index_module=SimpleNamespace(),
        knowledge_base_service=SimpleNamespace(),
        artifact_manifest=_ready_manifest(),
    )


def _serving_runtime(*, ready: bool = False) -> ServingRuntime:
    return ServingRuntime(
        config=build_test_config(),
        neo4j_manager=SimpleNamespace(),
        data_module=SimpleNamespace(),
        index_module=SimpleNamespace(),
        query_tracer=SimpleNamespace(),
        generation_module=SimpleNamespace(),
        retrieval_runtime_profile=SimpleNamespace(),
        query_understanding_service=SimpleNamespace(),
        traditional_retrieval=SimpleNamespace(),
        graph_rag_retrieval=SimpleNamespace(),
        query_router=SimpleNamespace(),
        answer_workflow=SimpleNamespace(),
        artifact_manifest=_ready_manifest()
        if ready
        else ArtifactManifest.missing(manifest_path="storage/indexes/artifact_manifest.json"),
        retrieval_engines_initialized=ready,
    )


class RuntimeLifecycleServiceTests(unittest.TestCase):
    def test_initialization_service_reuses_initialized_build_runtime(self) -> None:
        build_runtime = _build_runtime()
        service = RuntimeInitializationService(
            config=build_test_config(),
            build_runtime_factory=_FakeBuildBootstrapper(build_runtime),
            serving_runtime_lifecycle_service=ServingRuntimeLifecycleService(
                serving_runtime_factory=_FakeServingBootstrapper(_serving_runtime()),
                serving_runtime_preparer=_FakeServingBootstrapper(_serving_runtime()),
            ),
        )

        result = service.initialize_build_runtime(build_runtime)

        self.assertIs(result, build_runtime)
        self.assertEqual(service.build_runtime_factory.build_calls, 0)

    def test_lifecycle_service_composer_adapts_bootstrappers(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime()
        composer = RuntimeLifecycleServiceComposer()

        components = composer.adapt_bootstrappers(
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertTrue(callable(getattr(components.build_runtime_factory, "build", None)))
        self.assertTrue(
            callable(getattr(components.build_runtime_executor, "build_knowledge_base", None))
        )
        self.assertTrue(callable(getattr(components.serving_runtime_factory, "build", None)))
        self.assertTrue(
            callable(
                getattr(
                    components.serving_runtime_preparer,
                    "prepare_with_shared_runtime",
                    None,
                )
            )
        )
        self.assertIsInstance(
            components.serving_runtime_lifecycle_service,
            ServingRuntimeLifecycleService,
        )

    def test_lifecycle_service_composer_composes_default_bundle(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime()
        composer = RuntimeLifecycleServiceComposer()

        bundle = composer.compose(
            config=build_test_config(),
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertIsInstance(bundle, RuntimeLifecycleServiceBundle)
        self.assertIsInstance(bundle.initialization_service, RuntimeInitializationService)
        self.assertIsInstance(bundle.readiness_service, RuntimeReadinessService)
        self.assertIsInstance(bundle.serving_lifecycle_service, ServingRuntimeLifecycleService)
        self.assertIsInstance(bundle.build_lifecycle_service, BuildRuntimeLifecycleService)

    def test_initialization_service_prepares_existing_serving_runtime(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime()
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        serving_lifecycle_service = ServingRuntimeLifecycleService(
            serving_runtime_factory=serving_bootstrapper,
            serving_runtime_preparer=serving_bootstrapper,
        )
        service = RuntimeInitializationService(
            config=build_test_config(),
            build_runtime_factory=_FakeBuildBootstrapper(build_runtime),
            serving_runtime_lifecycle_service=serving_lifecycle_service,
        )

        result = service.initialize_serving_runtime(
            serving_runtime,
            build_runtime=build_runtime,
        )

        self.assertIs(result, serving_runtime)
        self.assertEqual(
            service.serving_runtime_lifecycle_service.serving_runtime_factory.build_calls,
            0,
        )
        self.assertEqual(
            len(service.serving_runtime_lifecycle_service.serving_runtime_factory.prepare_calls),
            1,
        )

    def test_initialization_service_builds_and_prepares_new_serving_runtime(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=False)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        service = RuntimeInitializationService(
            config=build_test_config(),
            build_runtime_factory=_FakeBuildBootstrapper(build_runtime),
            serving_runtime_lifecycle_service=ServingRuntimeLifecycleService(
                serving_runtime_factory=serving_bootstrapper,
                serving_runtime_preparer=serving_bootstrapper,
            ),
        )

        result = service.initialize_serving_runtime(
            None,
            build_runtime=build_runtime,
        )

        self.assertIs(result, serving_runtime)
        self.assertEqual(serving_bootstrapper.build_calls, 1)
        self.assertEqual(len(serving_bootstrapper.prepare_calls), 1)
        self.assertTrue(result.retrieval_engines_initialized)

    def test_serving_lifecycle_refreshes_initialized_serving_runtime_from_build(
        self,
    ) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        service = ServingRuntimeLifecycleService(
            serving_runtime_factory=serving_bootstrapper,
            serving_runtime_preparer=serving_bootstrapper,
        )

        result = service.refresh_from_build(
            serving_runtime,
            build_runtime=build_runtime,
            force=True,
        )

        self.assertIs(result, serving_runtime)
        self.assertEqual(len(serving_bootstrapper.prepare_calls), 1)
        self.assertTrue(serving_bootstrapper.prepare_calls[0]["force"])

    def test_readiness_service_validates_artifact_and_system_readiness(self) -> None:
        service = RuntimeReadinessService()
        serving_runtime = _serving_runtime(ready=False)

        with self.assertRaisesRegex(ValueError, "Serving artifacts are not ready"):
            service.require_ready(serving_runtime, artifacts_ready=False)

    def test_build_lifecycle_service_builds_and_refreshes_serving_runtime(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        build_bootstrapper = _FakeBuildBootstrapper(build_runtime)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        serving_lifecycle_service = ServingRuntimeLifecycleService(
            serving_runtime_factory=serving_bootstrapper,
            serving_runtime_preparer=serving_bootstrapper,
        )
        readiness_service = RuntimeReadinessService()
        service = BuildRuntimeLifecycleService(
            build_runtime_executor=build_bootstrapper,
            serving_lifecycle_service=serving_lifecycle_service,
            readiness_service=readiness_service,
        )

        result_build, result_serving = service.build_knowledge_base(
            build_runtime,
            serving_runtime=serving_runtime,
        )

        self.assertIs(result_build, build_runtime)
        self.assertIs(result_serving, serving_runtime)
        self.assertEqual(build_bootstrapper.build_knowledge_base_calls, 1)
        self.assertEqual(
            len(serving_lifecycle_service.serving_runtime_factory.prepare_calls),
            1,
        )
        self.assertTrue(serving_lifecycle_service.serving_runtime_factory.prepare_calls[0]["force"])

    def test_build_lifecycle_service_rebuilds_and_refreshes_serving_runtime(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        build_bootstrapper = _FakeBuildBootstrapper(build_runtime)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        serving_lifecycle_service = ServingRuntimeLifecycleService(
            serving_runtime_factory=serving_bootstrapper,
            serving_runtime_preparer=serving_bootstrapper,
        )
        service = BuildRuntimeLifecycleService(
            build_runtime_executor=build_bootstrapper,
            serving_lifecycle_service=serving_lifecycle_service,
            readiness_service=RuntimeReadinessService(),
        )

        result_build, result_serving = service.rebuild_knowledge_base(
            build_runtime,
            serving_runtime=serving_runtime,
        )

        self.assertIs(result_build, build_runtime)
        self.assertIs(result_serving, serving_runtime)
        self.assertEqual(build_bootstrapper.rebuild_knowledge_base_calls, 1)
        self.assertEqual(
            len(serving_lifecycle_service.serving_runtime_factory.prepare_calls),
            1,
        )
        self.assertTrue(serving_lifecycle_service.serving_runtime_factory.prepare_calls[0]["force"])

    def test_runtime_manager_delegates_to_injected_services(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        calls: list[str] = []

        class _StubInitializationService:
            def initialize_build_runtime(self, current_runtime, **kwargs):
                del current_runtime, kwargs
                calls.append("build-init")
                return build_runtime

            def initialize_serving_runtime(self, current_runtime, **kwargs):
                del current_runtime, kwargs
                calls.append("serving-init")
                return serving_runtime

            def initialize_system(self, **kwargs):
                del kwargs
                calls.append("system-init")
                return build_runtime, serving_runtime

        class _StubServingLifecycleService:
            def prepare_existing(self, runtime, **kwargs):
                del kwargs
                calls.append("prepare-existing")
                return runtime

        class _StubReadinessService:
            def require_build_runtime(self, runtime):
                calls.append("require-build")
                return runtime

            def require_serving_runtime(self, runtime):
                calls.append("require-serving")
                return runtime

            def require_ready(self, runtime, *, artifacts_ready):
                del artifacts_ready
                calls.append("require-ready")
                return runtime

            def is_build_initialized(self, runtime):
                del runtime
                calls.append("is-build")
                return True

            def is_serving_initialized(self, runtime):
                del runtime
                calls.append("is-serving")
                return True

        class _StubBuildLifecycleService:
            def build_knowledge_base(self, build_runtime_arg, **kwargs):
                del kwargs
                calls.append("build-lifecycle")
                return build_runtime_arg, serving_runtime

            def rebuild_knowledge_base(self, build_runtime_arg, **kwargs):
                del kwargs
                calls.append("rebuild-lifecycle")
                return build_runtime_arg, serving_runtime

        lifecycle_bundle = RuntimeLifecycleServiceBundle(
            initialization_service=_StubInitializationService(),
            readiness_service=_StubReadinessService(),
            serving_lifecycle_service=_StubServingLifecycleService(),
            build_lifecycle_service=_StubBuildLifecycleService(),
        )
        manager = SystemRuntimeManager(
            config=build_test_config(),
            diagnostics_service=RuntimeDiagnosticsService(build_test_config()),
            shutdown_service=RuntimeShutdownService(),
            lifecycle_services=lifecycle_bundle,
        )

        manager.build_runtime = build_runtime
        manager.initialize_system()
        manager.prepare_existing_serving_runtime()
        manager.build_knowledge_base()
        manager.rebuild_knowledge_base()
        manager.require_ready()

        self.assertEqual(
            calls,
            [
                "system-init",
                "prepare-existing",
                "build-lifecycle",
                "rebuild-lifecycle",
                "require-ready",
            ],
        )

    def test_runtime_manager_can_consume_precomposed_lifecycle_bundle(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        lifecycle_bundle = RuntimeLifecycleServiceBundle(
            initialization_service=SimpleNamespace(
                initialize_build_runtime=lambda current_runtime, **kw: build_runtime,
                initialize_serving_runtime=lambda current_runtime, **kw: serving_runtime,
                initialize_system=lambda **kw: (build_runtime, serving_runtime),
            ),
            readiness_service=RuntimeReadinessService(),
            serving_lifecycle_service=SimpleNamespace(
                prepare_existing=lambda runtime, **kw: runtime,
            ),
            build_lifecycle_service=SimpleNamespace(
                build_knowledge_base=lambda runtime, **kw: (runtime, serving_runtime),
                rebuild_knowledge_base=lambda runtime, **kw: (runtime, serving_runtime),
            ),
        )

        manager = SystemRuntimeManager(
            config=build_test_config(),
            diagnostics_service=RuntimeDiagnosticsService(build_test_config()),
            shutdown_service=RuntimeShutdownService(),
            lifecycle_services=lifecycle_bundle,
        )

        self.assertIs(manager.initialization_service, lifecycle_bundle.initialization_service)
        self.assertIs(manager.readiness_service, lifecycle_bundle.readiness_service)
        self.assertIs(
            manager.serving_lifecycle_service,
            lifecycle_bundle.serving_lifecycle_service,
        )
        self.assertIs(manager.build_lifecycle_service, lifecycle_bundle.build_lifecycle_service)

    def test_runtime_manager_close_clears_runtime_state_store(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(ready=True)
        manager = SystemRuntimeManager(
            config=build_test_config(),
            diagnostics_service=RuntimeDiagnosticsService(build_test_config()),
            shutdown_service=RuntimeShutdownService(),
            lifecycle_services=RuntimeLifecycleServiceBundle(
                initialization_service=SimpleNamespace(),
                readiness_service=RuntimeReadinessService(),
                serving_lifecycle_service=SimpleNamespace(),
                build_lifecycle_service=SimpleNamespace(),
            ),
        )
        manager.build_runtime = build_runtime
        manager.serving_runtime = serving_runtime

        manager.close()

        self.assertFalse(manager.is_initialized())
        self.assertIsNone(manager.build_runtime)
        self.assertIsNone(manager.serving_runtime)
        self.assertFalse(manager.artifacts_ready)
        self.assertFalse(manager.system_ready)


if __name__ == "__main__":
    unittest.main()
