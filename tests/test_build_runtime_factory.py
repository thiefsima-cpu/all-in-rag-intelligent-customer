from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.bootstrap import BuildBootstrapper
from rag_modules.app.composition.bootstrapper_composer import (
    BuildBootstrapperComponents,
    BuildBootstrapperComposer,
)
from rag_modules.app.composition.build_runtime_factory import BuildRuntimeFactory
from rag_modules.runtime.artifacts import ArtifactManifest


class _FakeKnowledgeBaseService:
    def __init__(self, manifest: ArtifactManifest) -> None:
        self.artifact_manifest = manifest


class _CapturingServicesProvider:
    def __init__(self, *, knowledge_base_service, runtime_stats_access) -> None:
        self.knowledge_base_service = knowledge_base_service
        self.runtime_stats_access = runtime_stats_access
        self.calls: list[dict] = []
        self.stats_calls: list[dict] = []

    def provide_runtime_stats_access(self, **kwargs):
        self.stats_calls.append(kwargs)
        return self.runtime_stats_access

    def provide_knowledge_base_service(self, **kwargs):
        self.calls.append(kwargs)
        return self.knowledge_base_service


class _CapturingBuildPipelineProvider:
    def __init__(self, *, document_artifact_builder, semantic_graph_schema_sync) -> None:
        self.document_artifact_builder = document_artifact_builder
        self.semantic_graph_schema_sync = semantic_graph_schema_sync
        self.document_builder_calls: list[dict] = []
        self.schema_sync_calls: list[dict] = []

    def provide_document_artifact_builder(self, **kwargs):
        self.document_builder_calls.append(kwargs)
        return self.document_artifact_builder

    def provide_semantic_graph_schema_sync(self, **kwargs):
        self.schema_sync_calls.append(kwargs)
        return self.semantic_graph_schema_sync


class _StubExecutor:
    def __init__(self):
        self.build_calls: list[dict] = []
        self.rebuild_calls: list[dict] = []

    def build_knowledge_base(self, runtime, **kwargs):
        self.build_calls.append({"runtime": runtime, **kwargs})
        runtime.build_prepared = True
        return runtime

    def rebuild_knowledge_base(self, runtime, **kwargs):
        self.rebuild_calls.append({"runtime": runtime, **kwargs})
        runtime.rebuild_prepared = True
        return runtime


class BuildRuntimeFactoryTests(unittest.TestCase):
    def test_build_injects_build_lifecycle_ports_and_services(self) -> None:
        manifest_store = object()
        document_artifact_cache = object()
        runtime_artifact_access = object()
        runtime_stats_access = object()
        document_artifact_builder = object()
        semantic_graph_schema_sync = object()
        knowledge_base_service = _FakeKnowledgeBaseService(
            ArtifactManifest.missing(manifest_path="manifest.json")
        )
        services = _CapturingServicesProvider(
            knowledge_base_service=knowledge_base_service,
            runtime_stats_access=runtime_stats_access,
        )
        build_pipeline = _CapturingBuildPipelineProvider(
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )
        graph_manager = SimpleNamespace(name="graph")
        data_module = SimpleNamespace(name="data")
        index_module = SimpleNamespace(name="index")
        infrastructure = SimpleNamespace(
            provide_neo4j_manager=lambda config, existing=None: existing or graph_manager,
            provide_data_module=(
                lambda config, neo4j_manager, existing=None: existing or data_module
            ),
            provide_index_module=lambda config, existing=None: existing or index_module,
            provide_artifact_manifest_store=(
                lambda config, existing=None: existing or manifest_store
            ),
            provide_document_artifact_cache=(
                lambda config, existing=None, *, manifest_store=None: (
                    existing or document_artifact_cache
                )
            ),
            provide_runtime_artifact_access=(
                lambda config, existing=None: existing or runtime_artifact_access
            ),
        )
        factory = BuildRuntimeFactory(
            provider=SimpleNamespace(
                infrastructure=infrastructure,
                build_pipeline=build_pipeline,
                services=services,
            )
        )

        runtime = factory.build(config=SimpleNamespace())

        self.assertIs(runtime.knowledge_base_service, knowledge_base_service)
        self.assertEqual(len(services.calls), 1)
        self.assertIs(services.calls[0]["manifest_store"], manifest_store)
        self.assertIs(services.calls[0]["runtime_artifact_access"], runtime_artifact_access)
        self.assertIs(services.calls[0]["runtime_stats_access"], runtime_stats_access)
        self.assertIs(services.calls[0]["document_artifact_builder"], document_artifact_builder)
        self.assertIs(services.calls[0]["semantic_graph_schema_sync"], semantic_graph_schema_sync)
        self.assertEqual(len(services.stats_calls), 1)
        self.assertEqual(len(build_pipeline.document_builder_calls), 1)
        self.assertIs(build_pipeline.document_builder_calls[0]["manifest_store"], manifest_store)
        self.assertIs(build_pipeline.document_builder_calls[0]["cache"], document_artifact_cache)
        self.assertEqual(len(build_pipeline.schema_sync_calls), 1)
        self.assertIs(build_pipeline.schema_sync_calls[0]["neo4j_manager"], graph_manager)
        self.assertIs(runtime.artifact_manifest, knowledge_base_service.artifact_manifest)
        self.assertFalse(hasattr(factory, "build_knowledge_base"))
        self.assertFalse(hasattr(factory, "rebuild_knowledge_base"))


class BuildBootstrapperTests(unittest.TestCase):
    def test_bootstrapper_composer_builds_default_components(self) -> None:
        runtime = SimpleNamespace(name="build")
        factory = SimpleNamespace(
            build=lambda config=None, **kwargs: runtime,
        )
        executor = _StubExecutor()
        composer = BuildBootstrapperComposer()

        components = composer.compose(
            provider=SimpleNamespace(),
            factory=factory,
            executor=executor,
        )

        self.assertIsInstance(components, BuildBootstrapperComponents)
        self.assertIs(components.factory, factory)
        self.assertIs(components.executor, executor)

    def test_public_bootstrapper_binds_components_from_composer_dataclass(self) -> None:
        provider = SimpleNamespace(name="provider")
        factory = SimpleNamespace(name="factory", build=lambda config=None, **kwargs: None)
        executor = SimpleNamespace(
            name="executor",
            build_knowledge_base=lambda runtime, **kwargs: runtime,
            rebuild_knowledge_base=lambda runtime, **kwargs: runtime,
        )
        calls: list[str] = []

        class _StubComposer:
            def compose(self, **kwargs):
                del kwargs
                calls.append("compose")
                return BuildBootstrapperComponents(
                    provider=provider,
                    factory=factory,
                    executor=executor,
                )

        bootstrapper = BuildBootstrapper(bootstrapper_composer=_StubComposer())

        self.assertEqual(calls, ["compose"])
        self.assertIs(bootstrapper.provider, provider)
        self.assertIs(bootstrapper.factory, factory)
        self.assertIs(bootstrapper.executor, executor)

    def test_build_still_returns_assembled_runtime_for_public_bootstrapper(self) -> None:
        runtime = SimpleNamespace(name="build")
        factory = SimpleNamespace(
            build_calls=[],
            build=lambda config=None, **kwargs: (
                factory.build_calls.append({"config": config, **kwargs}) or runtime
            ),
        )
        bootstrapper = BuildBootstrapper(
            provider=SimpleNamespace(),
            factory=factory,
        )

        result = bootstrapper.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result, runtime)
        self.assertEqual(len(factory.build_calls), 1)

    def test_build_can_compose_factory_and_executor(self) -> None:
        runtime = SimpleNamespace(name="build", build_prepared=False)
        factory = SimpleNamespace(
            build_calls=[],
            build=lambda config=None, **kwargs: (
                factory.build_calls.append({"config": config, **kwargs}) or runtime
            ),
        )
        executor = _StubExecutor()
        bootstrapper = BuildBootstrapper(
            provider=SimpleNamespace(),
            factory=factory,
            executor=executor,
        )

        build_result = bootstrapper.build(config=SimpleNamespace(name="cfg"))
        kb_result = bootstrapper.build_knowledge_base(runtime)

        self.assertIs(build_result, runtime)
        self.assertIs(kb_result, runtime)
        self.assertEqual(len(factory.build_calls), 1)
        self.assertEqual(len(executor.build_calls), 1)

    def test_build_knowledge_base_delegates_through_public_bootstrapper(self) -> None:
        runtime = SimpleNamespace(build_prepared=False)
        executor = _StubExecutor()
        bootstrapper = BuildBootstrapper(
            provider=SimpleNamespace(),
            factory=SimpleNamespace(build=lambda config=None, **kwargs: runtime),
            executor=executor,
        )

        result = bootstrapper.build_knowledge_base(runtime)

        self.assertIs(result, runtime)
        self.assertTrue(runtime.build_prepared)
        self.assertEqual(len(executor.build_calls), 1)

    def test_rebuild_knowledge_base_delegates_through_public_bootstrapper(self) -> None:
        runtime = SimpleNamespace(rebuild_prepared=False)
        executor = _StubExecutor()
        bootstrapper = BuildBootstrapper(
            provider=SimpleNamespace(),
            factory=SimpleNamespace(build=lambda config=None, **kwargs: runtime),
            executor=executor,
        )

        result = bootstrapper.rebuild_knowledge_base(runtime)

        self.assertIs(result, runtime)
        self.assertTrue(runtime.rebuild_prepared)
        self.assertEqual(len(executor.rebuild_calls), 1)


if __name__ == "__main__":
    unittest.main()
