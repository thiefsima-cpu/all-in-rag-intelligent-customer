from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.bootstrap_facade_support import (
    BuildBootstrapperInvocationAdapter,
    GraphBootstrapperInvocationAdapter,
    ServingBootstrapperInvocationAdapter,
)


class BootstrapFacadeSupportTests(unittest.TestCase):
    def test_build_invocation_adapter_delegates_to_factory_and_executor(self) -> None:
        runtime = SimpleNamespace(name="runtime", prepared=False)
        build_calls: list[dict] = []
        kb_calls: list[dict] = []
        rebuild_calls: list[dict] = []
        factory = SimpleNamespace(
            build=lambda config=None, **kwargs: (
                build_calls.append({"config": config, **kwargs}) or runtime
            )
        )
        executor = SimpleNamespace(
            build_knowledge_base=lambda runtime_arg, **kwargs: (
                kb_calls.append({"runtime": runtime_arg, **kwargs}) or runtime_arg
            ),
            rebuild_knowledge_base=lambda runtime_arg, **kwargs: (
                rebuild_calls.append({"runtime": runtime_arg, **kwargs}) or runtime_arg
            ),
        )
        adapter = BuildBootstrapperInvocationAdapter()

        build_result = adapter.build_runtime(factory=factory, config=SimpleNamespace(name="cfg"))
        kb_result = adapter.build_knowledge_base(executor=executor, runtime=runtime)
        rebuild_result = adapter.rebuild_knowledge_base(executor=executor, runtime=runtime)

        self.assertIs(build_result, runtime)
        self.assertIs(kb_result, runtime)
        self.assertIs(rebuild_result, runtime)
        self.assertEqual(len(build_calls), 1)
        self.assertEqual(len(kb_calls), 1)
        self.assertEqual(len(rebuild_calls), 1)

    def test_serving_invocation_adapter_delegates_to_lifecycle_service(self) -> None:
        runtime = SimpleNamespace(name="runtime", prepared=False)
        build_calls: list[dict] = []
        prepare_calls: list[dict] = []
        shared_prepare_calls: list[dict] = []
        lifecycle_service = SimpleNamespace(
            build_ready=lambda config=None, **kwargs: (
                build_calls.append({"config": config, **kwargs}) or runtime
            ),
            prepare=lambda runtime_arg, **kwargs: (
                prepare_calls.append({"runtime": runtime_arg, **kwargs}) or runtime_arg
            ),
            prepare_with_shared_runtime=lambda runtime_arg, **kwargs: (
                shared_prepare_calls.append({"runtime": runtime_arg, **kwargs}) or runtime_arg
            ),
        )
        adapter = ServingBootstrapperInvocationAdapter()

        build_result = adapter.build_serving_runtime(
            lifecycle_service=lifecycle_service,
            config=SimpleNamespace(name="cfg"),
            shared_runtime=SimpleNamespace(name="shared"),
        )
        prepare_result = adapter.prepare_serving_runtime(
            lifecycle_service=lifecycle_service,
            runtime=runtime,
        )
        shared_prepare_result = adapter.prepare_serving_runtime_with_shared_runtime(
            lifecycle_service=lifecycle_service,
            runtime=runtime,
            shared_runtime=SimpleNamespace(name="shared"),
        )

        self.assertIs(build_result, runtime)
        self.assertIs(prepare_result, runtime)
        self.assertIs(shared_prepare_result, runtime)
        self.assertEqual(len(build_calls), 1)
        self.assertEqual(len(prepare_calls), 1)
        self.assertEqual(len(shared_prepare_calls), 1)

    def test_graph_invocation_adapter_delegates_to_bootstrap_service(self) -> None:
        runtime = SimpleNamespace(name="runtime")
        build_calls: list[dict] = []
        bootstrap_service = SimpleNamespace(
            build=lambda config=None, **kwargs: (
                build_calls.append({"config": config, **kwargs}) or runtime
            )
        )
        adapter = GraphBootstrapperInvocationAdapter()

        result = adapter.build_system_runtime(
            bootstrap_service=bootstrap_service,
            config=SimpleNamespace(name="cfg"),
        )

        self.assertIs(result, runtime)
        self.assertEqual(len(build_calls), 1)


if __name__ == "__main__":
    unittest.main()
