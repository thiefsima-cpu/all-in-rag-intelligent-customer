from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.bootstrap import BuildBootstrapper
from rag_modules.app.composition.bootstrapper_composer import (
    BuildBootstrapperComponents,
    BuildBootstrapperComposer,
)
from rag_modules.app.composition.build_runtime_factory import BuildRuntimeFactory


class _StubAssembler:
    def __init__(self, runtime):
        self.runtime = runtime
        self.calls: list[dict] = []

    def assemble(self, config=None, **kwargs):
        self.calls.append({"config": config, **kwargs})
        return self.runtime


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
    def test_build_only_assembles_runtime(self) -> None:
        runtime = SimpleNamespace(build_prepared=False)
        assembler = _StubAssembler(runtime)
        factory = BuildRuntimeFactory(
            provider=SimpleNamespace(),
            assembler=assembler,
        )

        result = factory.build(config=SimpleNamespace(name="cfg"))

        self.assertIs(result, runtime)
        self.assertEqual(len(assembler.calls), 1)
        self.assertFalse(runtime.build_prepared)
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
