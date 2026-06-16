"""Application-level interactive session adapter over the composed runtime services."""

from __future__ import annotations

from ..application_protocol import GraphRAGApplication
from .contracts import SystemInteractiveProtocol, SystemOperationsProtocol


class SystemInteractiveService(SystemInteractiveProtocol):
    """Run the interactive CLI against the application contract."""

    def __init__(self, *, operations_service: SystemOperationsProtocol) -> None:
        self.operations_service = operations_service

    def run_interactive(
        self,
        *,
        system: GraphRAGApplication,
        input_func=input,
        output_func=print,
    ) -> None:
        self.operations_service.require_ready()
        from ...interfaces.cli_console import InteractiveCliConsole

        console = InteractiveCliConsole(
            system=system,
            input_func=input_func,
            output_func=output_func,
        )
        try:
            console.run()
        finally:
            self.operations_service.close()


__all__ = ["SystemInteractiveService"]
