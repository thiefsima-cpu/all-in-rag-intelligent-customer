"""Application facade backed by explicit build and serving composition roots."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from ..configuration.models import GraphRAGConfig

from ..artifacts import ArtifactManifest
from .assembly import ApplicationAssembler, ApplicationContainer
from .contracts import (
    QuestionAnswerer,
    RuntimeComponentProvider,
    SystemFacadeSupportProtocol,
    SystemOperationsProtocol,
)
from .services.answer_models import QuestionAnswerResponse, QuestionAnswerResult

if TYPE_CHECKING:
    from .bootstrap import BuildBootstrapper, GraphRAGBootstrapper, ServingBootstrapper
    from .runtime_state import BuildRuntime, ServingRuntime
    from .runtime_view import SystemRuntime


class AdvancedGraphRAGSystem:
    """Stable application surface for API service endpoints."""

    def __init__(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        provider: Optional[RuntimeComponentProvider] = None,
        bootstrapper: Optional[GraphRAGBootstrapper] = None,
        build_bootstrapper: Optional[BuildBootstrapper] = None,
        serving_bootstrapper: Optional[ServingBootstrapper] = None,
        system_composer=None,
        assembler: ApplicationAssembler | None = None,
        container: ApplicationContainer | None = None,
    ):
        container = container or (assembler or ApplicationAssembler(
            system_composer=system_composer,
        )).assemble(
            config=config,
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        self.config = container.config
        self.provider = container.provider
        self.bootstrapper = container.bootstrapper
        self.build_bootstrapper = container.build_bootstrapper
        self.serving_bootstrapper = container.serving_bootstrapper
        self.operations_service: SystemOperationsProtocol = container.operations_service
        self.answering_service: QuestionAnswerer = container.answering_service
        self.facade_support: SystemFacadeSupportProtocol = container.facade_support

    def initialize_build_runtime(
        self,
        progress=None,
        *,
        neo4j_manager=None,
    ) -> BuildRuntime:
        return self.operations_service.initialize_build_runtime(
            progress=progress,
            neo4j_manager=neo4j_manager,
        )

    def initialize_serving_runtime(
        self,
        progress=None,
        *,
        query_tracer=None,
        neo4j_manager=None,
    ) -> ServingRuntime:
        return self.operations_service.initialize_serving_runtime(
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )

    def initialize_system(
        self,
        progress=None,
        *,
        query_tracer=None,
        neo4j_manager=None,
    ) -> SystemRuntime:
        return self.operations_service.initialize_system(
            progress=progress,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
        )

    def is_initialized(self) -> bool:
        return self.operations_service.is_initialized()

    def is_build_initialized(self) -> bool:
        return self.operations_service.is_build_initialized()

    def is_serving_initialized(self) -> bool:
        return self.operations_service.is_serving_initialized()

    def build_knowledge_base(self, progress=None) -> None:
        self.operations_service.build_knowledge_base(progress=progress)

    def rebuild_knowledge_base(self, progress=None) -> None:
        self.operations_service.rebuild_knowledge_base(progress=progress)

    def refresh_serving_runtime(self, progress=None, *, force: bool = True):
        return self.operations_service.refresh_serving_runtime(
            progress=progress,
            force=force,
        )

    def answer_question(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResult:
        return self.answering_service.answer_question(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ) -> QuestionAnswerResponse:
        return self.answering_service.answer_question_response(
            question=question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=message_callback,
            chunk_callback=chunk_callback,
        )

    def ask_question_with_routing(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
    ):
        result = self.answer_question(
            question,
            stream=stream,
            explain_routing=explain_routing,
            message_callback=print,
            chunk_callback=lambda chunk: print(chunk, end="", flush=True),
        )
        return result.answer, result.analysis

    def collect_system_stats(self) -> dict:
        return self.operations_service.collect_system_stats()

    def collect_startup_diagnostics(self, mode: str):
        return self.operations_service.collect_startup_diagnostics(mode)

    def close(self) -> None:
        self.operations_service.close()

    @property
    def runtime(self) -> SystemRuntime:
        return self.facade_support.runtime

    @property
    def build_runtime(self) -> Optional[BuildRuntime]:
        return self.facade_support.build_runtime

    @property
    def serving_runtime(self) -> Optional[ServingRuntime]:
        return self.facade_support.serving_runtime

    @property
    def infrastructure(self) -> Any:
        return self.facade_support.infrastructure

    @property
    def retrieval(self) -> Any:
        return self.facade_support.retrieval

    @property
    def services(self) -> Any:
        return self.facade_support.services

    def __getattr__(self, name: str) -> Any:
        resolver = getattr(self.facade_support, "resolve_legacy_attribute", None)
        if resolver is None:
            raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")
        return resolver(self, name)

    def __dir__(self) -> list[str]:
        legacy_dir = getattr(self.facade_support, "legacy_dir", None)
        if legacy_dir is None:
            return object.__dir__(self)
        return legacy_dir(self)

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.facade_support.artifact_manifest

    @property
    def artifacts_ready(self) -> bool:
        return self.facade_support.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self.facade_support.system_ready
