from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.assembly import (
    ApplicationAssembler,
    ApplicationContainer,
    assemble_application_container,
    create_application_system,
)
from rag_modules.app.system import AdvancedGraphRAGSystem
from rag_modules.configuration.testing import build_test_config


def _container_stub(config=None) -> ApplicationContainer:
    resolved_config = config or build_test_config()
    return ApplicationContainer(
        config=resolved_config,
        provider=SimpleNamespace(name="provider"),
        bootstrapper=SimpleNamespace(name="bootstrapper"),
        build_bootstrapper=SimpleNamespace(name="build-bootstrapper"),
        serving_bootstrapper=SimpleNamespace(name="serving-bootstrapper"),
        operations_service=SimpleNamespace(
            initialize_build_runtime=lambda **kwargs: kwargs,
            initialize_serving_runtime=lambda **kwargs: kwargs,
            initialize_system=lambda **kwargs: kwargs,
            is_initialized=lambda: False,
            is_build_initialized=lambda: False,
            is_serving_initialized=lambda: False,
            build_knowledge_base=lambda **kwargs: None,
            rebuild_knowledge_base=lambda **kwargs: None,
            collect_system_stats=lambda: {"ready": False},
            collect_startup_diagnostics=lambda mode: SimpleNamespace(
                mode=mode,
                to_dict=lambda: {"mode": mode},
            ),
            close=lambda: None,
        ),
        answering_service=SimpleNamespace(
            answer_question=lambda **kwargs: SimpleNamespace(answer="ok", analysis=None),
            answer_question_response=lambda **kwargs: SimpleNamespace(
                to_dict=lambda: {"summary": {"answer": "ok"}}
            ),
        ),
        facade_support=SimpleNamespace(
            runtime=SimpleNamespace(),
            build_runtime=None,
            serving_runtime=None,
            infrastructure=SimpleNamespace(),
            retrieval=SimpleNamespace(),
            services=SimpleNamespace(),
            artifact_manifest=SimpleNamespace(),
            artifacts_ready=False,
            system_ready=False,
        ),
    )


class _StubSystemComposer:
    def __init__(self, container: ApplicationContainer) -> None:
        self.container = container
        self.calls: list[dict] = []

    def compose(self, **kwargs):
        self.calls.append(dict(kwargs))
        return SimpleNamespace(
            config=self.container.config,
            provider=self.container.provider,
            bootstrapper=self.container.bootstrapper,
            build_bootstrapper=self.container.build_bootstrapper,
            serving_bootstrapper=self.container.serving_bootstrapper,
            operations_service=self.container.operations_service,
            answering_service=self.container.answering_service,
            facade_support=self.container.facade_support,
        )


class ApplicationAssemblyTests(unittest.TestCase):
    def test_application_assembler_wraps_internal_composer_in_small_container(self) -> None:
        container = _container_stub()
        composer = _StubSystemComposer(container)

        assembled = ApplicationAssembler(system_composer=composer).assemble(config=container.config)

        self.assertIsInstance(assembled, ApplicationContainer)
        self.assertIs(assembled.config, container.config)
        self.assertEqual(len(composer.calls), 1)

    def test_assemble_application_container_uses_single_entry(self) -> None:
        container = _container_stub()
        composer = _StubSystemComposer(container)

        assembled = assemble_application_container(
            config=container.config,
            assembler=ApplicationAssembler(system_composer=composer),
        )

        self.assertIs(assembled.provider, container.provider)
        self.assertIs(assembled.facade_support, container.facade_support)

    def test_create_application_system_builds_system_from_container(self) -> None:
        container = _container_stub()
        composer = _StubSystemComposer(container)

        system = create_application_system(
            config=container.config,
            assembler=ApplicationAssembler(system_composer=composer),
        )

        self.assertIsInstance(system, AdvancedGraphRAGSystem)
        self.assertIs(system.provider, container.provider)
        self.assertEqual(system.answer_question("hi").answer, "ok")
        self.assertNotIn("run_interactive", AdvancedGraphRAGSystem.__dict__)
        self.assertNotIn("interactive_service", system.__dict__)

    def test_system_accepts_prebuilt_application_container(self) -> None:
        container = _container_stub()

        system = AdvancedGraphRAGSystem(container=container)

        self.assertIs(system.provider, container.provider)
        self.assertEqual(system.collect_system_stats()["ready"], False)


if __name__ == "__main__":
    unittest.main()
