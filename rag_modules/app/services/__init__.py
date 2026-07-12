"""Runtime diagnostics and shutdown services owned by application composition."""

from .runtime_diagnostics_service import RuntimeDiagnosticsService
from .runtime_shutdown_service import RuntimeShutdownService

__all__ = ["RuntimeDiagnosticsService", "RuntimeShutdownService"]
