"""Single assembly entry for GraphRAG application systems."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..configuration import get_default_config
from ..configuration.models import GraphRAGConfig
from .composition import AdvancedGraphRAGSystemComposer
from .contracts import (
    QuestionAnswerer,
    RuntimeComponentProvider,
    SystemFacadeSupportProtocol,
    SystemOperationsProtocol,
)

if TYPE_CHECKING:
    from .bootstrap import BuildBootstrapper, GraphRAGBootstrapper, ServingBootstrapper
    from .system import AdvancedGraphRAGSystem


@dataclass(frozen=True)
class ApplicationContainer:
    """Small application-facing container over the resolved system collaborators."""

    config: GraphRAGConfig
    provider: RuntimeComponentProvider
    bootstrapper: GraphRAGBootstrapper
    build_bootstrapper: BuildBootstrapper
    serving_bootstrapper: ServingBootstrapper
    operations_service: SystemOperationsProtocol
    answering_service: QuestionAnswerer
    facade_support: SystemFacadeSupportProtocol


class ApplicationAssembler:
    """Single assembly entry that hides composer/provider internals from callers."""

    def __init__(
        self,
        *,
        system_composer: AdvancedGraphRAGSystemComposer | None = None,
    ) -> None:
        self.system_composer = system_composer or AdvancedGraphRAGSystemComposer()

    def assemble(
        self,
        *,
        config: GraphRAGConfig | None = None,
        provider: RuntimeComponentProvider | None = None,
        bootstrapper: GraphRAGBootstrapper | None = None,
        build_bootstrapper: BuildBootstrapper | None = None,
        serving_bootstrapper: ServingBootstrapper | None = None,
    ) -> ApplicationContainer:
        components = self.system_composer.compose(
            config=config or get_default_config(),
            provider=provider,
            bootstrapper=bootstrapper,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
        )
        return ApplicationContainer(
            config=components.config,
            provider=components.provider,
            bootstrapper=components.bootstrapper,
            build_bootstrapper=components.build_bootstrapper,
            serving_bootstrapper=components.serving_bootstrapper,
            operations_service=components.operations_service,
            answering_service=components.answering_service,
            facade_support=components.facade_support,
        )


def assemble_application_container(
    *,
    config: GraphRAGConfig | None = None,
    provider: RuntimeComponentProvider | None = None,
    bootstrapper: GraphRAGBootstrapper | None = None,
    build_bootstrapper: BuildBootstrapper | None = None,
    serving_bootstrapper: ServingBootstrapper | None = None,
    assembler: ApplicationAssembler | None = None,
) -> ApplicationContainer:
    """Assemble a small application container from the default internal wiring."""

    return (assembler or ApplicationAssembler()).assemble(
        config=config,
        provider=provider,
        bootstrapper=bootstrapper,
        build_bootstrapper=build_bootstrapper,
        serving_bootstrapper=serving_bootstrapper,
    )


def create_application_system(
    *,
    config: GraphRAGConfig | None = None,
    provider: RuntimeComponentProvider | None = None,
    bootstrapper: GraphRAGBootstrapper | None = None,
    build_bootstrapper: BuildBootstrapper | None = None,
    serving_bootstrapper: ServingBootstrapper | None = None,
    assembler: ApplicationAssembler | None = None,
) -> "AdvancedGraphRAGSystem":
    """Create the application system through the canonical single assembly entry."""

    from .system import AdvancedGraphRAGSystem

    container = assemble_application_container(
        config=config,
        provider=provider,
        bootstrapper=bootstrapper,
        build_bootstrapper=build_bootstrapper,
        serving_bootstrapper=serving_bootstrapper,
        assembler=assembler,
    )
    return AdvancedGraphRAGSystem(container=container)


__all__ = [
    "ApplicationAssembler",
    "ApplicationContainer",
    "assemble_application_container",
    "create_application_system",
]
