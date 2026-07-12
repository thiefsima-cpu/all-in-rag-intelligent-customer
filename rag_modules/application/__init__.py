"""Pure application use cases, ports, and DTOs.

Concrete runtime construction belongs to ``rag_modules.app.composition`` and
its providers.  Modules in this package receive their collaborators through
constructors and do not select retrieval, generation, or build implementations.
"""

__all__ = ["answering", "knowledge_base", "ports"]
