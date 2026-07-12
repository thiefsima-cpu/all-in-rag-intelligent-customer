"""Higher-level application contracts that hide deeper assembly subpackages."""

from __future__ import annotations

from ..application.answering.answer_models import QuestionAnswerer
from .composition.contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
    ServingRuntimePreparerProtocol,
    SystemFacadeSupportProtocol,
    SystemOperationsProtocol,
)
from .providers import RuntimeComponentProvider

__all__ = [
    "BuildRuntimeExecutorProtocol",
    "BuildRuntimeFactoryProtocol",
    "QuestionAnswerer",
    "RuntimeComponentProvider",
    "ServingRuntimeFactoryProtocol",
    "ServingRuntimeLifecycleServiceProtocol",
    "ServingRuntimePreparerProtocol",
    "SystemFacadeSupportProtocol",
    "SystemOperationsProtocol",
]
