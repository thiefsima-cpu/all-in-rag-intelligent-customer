from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.bootstrap import GraphRAGBootstrapper, ServingBootstrapper
from rag_modules.app.composition.bootstrapper_composer import (
    GraphBootstrapperSurface,
    GraphBootstrapperSurfaceComposer,
    GraphRAGBootstrapperComponents,
    GraphRAGBootstrapperComposer,
    ServingBootstrapperComponents,
    ServingBootstrapperComposer,
    SystemRuntimeBootstrapServiceComposer,
)
from rag_modules.app.composition.serving_runtime_assembler import ServingRuntimeAssembler
from rag_modules.app.composition.serving_runtime_factory import ServingRuntimeFactory
from rag_modules.app.composition.serving_runtime_lifecycle_service import (
    ServingRuntimeLifecycleService,
)
from rag_modules.app.composition.serving_runtime_preparer import ServingRuntimePreparer
from rag_modules.artifacts import ArtifactManifest
from rag_modules.build_pipeline.document_artifacts.models import DocumentArtifactResult
from rag_modules.configuration.testing import build_test_config
from rag_modules.text_document import TextDocument


class _StubAssembler:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls: list[dict] = []

    def assemble(self, config=None, **kwargs):
        self.calls.append({"config": config, **kwargs})
        return self.runtime


class _StubPreparer:
    def __init__(self):
        self.prepare_calls: list[dict] = []
        self.shared_prepare_calls: list[dict] = []

    def prepare(self, runtime, **kwargs):
        self.prepare_calls.append({"runtime": runtime, **kwargs})
        return runtime

    def prepare_with_shared_runtime(self, runtime, **kwargs):
        self.shared_prepare_calls.append({"runtime": runtime, **kwargs})
        runtime.prepared = True
        return runtime


class _StubServingFactory:
    def __init__(self, runtime):
        self.runtime = runtime
        self.build_calls: list[dict] = []
        self.prepare_calls: list[dict] = []
        self.prepare_shared_calls: list[dict] = []

    def build(self, config=None, **kwargs):
        self.build_calls.append({"config": config, **kwargs})
        return self.runtime

    def prepare(self, runtime, **kwargs):
        self.prepare_calls.append({"runtime": runtime, **kwargs})
        return runtime

    def prepare_with_shared_runtime(self, runtime, **kwargs):
        self.prepare_shared_calls.append({"runtime": runtime, **kwargs})
        runtime.prepared = True
        return runtime


class _StubServingLifecycleService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.build_ready_calls: list[dict] = []
        self.prepare_calls: list[dict] = []
        self.prepare_shared_calls: list[dict] = []

    def build_ready(self, config=None, **kwargs):
        self.build_ready_calls.append({"config": config, **kwargs})
        self.runtime.prepared = True
        return self.runtime

    def prepare(self, runtime, **kwargs):
        self.prepare_calls.append({"runtime": runtime, **kwargs})
        return runtime

    def prepare_with_shared_runtime(self, runtime, **kwargs):
        self.prepare_shared_calls.append({"runtime": runtime, **kwargs})
        runtime.prepared = True
        return runtime


class _StubSystemBootstrapService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls: list[dict] = []

    def build(self, config=None, **kwargs):
        self.calls.append({"config": config, **kwargs})
        return self.runtime


class _FakeManifestStore:
    def __init__(self, manifest):
        self.manifest = manifest
        self.load_calls = 0

    def load(self):
        self.load_calls += 1
        return self.manifest


class _FakeDocumentArtifactCache:
    def __init__(self, result):
        self.result = result
        self.load_calls = 0

    def load(self, data_module):
        self.load_calls += 1
        data_module.cache_loaded = True
        return self.result


class _FakeRuntimeArtifactAccess:
    def __init__(self):
        self.graph_load_calls = 0
        self.vector_has_collection_calls = 0
        self.vector_load_calls = 0

    def load_graph_data(self, data_module):
        self.graph_load_calls += 1
        data_module.graph_loaded_via_adapter = True
        loader = getattr(data_module, "load_graph_data", None)
        if callable(loader):
            return loader()
        return None

    def has_vector_collection(self, index_module):
        self.vector_has_collection_calls += 1
        return bool(index_module.has_collection())

    def load_vector_collection(self, index_module):
        self.vector_load_calls += 1
        return bool(index_module.load_collection())


class _FakeTraditionalRetrieval:
    def __init__(self):
        self.initialized_docs = None

    def initialize(self, docs):
        self.initialized_docs = list(docs)


class _FakeGraphRetrieval:
    def __init__(self):
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1


class _FailingGraphRetrieval:
    def __init__(self, message: str = "graph init failed"):
        self.message = message
        self.initialize_calls = 0

    def initialize(self):
        self.initialize_calls += 1
        raise RuntimeError(self.message)


class ServingRuntimeFactoryTests(unittest.TestCase):
    def test_build_only_assembles_runtime(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        assembler = _StubAssembler(runtime)
        preparer = _StubPreparer()
        factory = ServingRuntimeFactory(
            provider=SimpleNamespace(),
            assembler=assembler,
        )

        result = factory.build(config=SimpleNamespace(name="cfg"), shared_runtime=SimpleNamespace())

        self.assertIs(result, runtime)
        self.assertEqual(len(assembler.calls), 1)
        self.assertEqual(preparer.shared_prepare_calls, [])
        self.assertFalse(runtime.prepared)
        self.assertFalse(hasattr(factory, "prepare"))
        self.assertFalse(hasattr(factory, "prepare_with_shared_runtime"))
        self.assertFalse(hasattr(factory, "build_ready"))

    def test_lifecycle_service_prepare_with_shared_runtime_delegates_to_preparer(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        preparer = _StubPreparer()
        assembler = _StubAssembler(runtime)
        factory = ServingRuntimeFactory(
            provider=SimpleNamespace(),
            assembler=assembler,
        )
        lifecycle_service = ServingRuntimeLifecycleService(
            serving_runtime_factory=factory,
            serving_runtime_preparer=preparer,
        )
        shared_runtime = SimpleNamespace(name="build")

        result = lifecycle_service.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
        )

        self.assertIs(result, runtime)
        self.assertTrue(runtime.prepared)
        self.assertEqual(len(preparer.shared_prepare_calls), 1)
        self.assertIs(preparer.shared_prepare_calls[0]["shared_runtime"], shared_runtime)
        self.assertEqual(assembler.calls, [])

    def test_preparer_loads_artifacts_through_infrastructure_provider_boundary(self) -> None:
        ready_manifest = ArtifactManifest(
            stage="ready",
            manifest_path="manifest.json",
            index_signature="sig-1",
            collection_name="recipes",
        )
        cache_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                manifest_path="manifest.json",
                index_signature="sig-1",
                collection_name="recipes",
                total_documents=1,
                total_chunks=1,
                documents_path="documents.json",
                chunks_path="chunks.json",
                cache_hit=True,
            ),
            cache_hit=True,
        )
        manifest_store = _FakeManifestStore(ready_manifest)
        document_cache = _FakeDocumentArtifactCache(cache_result)
        runtime_artifact_access = _FakeRuntimeArtifactAccess()
        infrastructure = SimpleNamespace(
            provide_artifact_manifest_store=lambda config, existing=None: (
                existing or manifest_store
            ),
            provide_document_artifact_cache=(
                lambda config, existing=None, *, manifest_store=None: existing or document_cache
            ),
            provide_runtime_artifact_access=(
                lambda config, existing=None: existing or runtime_artifact_access
            ),
        )
        preparer = ServingRuntimePreparer(provider=SimpleNamespace(infrastructure=infrastructure))
        traditional_retrieval = _FakeTraditionalRetrieval()
        graph_rag_retrieval = _FakeGraphRetrieval()
        data_module = SimpleNamespace(
            chunks=[],
            cache_loaded=False,
            graph_load_calls=0,
            graph_loaded_via_adapter=False,
        )

        def _load_graph_data():
            data_module.graph_load_calls += 1

        data_module.load_graph_data = _load_graph_data
        runtime = SimpleNamespace(
            config=SimpleNamespace(),
            artifact_manifest=ArtifactManifest.missing(manifest_path="manifest.json"),
            retrieval_engines_initialized=False,
            data_module=data_module,
            index_module=SimpleNamespace(
                has_collection=lambda: True,
                load_collection=lambda: True,
            ),
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
        )

        result = preparer.prepare(runtime)

        self.assertIs(result, runtime)
        self.assertEqual(manifest_store.load_calls, 1)
        self.assertEqual(document_cache.load_calls, 1)
        self.assertEqual(data_module.graph_load_calls, 1)
        self.assertTrue(data_module.graph_loaded_via_adapter)
        self.assertEqual(runtime_artifact_access.graph_load_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_has_collection_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_load_calls, 1)
        self.assertTrue(runtime.retrieval_engines_initialized)
        self.assertTrue(data_module.cache_loaded)
        self.assertEqual(len(traditional_retrieval.initialized_docs or []), 1)
        self.assertEqual(graph_rag_retrieval.initialize_calls, 1)
        self.assertEqual(runtime.artifact_manifest.stage, "ready")
        self.assertEqual(runtime.artifact_manifest.index_signature, "sig-1")

    def test_preparer_raises_when_graph_retrieval_initialization_fails(self) -> None:
        ready_manifest = ArtifactManifest(
            stage="ready",
            manifest_path="manifest.json",
            index_signature="sig-1",
            collection_name="recipes",
        )
        cache_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                manifest_path="manifest.json",
                index_signature="sig-1",
                collection_name="recipes",
            ),
            cache_hit=True,
        )
        infrastructure = SimpleNamespace(
            provide_artifact_manifest_store=(
                lambda config, existing=None: existing or _FakeManifestStore(ready_manifest)
            ),
            provide_document_artifact_cache=(
                lambda config, existing=None, *, manifest_store=None: (
                    existing or _FakeDocumentArtifactCache(cache_result)
                )
            ),
            provide_runtime_artifact_access=(
                lambda config, existing=None: existing or _FakeRuntimeArtifactAccess()
            ),
        )
        preparer = ServingRuntimePreparer(provider=SimpleNamespace(infrastructure=infrastructure))
        runtime = SimpleNamespace(
            config=SimpleNamespace(),
            artifact_manifest=ArtifactManifest.missing(manifest_path="manifest.json"),
            retrieval_engines_initialized=False,
            data_module=SimpleNamespace(chunks=[], load_graph_data=lambda: None),
            index_module=SimpleNamespace(
                has_collection=lambda: True,
                load_collection=lambda: True,
            ),
            traditional_retrieval=_FakeTraditionalRetrieval(),
            graph_rag_retrieval=_FailingGraphRetrieval(),
        )

        with self.assertRaisesRegex(
            RuntimeError, "Serving runtime retrieval initialization failed"
        ):
            preparer.prepare(runtime)

        self.assertFalse(runtime.retrieval_engines_initialized)

    def test_preparer_marks_manifest_stale_when_cached_artifacts_mismatch_index_signature(
        self,
    ) -> None:
        ready_manifest = ArtifactManifest(
            stage="ready",
            manifest_path="manifest.json",
            index_signature="persisted-index",
            collection_name="recipes",
        )
        cache_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                manifest_path="manifest.json",
                index_signature="current-index",
                collection_name="recipes",
            ),
            cache_hit=True,
        )
        infrastructure = SimpleNamespace(
            provide_artifact_manifest_store=(
                lambda config, existing=None: existing or _FakeManifestStore(ready_manifest)
            ),
            provide_document_artifact_cache=(
                lambda config, existing=None, *, manifest_store=None: (
                    existing or _FakeDocumentArtifactCache(cache_result)
                )
            ),
            provide_runtime_artifact_access=(
                lambda config, existing=None: existing or _FakeRuntimeArtifactAccess()
            ),
        )
        traditional_retrieval = _FakeTraditionalRetrieval()
        graph_rag_retrieval = _FakeGraphRetrieval()
        preparer = ServingRuntimePreparer(provider=SimpleNamespace(infrastructure=infrastructure))
        runtime = SimpleNamespace(
            config=SimpleNamespace(),
            artifact_manifest=ArtifactManifest.missing(manifest_path="manifest.json"),
            retrieval_engines_initialized=False,
            data_module=SimpleNamespace(chunks=[], load_graph_data=lambda: None),
            index_module=SimpleNamespace(
                has_collection=lambda: True,
                load_collection=lambda: True,
            ),
            traditional_retrieval=traditional_retrieval,
            graph_rag_retrieval=graph_rag_retrieval,
        )

        result = preparer.prepare(runtime)

        self.assertIs(result, runtime)
        self.assertFalse(runtime.retrieval_engines_initialized)
        self.assertEqual(runtime.artifact_manifest.stage, "stale")
        self.assertIn("do not match", runtime.artifact_manifest.last_error)
        self.assertIsNone(traditional_retrieval.initialized_docs)
        self.assertEqual(graph_rag_retrieval.initialize_calls, 0)


class ServingRuntimeAssemblerTests(unittest.TestCase):
    def test_assembler_uses_query_understanding_capability_provider(self) -> None:
        config = build_test_config()
        client = SimpleNamespace(name="client")
        llm_client = SimpleNamespace(name="llm-client")
        profile = SimpleNamespace(name="profile")
        understanding_service = SimpleNamespace(name="understanding")
        traditional_retrieval = SimpleNamespace(name="traditional")
        graph_rag_retrieval = SimpleNamespace(name="graph")
        router = SimpleNamespace(name="router")
        answer_workflow = SimpleNamespace(name="workflow")

        infrastructure = SimpleNamespace(
            provide_neo4j_manager=(
                lambda config, existing=None: existing or SimpleNamespace(name="neo4j")
            ),
            provide_data_module=(
                lambda config, neo4j_manager, existing=None: (
                    existing or SimpleNamespace(name="data", neo4j_manager=neo4j_manager)
                )
            ),
            provide_index_module=(
                lambda config, existing=None: existing or SimpleNamespace(name="index")
            ),
            provide_query_tracer=(
                lambda config, existing=None: existing or SimpleNamespace(name="tracer")
            ),
        )
        generation = SimpleNamespace(
            provide_generation_module=lambda config: SimpleNamespace(
                client=client,
                llm_client=llm_client,
            )
        )
        retrieval = SimpleNamespace(
            provide_traditional_retrieval=lambda **kwargs: traditional_retrieval,
            provide_graph_rag_retrieval=lambda **kwargs: graph_rag_retrieval,
            provide_routing_workflow=lambda **kwargs: router,
        )
        services = SimpleNamespace(
            provide_answer_workflow=lambda **kwargs: answer_workflow,
            provide_question_answer_service=lambda **kwargs: SimpleNamespace(
                name="question-answer-service",
                workflow=kwargs["answer_workflow"],
            ),
        )

        class _RootProvider:
            def __init__(self) -> None:
                self.infrastructure = infrastructure
                self.build_pipeline = SimpleNamespace()
                self.diagnostics = SimpleNamespace()
                self.lifecycle = SimpleNamespace()
                self.generation = generation
                self.query_understanding = self
                self.retrieval = retrieval
                self.services = services
                self.calls: list[str] = []

            def provide_retrieval_runtime_profile(self, config):
                self.calls.append("profile")
                return profile

            def provide_query_understanding_service(
                self,
                *,
                config,
                llm_client,
                retrieval_profile,
            ):
                self.calls.append("service")
                self.last_llm_client = llm_client
                self.last_profile = retrieval_profile
                return understanding_service

        provider = _RootProvider()
        assembler = ServingRuntimeAssembler(provider=provider)

        runtime = assembler.assemble(config=config)

        self.assertEqual(provider.calls, ["profile", "service"])
        self.assertIs(provider.last_llm_client, llm_client)
        self.assertIs(provider.last_profile, profile)
        self.assertIs(runtime.retrieval_runtime_profile, profile)
        self.assertIs(runtime.query_understanding_service, understanding_service)
        self.assertIs(runtime.query_router, router)
        self.assertIs(runtime.answer_workflow, answer_workflow)
        self.assertEqual(runtime.question_answer_service.name, "question-answer-service")
        self.assertIs(runtime.question_answer_service.workflow, answer_workflow)

    def test_assembler_requires_canonical_routing_workflow_provider(self) -> None:
        config = build_test_config()
        profile = SimpleNamespace(name="profile")
        understanding_service = SimpleNamespace(name="understanding")

        infrastructure = SimpleNamespace(
            provide_neo4j_manager=(
                lambda config, existing=None: existing or SimpleNamespace(name="neo4j")
            ),
            provide_data_module=(
                lambda config, neo4j_manager, existing=None: (
                    existing or SimpleNamespace(name="data", neo4j_manager=neo4j_manager)
                )
            ),
            provide_index_module=(
                lambda config, existing=None: existing or SimpleNamespace(name="index")
            ),
            provide_query_tracer=(
                lambda config, existing=None: existing or SimpleNamespace(name="tracer")
            ),
        )
        provider = SimpleNamespace(
            infrastructure=infrastructure,
            build_pipeline=SimpleNamespace(),
            diagnostics=SimpleNamespace(),
            lifecycle=SimpleNamespace(),
            generation=SimpleNamespace(
                provide_generation_module=lambda config: SimpleNamespace(client=SimpleNamespace())
            ),
            query_understanding=SimpleNamespace(
                provide_retrieval_runtime_profile=lambda config: profile,
                provide_query_understanding_service=lambda **kwargs: understanding_service,
            ),
            retrieval=SimpleNamespace(
                provide_traditional_retrieval=lambda **kwargs: SimpleNamespace(name="traditional"),
                provide_graph_rag_retrieval=lambda **kwargs: SimpleNamespace(name="graph"),
            ),
            services=SimpleNamespace(
                provide_answer_workflow=lambda **kwargs: SimpleNamespace(name="workflow"),
                provide_question_answer_service=lambda **kwargs: SimpleNamespace(
                    name="question-answer-service",
                    workflow=kwargs["answer_workflow"],
                ),
            ),
        )

        assembler = ServingRuntimeAssembler(provider=provider)

        with self.assertRaisesRegex(AttributeError, "provide_routing_workflow"):
            assembler.assemble(config=config)


class ServingBootstrapperTests(unittest.TestCase):
    def test_bootstrapper_composer_builds_default_lifecycle_bundle(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        composer = ServingBootstrapperComposer()

        components = composer.compose(
            provider=SimpleNamespace(),
            factory=_StubServingFactory(runtime),
            preparer=_StubPreparer(),
        )

        self.assertIsInstance(components, ServingBootstrapperComponents)
        self.assertTrue(callable(getattr(components.factory, "build", None)))
        self.assertTrue(callable(getattr(components.preparer, "prepare_with_shared_runtime", None)))
        self.assertIsInstance(components.lifecycle_service, ServingRuntimeLifecycleService)

    def test_public_bootstrapper_binds_serving_components_from_composer_dataclass(self) -> None:
        provider = SimpleNamespace(name="provider")
        factory = SimpleNamespace(name="factory")
        preparer = SimpleNamespace(name="preparer")
        lifecycle_service = _StubServingLifecycleService(SimpleNamespace(prepared=False))
        calls: list[str] = []

        class _StubComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return ServingBootstrapperComponents(
                    provider=provider,
                    factory=factory,
                    preparer=preparer,
                    lifecycle_service=lifecycle_service,
                )

        bootstrapper = ServingBootstrapper(bootstrapper_composer=_StubComposer())

        self.assertEqual(calls, ["compose"])
        self.assertIs(bootstrapper.provider, provider)
        self.assertIs(bootstrapper.factory, factory)
        self.assertIs(bootstrapper.preparer, preparer)
        self.assertIs(bootstrapper.lifecycle_service, lifecycle_service)

    def test_build_still_prepares_runtime_for_public_bootstrapper(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        lifecycle_service = _StubServingLifecycleService(runtime)
        bootstrapper = ServingBootstrapper(
            provider=SimpleNamespace(),
            factory=_StubServingFactory(runtime),
            lifecycle_service=lifecycle_service,
        )
        shared_runtime = SimpleNamespace(name="build")

        result = bootstrapper.build(
            config=SimpleNamespace(name="cfg"),
            shared_runtime=shared_runtime,
        )

        self.assertIs(result, runtime)
        self.assertTrue(runtime.prepared)
        self.assertEqual(len(lifecycle_service.build_ready_calls), 1)
        self.assertIs(lifecycle_service.build_ready_calls[0]["shared_runtime"], shared_runtime)

    def test_build_can_delegate_through_injected_lifecycle_service(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        lifecycle_service = _StubServingLifecycleService(runtime)
        bootstrapper = ServingBootstrapper(
            provider=SimpleNamespace(),
            factory=_StubServingFactory(runtime),
            lifecycle_service=lifecycle_service,
        )

        result = bootstrapper.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result, runtime)
        self.assertTrue(runtime.prepared)
        self.assertEqual(len(lifecycle_service.build_ready_calls), 1)

    def test_build_can_compose_lifecycle_service_from_factory_and_preparer(self) -> None:
        runtime = SimpleNamespace(prepared=False)
        factory = _StubServingFactory(runtime)
        preparer = _StubPreparer()
        bootstrapper = ServingBootstrapper(
            provider=SimpleNamespace(),
            factory=factory,
            preparer=preparer,
        )

        result = bootstrapper.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result, runtime)
        self.assertTrue(runtime.prepared)
        self.assertEqual(len(factory.build_calls), 1)
        self.assertEqual(len(preparer.shared_prepare_calls), 1)


class GraphRAGBootstrapperTests(unittest.TestCase):
    def test_bootstrapper_surface_composer_resolves_explicit_split_surface(self) -> None:
        provider = SimpleNamespace(name="provider")
        build_bootstrapper = SimpleNamespace(name="build")
        serving_bootstrapper = SimpleNamespace(name="serve")

        surface = GraphBootstrapperSurfaceComposer().compose(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )

        self.assertIsInstance(surface, GraphBootstrapperSurface)
        self.assertIs(surface.provider, provider)
        self.assertIs(surface.build_bootstrapper, build_bootstrapper)
        self.assertIs(surface.serving_bootstrapper, serving_bootstrapper)

    def test_bootstrapper_composer_builds_default_bootstrap_service_directly(self) -> None:
        build_runtime = SimpleNamespace(name="build")
        serving_runtime = SimpleNamespace(name="serving", prepared=False)
        adapt_calls: list[dict] = []

        class _StubBuildBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return build_runtime

        class _StubServingBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return serving_runtime

            def prepare_with_shared_runtime(self, runtime, **kwargs):
                del kwargs
                runtime.prepared = True
                return runtime

        class _StubLifecycleServiceComposer:
            def adapt_bootstrappers(self, **kwargs):
                adapt_calls.append(kwargs)
                return SimpleNamespace(
                    build_runtime_factory=_StubBuildBootstrapper(),
                    serving_runtime_lifecycle_service=_StubServingLifecycleService(serving_runtime),
                )

        composer = GraphRAGBootstrapperComposer()
        components = composer.compose(
            provider=SimpleNamespace(),
            build_bootstrapper=_StubBuildBootstrapper(),
            serving_bootstrapper=_StubServingBootstrapper(),
            lifecycle_service_composer=_StubLifecycleServiceComposer(),
        )

        self.assertIsInstance(components, GraphRAGBootstrapperComponents)
        self.assertTrue(callable(getattr(components.bootstrap_service, "build", None)))
        self.assertEqual(len(adapt_calls), 1)

    def test_bootstrap_service_composer_builds_service_from_adapted_bootstrappers(self) -> None:
        build_bootstrapper = SimpleNamespace(name="build-bootstrapper")
        serving_bootstrapper = SimpleNamespace(name="serving-bootstrapper")
        lifecycle_components = SimpleNamespace(
            build_runtime_factory=SimpleNamespace(name="build-factory"),
            serving_runtime_lifecycle_service=SimpleNamespace(name="serving-lifecycle"),
        )
        calls: list[str] = []
        captured: dict[str, object] = {}

        class _StubLifecycleServiceComposer:
            def adapt_bootstrappers(self, **kwargs):
                captured.update(kwargs)
                calls.append("adapt")
                return lifecycle_components

        service = SystemRuntimeBootstrapServiceComposer().compose(
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            lifecycle_service_composer=_StubLifecycleServiceComposer(),
        )

        self.assertEqual(calls, ["adapt"])
        self.assertIs(captured["build_bootstrapper"], build_bootstrapper)
        self.assertIs(captured["serving_bootstrapper"], serving_bootstrapper)
        self.assertIs(service.build_runtime_factory, lifecycle_components.build_runtime_factory)
        self.assertIs(
            service.serving_runtime_lifecycle_service,
            lifecycle_components.serving_runtime_lifecycle_service,
        )

    def test_bootstrapper_composer_delegates_surface_resolution(self) -> None:
        build_runtime = SimpleNamespace(name="build")
        serving_runtime = SimpleNamespace(name="serving", prepared=False)
        calls: list[str] = []

        class _StubBuildBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return build_runtime

        class _StubServingBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return serving_runtime

            def prepare_with_shared_runtime(self, runtime, **kwargs):
                del kwargs
                runtime.prepared = True
                return runtime

        class _StubSurfaceComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return GraphBootstrapperSurface(
                    provider=SimpleNamespace(name="provider"),
                    build_bootstrapper=_StubBuildBootstrapper(),
                    serving_bootstrapper=_StubServingBootstrapper(),
                )

        components = GraphRAGBootstrapperComposer().compose(
            provider=SimpleNamespace(name="ignored"),
            bootstrapper_surface_composer=_StubSurfaceComposer(),
        )

        self.assertEqual(calls, ["compose"])
        self.assertIsInstance(components, GraphRAGBootstrapperComponents)
        self.assertTrue(callable(getattr(components.bootstrap_service, "build", None)))

    def test_bootstrapper_composer_delegates_bootstrap_service_assembly(self) -> None:
        calls: list[str] = []

        class _StubSurfaceComposer:
            def compose(self, **kwargs):
                del kwargs
                return GraphBootstrapperSurface(
                    provider=SimpleNamespace(name="provider"),
                    build_bootstrapper=SimpleNamespace(name="build"),
                    serving_bootstrapper=SimpleNamespace(name="serve"),
                )

        class _StubBootstrapServiceComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return _StubSystemBootstrapService(SimpleNamespace(name="runtime"))

        components = GraphRAGBootstrapperComposer().compose(
            bootstrapper_surface_composer=_StubSurfaceComposer(),
            bootstrap_service_composer=_StubBootstrapServiceComposer(),
        )

        self.assertEqual(calls, ["compose"])
        self.assertIsInstance(components, GraphRAGBootstrapperComponents)
        self.assertTrue(callable(getattr(components.bootstrap_service, "build", None)))

    def test_public_bootstrapper_binds_graph_components_from_composer_dataclass(self) -> None:
        provider = SimpleNamespace(name="provider")
        build_bootstrapper = SimpleNamespace(name="build")
        serving_bootstrapper = SimpleNamespace(name="serve")
        bootstrap_service = _StubSystemBootstrapService(SimpleNamespace(name="runtime"))
        calls: list[str] = []

        class _StubComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return GraphRAGBootstrapperComponents(
                    provider=provider,
                    build_bootstrapper=build_bootstrapper,
                    serving_bootstrapper=serving_bootstrapper,
                    bootstrap_service=bootstrap_service,
                )

        bootstrapper = GraphRAGBootstrapper(bootstrapper_composer=_StubComposer())

        self.assertEqual(calls, ["compose"])
        self.assertIs(bootstrapper.provider, provider)
        self.assertIs(bootstrapper.build_bootstrapper, build_bootstrapper)
        self.assertIs(bootstrapper.serving_bootstrapper, serving_bootstrapper)
        self.assertIs(bootstrapper.bootstrap_service, bootstrap_service)

    def test_build_delegates_to_bootstrap_service(self) -> None:
        runtime = SimpleNamespace(name="system")
        bootstrap_service = _StubSystemBootstrapService(runtime)
        bootstrapper = GraphRAGBootstrapper(
            provider=SimpleNamespace(),
            build_bootstrapper=SimpleNamespace(name="build"),
            serving_bootstrapper=SimpleNamespace(name="serve"),
            bootstrap_service=bootstrap_service,
        )

        result = bootstrapper.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result, runtime)
        self.assertEqual(len(bootstrap_service.calls), 1)

    def test_build_can_compose_bootstrap_service_from_split_bootstrappers(self) -> None:
        build_runtime = SimpleNamespace(name="build")
        serving_runtime = SimpleNamespace(name="serving", prepared=False)

        class _StubBuildBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return build_runtime

        class _StubServingBootstrapper:
            def build(self, config=None, **kwargs):
                del config, kwargs
                return serving_runtime

            def prepare_with_shared_runtime(self, runtime, **kwargs):
                del kwargs
                runtime.prepared = True
                return runtime

        bootstrapper = GraphRAGBootstrapper(
            provider=SimpleNamespace(),
            build_bootstrapper=_StubBuildBootstrapper(),
            serving_bootstrapper=_StubServingBootstrapper(),
        )

        result = bootstrapper.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result.build_runtime, build_runtime)
        self.assertIs(result.serving_runtime, serving_runtime)
        self.assertTrue(serving_runtime.prepared)


if __name__ == "__main__":
    unittest.main()
