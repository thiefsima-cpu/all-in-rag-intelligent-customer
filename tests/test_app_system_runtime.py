from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.bootstrap import BuildBootstrapper, ServingBootstrapper
from rag_modules.app.composition import (
    AdvancedGraphRAGBootstrapperSurface,
    AdvancedGraphRAGSystemComponents,
    AdvancedGraphRAGSystemComposer,
    RuntimeComponentProviderResolver,
    SystemApplicationServiceComposer,
    SystemBootstrapperSurfaceComposer,
    RuntimeLifecycleServiceBundle,
    RuntimeProviderSurface,
    RuntimeProviderSurfaceResolver,
    RuntimeReadinessService,
    RuntimeStateStore,
    SystemAnsweringService,
    SystemFacadeSupport,
    SystemOperationsService,
    SystemRuntimeInfrastructureComposer,
)
from rag_modules.app.provider_components.generation import DefaultGenerationComponentProvider
from rag_modules.app.provider_components.query_understanding import (
    DefaultQueryUnderstandingComponentProvider,
)
from rag_modules.app.provider_components.runtime import DefaultRuntimeComponentProvider
from rag_modules.app.services.runtime_diagnostics_service import RuntimeDiagnosticsService
from rag_modules.app.services.runtime_shutdown_service import RuntimeShutdownService
from rag_modules.app.runtime_state import BuildRuntime, ServingRuntime
from rag_modules.app.runtime_view import (
    SystemInfrastructureView,
    SystemRetrievalView,
    SystemServicesView,
)
from rag_modules.app.services.answer_models import QuestionAnswerResult
from rag_modules.app.services.question_answer_service import QuestionAnswerService
from rag_modules.app.system import AdvancedGraphRAGSystem
from rag_modules.artifacts import ArtifactManifest
from rag_modules.configuration.testing import build_test_config
from rag_modules.generation.service import GenerationWorkflowService
from rag_modules.query_understanding.service import QueryUnderstandingService
from rag_modules.retrieval.runtime_profile import RetrievalRuntimeProfile


class _FakeClosable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeKnowledgeBaseService(_FakeClosable):
    def __init__(self, manifest: ArtifactManifest) -> None:
        super().__init__()
        self.artifact_manifest = manifest
        self.build_calls = 0
        self.rebuild_calls = 0

    def build(self, progress=None) -> None:
        self.build_calls += 1
        if progress:
            progress("build-called")
        self.artifact_manifest = self.artifact_manifest.evolve(stage="ready")

    def rebuild(self, progress=None) -> None:
        self.rebuild_calls += 1
        if progress:
            progress("rebuild-called")
        self.artifact_manifest = self.artifact_manifest.evolve(stage="ready")


class _FakeAnswerWorkflow:
    def answer_question(self, *args, **kwargs) -> QuestionAnswerResult:
        del args, kwargs
        return QuestionAnswerResult(answer="workflow-ok", analysis=None)

    def answer_question_response(self, *args, **kwargs):
        del args, kwargs
        return self.answer_question().to_response()


class _CountingRuntimeStateStore:
    def __init__(self, *, serving_runtime) -> None:
        self.serving_runtime = serving_runtime
        self.refresh_calls = 0

    def refresh(self):
        self.refresh_calls += 1
        return SimpleNamespace()


class _FakeBuildBootstrapper(BuildBootstrapper):
    def __init__(self, runtime: BuildRuntime):
        self.runtime = runtime
        self.build_calls = 0
        self.build_knowledge_base_calls = 0
        self.rebuild_knowledge_base_calls = 0

    def build(self, config=None, **kwargs) -> BuildRuntime:
        del config, kwargs
        self.build_calls += 1
        return self.runtime

    def build_knowledge_base(self, runtime: BuildRuntime, *, progress=None) -> BuildRuntime:
        self.build_knowledge_base_calls += 1
        runtime.knowledge_base_service.build(progress=progress)
        runtime.artifact_manifest = runtime.knowledge_base_service.artifact_manifest
        return runtime

    def rebuild_knowledge_base(self, runtime: BuildRuntime, *, progress=None) -> BuildRuntime:
        self.rebuild_knowledge_base_calls += 1
        runtime.knowledge_base_service.rebuild(progress=progress)
        runtime.artifact_manifest = runtime.knowledge_base_service.artifact_manifest
        return runtime


class _FakeServingBootstrapper(ServingBootstrapper):
    def __init__(self, runtime: ServingRuntime):
        self.runtime = runtime
        self.build_calls = 0
        self.prepare_calls: list[dict] = []

    def build(self, config=None, **kwargs) -> ServingRuntime:
        del config, kwargs
        self.build_calls += 1
        return self.runtime

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks=None,
        artifact_manifest=None,
        progress=None,
        force: bool = False,
    ) -> ServingRuntime:
        self.prepare_calls.append(
            {
                "runtime": runtime,
                "chunks": list(chunks or []),
                "artifact_manifest": artifact_manifest,
                "force": force,
            }
        )
        if artifact_manifest is not None:
            runtime.artifact_manifest = artifact_manifest
        runtime.retrieval_engines_initialized = True
        if progress:
            progress("prepare-called")
        return runtime

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress=None,
        force: bool = False,
    ) -> ServingRuntime:
        return self.prepare(
            runtime,
            chunks=shared_runtime.data_module.chunks if shared_runtime and shared_runtime.data_module else None,
            artifact_manifest=shared_runtime.artifact_manifest if shared_runtime else None,
            progress=progress,
            force=force,
        )


def _ready_manifest() -> ArtifactManifest:
    return ArtifactManifest(
        stage="ready",
        manifest_path="storage/indexes/artifact_manifest.json",
        documents_path="storage/indexes/documents.json",
        chunks_path="storage/indexes/chunks.json",
        collection_name="recipes",
        total_documents=2,
        total_chunks=4,
        vector_rows=4,
    )


def _build_runtime() -> BuildRuntime:
    manifest = _ready_manifest()
    data_module = SimpleNamespace(
        chunks=[SimpleNamespace(content="c1"), SimpleNamespace(content="c2")],
        get_statistics=lambda: {"total_recipes": 2, "total_chunks": 4},
    )
    return BuildRuntime(
        config=SimpleNamespace(
            models=SimpleNamespace(
                llm_model="qwen3.7-plus",
                embedding_model="qwen3-vl-embedding",
                rerank_model="qwen3-vl-rerank",
            ),
            observability=SimpleNamespace(
                enable_query_tracing=True,
                query_trace_path="trace.jsonl",
            ),
        ),
        neo4j_manager=SimpleNamespace(),
        data_module=data_module,
        index_module=SimpleNamespace(get_collection_stats=lambda: {"row_count": 4}),
        knowledge_base_service=_FakeKnowledgeBaseService(manifest),
        artifact_manifest=manifest,
    )


def _serving_runtime(config) -> ServingRuntime:
    answer_workflow = _FakeAnswerWorkflow()
    query_router = SimpleNamespace(get_route_statistics=lambda: {"total_queries": 0})
    generation_module = SimpleNamespace()
    query_tracer = _FakeClosable()
    question_answer_service = QuestionAnswerService(
        config=config,
        query_router=query_router,
        generation_module=generation_module,
        query_tracer=query_tracer,
        answer_workflow=answer_workflow,
    )
    return ServingRuntime(
        config=config,
        neo4j_manager=SimpleNamespace(close=lambda: None),
        data_module=SimpleNamespace(get_statistics=lambda: {"total_recipes": 2, "total_chunks": 4}),
        index_module=SimpleNamespace(get_collection_stats=lambda: {"row_count": 4}),
        query_tracer=query_tracer,
        generation_module=generation_module,
        retrieval_runtime_profile=SimpleNamespace(to_dict=lambda: {"planner": {}}),
        query_understanding_service=SimpleNamespace(),
        traditional_retrieval=_FakeClosable(),
        graph_rag_retrieval=_FakeClosable(),
        query_router=query_router,
        answer_workflow=answer_workflow,
        question_answer_service=question_answer_service,
        artifact_manifest=ArtifactManifest.missing(manifest_path="storage/indexes/artifact_manifest.json"),
        retrieval_engines_initialized=False,
    )


def _provider_stub(name: str = "provider"):
    return SimpleNamespace(
        name=name,
        infrastructure=SimpleNamespace(name=f"{name}-infrastructure"),
        build_pipeline=SimpleNamespace(name=f"{name}-build-pipeline"),
        diagnostics=SimpleNamespace(name=f"{name}-diagnostics"),
        lifecycle=SimpleNamespace(name=f"{name}-lifecycle"),
        generation=SimpleNamespace(name=f"{name}-generation"),
        query_understanding=SimpleNamespace(name=f"{name}-understanding"),
        retrieval=SimpleNamespace(name=f"{name}-retrieval"),
        services=SimpleNamespace(name=f"{name}-services"),
    )


class AppSystemRuntimeTests(unittest.TestCase):
    def test_runtime_component_provider_resolver_resolves_explicit_or_inherited_provider(self) -> None:
        explicit_provider = _provider_stub("explicit")
        bootstrapper_provider = _provider_stub("bootstrapper")
        build_provider = _provider_stub("build")
        resolver = RuntimeComponentProviderResolver()

        resolved_explicit = resolver.resolve(
            provider=explicit_provider,
            bootstrapper=SimpleNamespace(provider=bootstrapper_provider),
        )
        resolved_build = resolver.resolve(
            build_bootstrapper=SimpleNamespace(provider=build_provider),
        )

        self.assertIs(resolved_explicit, explicit_provider)
        self.assertIs(resolved_build, build_provider)

    def test_runtime_infrastructure_composer_assembles_runtime_manager_and_shared_store(self) -> None:
        config = build_test_config()
        expected_runtime_stats_access = SimpleNamespace(name="stats")
        diagnostics_service = RuntimeDiagnosticsService(
            config,
            runtime_stats_access=expected_runtime_stats_access,
        )
        shutdown_service = RuntimeShutdownService()
        calls: list[str] = []

        class _StubDiagnosticsProvider:
            def provide_runtime_stats_access(self, *, config, existing=None):
                del config, existing
                calls.append("stats")
                return expected_runtime_stats_access

            def provide_runtime_diagnostics_service(
                self,
                *,
                config,
                existing=None,
                runtime_stats_access=None,
            ):
                del config, existing
                if runtime_stats_access is not expected_runtime_stats_access:
                    raise AssertionError("runtime_stats_access should be threaded through")
                calls.append("diagnostics")
                return diagnostics_service

        class _StubLifecycleProvider:
            def provide_runtime_shutdown_service(self, *, config, existing=None):
                del config, existing
                calls.append("shutdown")
                return shutdown_service

        provider = _provider_stub("provider")
        provider_surface = RuntimeProviderSurface(
            provider=provider,
            infrastructure=provider.infrastructure,
            build_pipeline=provider.build_pipeline,
            diagnostics=_StubDiagnosticsProvider(),
            lifecycle=_StubLifecycleProvider(),
            generation=provider.generation,
            query_understanding=provider.query_understanding,
            retrieval=provider.retrieval,
            services=provider.services,
        )
        lifecycle_services = RuntimeLifecycleServiceBundle(
            initialization_service=SimpleNamespace(),
            readiness_service=RuntimeReadinessService(),
            refresh_service=SimpleNamespace(),
            build_lifecycle_service=SimpleNamespace(),
        )

        infrastructure = SystemRuntimeInfrastructureComposer().compose(
            config=config,
            provider_surface=provider_surface,
            lifecycle_services=lifecycle_services,
        )

        self.assertEqual(calls, ["stats", "diagnostics", "shutdown"])
        self.assertIs(infrastructure.diagnostics_service, diagnostics_service)
        self.assertIs(infrastructure.shutdown_service, shutdown_service)
        self.assertIs(infrastructure.runtime_manager.diagnostics_service, diagnostics_service)
        self.assertIs(infrastructure.runtime_manager.shutdown_service, shutdown_service)
        self.assertIs(
            infrastructure.runtime_manager.initialization_service,
            lifecycle_services.initialization_service,
        )
        self.assertIs(
            infrastructure.runtime_manager.readiness_service,
            lifecycle_services.readiness_service,
        )
        self.assertIs(
            infrastructure.runtime_manager.refresh_service,
            lifecycle_services.refresh_service,
        )
        self.assertIs(
            infrastructure.runtime_manager.build_lifecycle_service,
            lifecycle_services.build_lifecycle_service,
        )
        self.assertIs(
            infrastructure.runtime_manager.runtime_state_store,
            infrastructure.runtime_state_store,
        )

    def test_application_service_composer_assembles_runtime_backed_services(self) -> None:
        runtime_backend = SimpleNamespace(name="runtime-backend")
        runtime_state_store = RuntimeStateStore()

        services = SystemApplicationServiceComposer().compose(
            runtime_backend=runtime_backend,
            runtime_state_store=runtime_state_store,
        )

        self.assertIsInstance(services.operations_service, SystemOperationsService)
        self.assertIsInstance(services.answering_service, SystemAnsweringService)
        self.assertIsInstance(services.facade_support, SystemFacadeSupport)
        self.assertIs(services.operations_service.backend, runtime_backend)
        self.assertIs(services.answering_service.backend, runtime_backend)
        self.assertIs(services.answering_service.runtime_state_store, runtime_state_store)
        self.assertIs(services.facade_support.runtime_state_store, runtime_state_store)

    def test_system_answering_service_does_not_refresh_runtime_after_answer(self) -> None:
        answer_service = SimpleNamespace(
            answer_question=lambda **kwargs: QuestionAnswerResult(
                answer=f"answer:{kwargs['question']}",
                analysis=None,
            ),
            answer_question_response=lambda **kwargs: QuestionAnswerResult(
                answer=f"answer:{kwargs['question']}",
                analysis=None,
            ).to_response(),
        )
        runtime_state_store = _CountingRuntimeStateStore(
            serving_runtime=SimpleNamespace(question_answer_service=answer_service)
        )
        service = SystemAnsweringService(
            backend=SimpleNamespace(
                is_serving_initialized=lambda: True,
                initialize_serving_runtime=lambda: None,
                require_ready=lambda: None,
            ),
            runtime_state_store=runtime_state_store,
        )

        result = service.answer_question("steady runtime")
        response = service.answer_question_response("steady runtime")

        self.assertEqual(result.answer, "answer:steady runtime")
        self.assertEqual(response.answer, "answer:steady runtime")
        self.assertEqual(runtime_state_store.refresh_calls, 0)

    def test_provider_surface_resolver_resolves_provider_from_available_surface(self) -> None:
        explicit_provider = _provider_stub("explicit")
        bootstrapper_provider = _provider_stub("bootstrapper")
        resolver = RuntimeProviderSurfaceResolver()

        resolved_explicit = resolver.resolve(
            provider=explicit_provider,
            bootstrapper=SimpleNamespace(provider=bootstrapper_provider),
        )
        resolved_bootstrapper = resolver.resolve(
            bootstrapper=SimpleNamespace(provider=bootstrapper_provider),
        )

        self.assertIsInstance(resolved_explicit, RuntimeProviderSurface)
        self.assertIs(resolved_explicit.provider, explicit_provider)
        self.assertIs(resolved_bootstrapper.provider, bootstrapper_provider)

    def test_provider_surface_resolver_requires_capability_provider_surface(self) -> None:
        provider = SimpleNamespace(name="monolithic")
        resolver = RuntimeProviderSurfaceResolver()

        with self.assertRaisesRegex(AttributeError, "infrastructure"):
            resolver.resolve(provider=provider)

    def test_system_bootstrapper_surface_composer_resolves_bootstrapper_surface(self) -> None:
        provider = _provider_stub("provider")
        build_bootstrapper = SimpleNamespace(name="build")
        serving_bootstrapper = SimpleNamespace(name="serve")
        bootstrapper = SimpleNamespace(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        composer = SystemBootstrapperSurfaceComposer()

        surface = composer.compose(bootstrapper=bootstrapper)

        self.assertIsInstance(surface, AdvancedGraphRAGBootstrapperSurface)
        self.assertIs(surface.provider_surface.provider, provider)
        self.assertIs(surface.bootstrapper, bootstrapper)
        self.assertIs(surface.build_bootstrapper, build_bootstrapper)
        self.assertIs(surface.serving_bootstrapper, serving_bootstrapper)

    def test_system_composer_delegates_bootstrapper_surface_resolution(self) -> None:
        provider = _provider_stub("provider")
        build_bootstrapper = SimpleNamespace(name="build")
        serving_bootstrapper = SimpleNamespace(name="serve")
        bootstrapper = SimpleNamespace(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        calls: list[str] = []

        class _StubBootstrapperSurfaceComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return AdvancedGraphRAGBootstrapperSurface(
                    provider_surface=RuntimeProviderSurface(
                        provider=provider,
                        infrastructure=provider.infrastructure,
                        build_pipeline=provider.build_pipeline,
                        diagnostics=provider.diagnostics,
                        lifecycle=provider.lifecycle,
                        generation=provider.generation,
                        query_understanding=provider.query_understanding,
                        retrieval=provider.retrieval,
                        services=provider.services,
                    ),
                    bootstrapper=bootstrapper,
                    build_bootstrapper=build_bootstrapper,
                    serving_bootstrapper=serving_bootstrapper,
                )

        composer = AdvancedGraphRAGSystemComposer()

        surface = composer.resolve_bootstrapper_surface(
            bootstrapper=bootstrapper,
            bootstrapper_surface_composer=_StubBootstrapperSurfaceComposer(),
        )

        self.assertEqual(calls, ["compose"])
        self.assertIs(surface.bootstrapper, bootstrapper)

    def test_system_can_delegate_assembly_to_injected_composer(self) -> None:
        calls: list[str] = []
        runtime_state_store = SimpleNamespace(name="runtime-state-store")
        operations_service = SimpleNamespace(name="operations-service")
        answering_service = SimpleNamespace(name="answering-service")

        class _StubComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                build_bootstrapper = SimpleNamespace(name="build")
                serving_bootstrapper = SimpleNamespace(name="serve")
                provider = _provider_stub("provider")
                bootstrapper = SimpleNamespace(
                    provider=provider,
                    build_bootstrapper=build_bootstrapper,
                    serving_bootstrapper=serving_bootstrapper,
                )
                return AdvancedGraphRAGSystemComponents(
                    config=build_test_config(),
                    provider=provider,
                    provider_surface=RuntimeProviderSurface(
                        provider=provider,
                        infrastructure=provider.infrastructure,
                        build_pipeline=provider.build_pipeline,
                        diagnostics=provider.diagnostics,
                        lifecycle=provider.lifecycle,
                        generation=provider.generation,
                        query_understanding=provider.query_understanding,
                        retrieval=provider.retrieval,
                        services=provider.services,
                    ),
                    bootstrapper=bootstrapper,
                    build_bootstrapper=build_bootstrapper,
                    serving_bootstrapper=serving_bootstrapper,
                    diagnostics_service=SimpleNamespace(name="diagnostics"),
                    shutdown_service=SimpleNamespace(name="shutdown"),
                    lifecycle_services=RuntimeLifecycleServiceBundle(
                        initialization_service=SimpleNamespace(),
                        readiness_service=RuntimeReadinessService(),
                        refresh_service=SimpleNamespace(),
                        build_lifecycle_service=SimpleNamespace(),
                    ),
                    runtime_state_store=runtime_state_store,
                    operations_service=operations_service,
                    answering_service=answering_service,
                    facade_support=SimpleNamespace(name="facade-support"),
                )

        system = AdvancedGraphRAGSystem(system_composer=_StubComposer())

        self.assertEqual(calls, ["compose"])
        self.assertIs(system.operations_service, operations_service)
        self.assertIs(system.answering_service, answering_service)
        self.assertNotIn("interactive_service", system.__dict__)
        self.assertNotIn("run_interactive", AdvancedGraphRAGSystem.__dict__)
        with self.assertRaises(AttributeError):
            _ = system.runtime_manager

    def test_system_composer_produces_facade_support(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        composer = AdvancedGraphRAGSystemComposer()

        components = composer.compose(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertIsInstance(components.facade_support, SystemFacadeSupport)
        manager = components.operations_service.backend
        self.assertIs(components.answering_service.backend, manager)
        self.assertFalse(hasattr(components, "runtime_manager"))

    def test_system_composer_shares_runtime_state_store(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        composer = AdvancedGraphRAGSystemComposer()

        components = composer.compose(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertIsInstance(components.runtime_state_store, RuntimeStateStore)
        manager = components.operations_service.backend
        self.assertIs(manager.runtime_state_store, components.runtime_state_store)
        self.assertIs(components.facade_support.runtime_state_store, components.runtime_state_store)
        self.assertIs(components.answering_service.runtime_state_store, components.runtime_state_store)

    def test_system_composer_produces_operations_service(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        composer = AdvancedGraphRAGSystemComposer()

        components = composer.compose(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertIsInstance(components.operations_service, SystemOperationsService)
        self.assertIs(components.operations_service.backend.runtime_state_store, components.runtime_state_store)

    def test_system_composer_produces_answering_service(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        composer = AdvancedGraphRAGSystemComposer()

        components = composer.compose(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertIsInstance(components.answering_service, SystemAnsweringService)
        self.assertIs(
            components.answering_service.backend,
            components.operations_service.backend,
        )

    def test_system_composer_does_not_produce_interactive_service(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        composer = AdvancedGraphRAGSystemComposer()

        components = composer.compose(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )

        self.assertFalse(hasattr(components, "interactive_service"))

    def test_system_initialization_uses_runtime_manager_and_prepare(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        build_bootstrapper = _FakeBuildBootstrapper(build_runtime)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )

        runtime = system.initialize_system()

        self.assertIs(runtime.build_runtime, build_runtime)
        self.assertIs(runtime.serving_runtime, serving_runtime)
        self.assertEqual(build_bootstrapper.build_calls, 1)
        self.assertEqual(serving_bootstrapper.build_calls, 1)
        self.assertEqual(len(serving_bootstrapper.prepare_calls), 1)
        self.assertTrue(system.system_ready)
        diagnostics = system.collect_startup_diagnostics("serve")
        self.assertTrue(diagnostics.system_ready)
        self.assertTrue(diagnostics.retrieval_engines_initialized)
        self.assertEqual(diagnostics.manifest.stage, "ready")
        stats = system.collect_system_stats()
        self.assertEqual(stats["models"]["llm_model"], "qwen3.7-plus")
        self.assertIs(system.services.generation_service, serving_runtime.generation_module)
        self.assertIs(system.services.answer_workflow, serving_runtime.answer_workflow)
        self.assertIs(system.retrieval.routing_workflow, serving_runtime.query_router)
        self.assertIs(system.infrastructure.data_module, serving_runtime.data_module)

    def test_build_knowledge_base_refreshes_serving_runtime(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        build_bootstrapper = _FakeBuildBootstrapper(build_runtime)
        serving_bootstrapper = _FakeServingBootstrapper(serving_runtime)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        system.initialize_system()

        system.build_knowledge_base()

        self.assertEqual(build_bootstrapper.build_knowledge_base_calls, 1)
        self.assertEqual(build_runtime.knowledge_base_service.build_calls, 1)
        self.assertTrue(serving_bootstrapper.prepare_calls[-1]["force"])
        self.assertTrue(system.artifacts_ready)

    def test_default_generation_provider_returns_workflow_service(self) -> None:
        provider = DefaultGenerationComponentProvider()

        generation_service = provider.provide_generation_module(build_test_config())

        self.assertIsInstance(generation_service, GenerationWorkflowService)

    def test_default_query_understanding_provider_returns_profile_and_service(self) -> None:
        config = build_test_config()
        generation_service = DefaultGenerationComponentProvider().provide_generation_module(config)
        provider = DefaultQueryUnderstandingComponentProvider()

        retrieval_profile = provider.provide_retrieval_runtime_profile(config)
        understanding_service = provider.provide_query_understanding_service(
            config=config,
            llm_client=generation_service.client,
            retrieval_profile=retrieval_profile,
        )

        self.assertIsInstance(retrieval_profile, RetrievalRuntimeProfile)
        self.assertIsInstance(understanding_service, QueryUnderstandingService)

    def test_runtime_provider_exposes_query_understanding_capability_only(self) -> None:
        called: list[str] = []

        class _StubQueryUnderstandingProvider:
            def provide_retrieval_runtime_profile(self, config):
                del config
                called.append("profile")
                return SimpleNamespace(name="profile")

            def provide_query_understanding_service(
                self,
                *,
                config,
                llm_client,
                retrieval_profile,
            ):
                del config, llm_client, retrieval_profile
                called.append("service")
                return SimpleNamespace(name="understanding")

        provider = DefaultRuntimeComponentProvider(
            query_understanding=_StubQueryUnderstandingProvider(),
        )

        self.assertFalse(hasattr(provider, "provide_retrieval_runtime_profile"))
        self.assertFalse(hasattr(provider, "provide_query_understanding_service"))

        profile = provider.query_understanding.provide_retrieval_runtime_profile(
            build_test_config()
        )
        service = provider.query_understanding.provide_query_understanding_service(
            config=build_test_config(),
            llm_client=SimpleNamespace(),
            retrieval_profile=profile,
        )

        self.assertEqual(called, ["profile", "service"])
        self.assertEqual(profile.name, "profile")
        self.assertEqual(service.name, "understanding")

    def test_runtime_provider_does_not_fall_back_to_legacy_query_router_provider(self) -> None:
        legacy_router = SimpleNamespace(name="legacy-router")

        class _StubRetrievalProvider:
            def provide_query_router(
                self,
                *,
                config,
                traditional_retrieval,
                graph_rag_retrieval,
                llm_client,
                retrieval_profile,
                query_understanding_service,
            ):
                del (
                    config,
                    traditional_retrieval,
                    graph_rag_retrieval,
                    llm_client,
                    retrieval_profile,
                    query_understanding_service,
                )
                return legacy_router

        provider = DefaultRuntimeComponentProvider(
            retrieval=_StubRetrievalProvider(),
        )

        self.assertFalse(hasattr(provider, "provide_routing_workflow"))
        with self.assertRaises(AttributeError):
            provider.retrieval.provide_routing_workflow(
                config=build_test_config(),
                traditional_retrieval=SimpleNamespace(name="traditional"),
                graph_rag_retrieval=SimpleNamespace(name="graph"),
                llm_client=SimpleNamespace(name="client"),
                retrieval_profile=SimpleNamespace(name="profile"),
                query_understanding_service=SimpleNamespace(name="understanding"),
            )

    def test_system_uses_provider_backed_runtime_diagnostics_service(self) -> None:
        called: list[str] = []

        class _StubDiagnosticsProvider:
            def provide_runtime_stats_access(
                self,
                *,
                config,
                existing=None,
            ):
                del config, existing
                called.append("stats")
                return SimpleNamespace(name="stats")

            def provide_runtime_diagnostics_service(
                self,
                *,
                config,
                existing=None,
                runtime_stats_access=None,
            ):
                del config, existing
                if runtime_stats_access is None:
                    raise AssertionError("runtime_stats_access should be provided")
                called.append("diagnostics")
                return RuntimeDiagnosticsService(build_test_config())

        provider = DefaultRuntimeComponentProvider(
            diagnostics=_StubDiagnosticsProvider(),
        )

        system = AdvancedGraphRAGSystem(
            config=build_test_config(),
            provider=provider,
            build_bootstrapper=_FakeBuildBootstrapper(_build_runtime()),
            serving_bootstrapper=_FakeServingBootstrapper(_serving_runtime(build_test_config())),
        )

        self.assertEqual(called, ["stats", "diagnostics"])

    def test_system_uses_provider_backed_runtime_shutdown_service(self) -> None:
        called: list[str] = []

        class _StubShutdownService:
            def close(self, *, runtime) -> None:
                del runtime
                called.append("close")

        class _StubLifecycleProvider:
            def provide_runtime_shutdown_service(
                self,
                *,
                config,
                existing=None,
            ):
                del config, existing
                called.append("lifecycle")
                return _StubShutdownService()

        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        provider = DefaultRuntimeComponentProvider(
            lifecycle=_StubLifecycleProvider(),
        )

        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            provider=provider,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        system.initialize_system()

        system.close()

        self.assertEqual(called, ["lifecycle", "close"])

    def test_system_close_uses_shutdown_service_semantics(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        system.initialize_system()
        serving_runtime.retrieval_engines_initialized = True

        system.close()

        self.assertTrue(serving_runtime.query_tracer.closed)
        self.assertTrue(serving_runtime.traditional_retrieval.closed)
        self.assertTrue(serving_runtime.graph_rag_retrieval.closed)
        self.assertTrue(build_runtime.knowledge_base_service.closed)
        self.assertFalse(serving_runtime.retrieval_engines_initialized)
        self.assertFalse(system.is_initialized())
        self.assertIsNone(system.build_runtime)
        self.assertIsNone(system.serving_runtime)
        self.assertFalse(system.artifacts_ready)
        self.assertFalse(system.system_ready)

    def test_system_answer_question_prefers_answer_workflow(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        system.initialize_system()

        result = system.answer_question("test question")

        self.assertEqual(result.answer, "workflow-ok")

    def test_system_exposes_lazy_question_answer_service_compat_wrapper(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        system.initialize_system()

        service = system.services.question_answer_service

        self.assertIsNotNone(service)
        self.assertEqual(service.answer_question("compat question").answer, "workflow-ok")
        self.assertIs(service, system.services.question_answer_service)

    def test_flat_runtime_attributes_are_retired_in_favor_of_grouped_views(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        runtime = system.initialize_system()

        self.assertIsInstance(system.infrastructure, SystemInfrastructureView)
        self.assertIsInstance(system.retrieval, SystemRetrievalView)
        self.assertIsInstance(system.services, SystemServicesView)
        self.assertIsInstance(runtime.infrastructure, SystemInfrastructureView)
        self.assertIsInstance(runtime.retrieval, SystemRetrievalView)
        self.assertIsInstance(runtime.services, SystemServicesView)
        self.assertIs(system.retrieval.routing_workflow, serving_runtime.query_router)
        self.assertIs(system.services.generation_service, serving_runtime.generation_module)
        self.assertIs(
            system.services.question_answer_service,
            serving_runtime.question_answer_service,
        )
        self.assertIs(runtime.infrastructure.data_module, serving_runtime.data_module)
        self.assertIs(runtime.retrieval.routing_workflow, serving_runtime.query_router)
        self.assertIs(runtime.services.answer_workflow, serving_runtime.answer_workflow)

        for owner, name in (
            (system, "query_router"),
            (system, "generation_service"),
            (system, "question_answer_service"),
            (runtime, "data_module"),
            (runtime, "query_router"),
            (runtime, "answer_workflow"),
        ):
            with self.subTest(owner=type(owner).__name__, name=name):
                with self.assertRaises(AttributeError):
                    getattr(owner, name)
                self.assertNotIn(name, dir(owner))

    def test_runtime_grouped_views_are_cached_per_runtime_instance(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        runtime = system.initialize_system()

        first_infrastructure = runtime.infrastructure
        first_retrieval = runtime.retrieval
        first_services = runtime.services

        self.assertIs(first_infrastructure, runtime.infrastructure)
        self.assertIs(first_retrieval, runtime.retrieval)
        self.assertIs(first_services, runtime.services)

    def test_system_answer_question_response_returns_api_ready_contract(self) -> None:
        build_runtime = _build_runtime()
        serving_runtime = _serving_runtime(build_runtime.config)
        system = AdvancedGraphRAGSystem(
            config=build_runtime.config,
            build_bootstrapper=_FakeBuildBootstrapper(build_runtime),
            serving_bootstrapper=_FakeServingBootstrapper(serving_runtime),
        )
        system.initialize_system()

        response = system.answer_question_response("test question")
        payload = response.to_dict()

        self.assertEqual(response.answer, "workflow-ok")
        self.assertEqual(response.doc_count, 0)
        self.assertFalse(response.has_evidence)
        self.assertEqual(set(payload.keys()), {"summary", "grounding", "diagnostics", "traces"})
        self.assertEqual(payload["summary"]["answer"], "workflow-ok")


if __name__ == "__main__":
    unittest.main()
