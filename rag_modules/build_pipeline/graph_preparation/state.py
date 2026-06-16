"""Mutable state container for graph-preparation artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ...text_document import TextDocument
from .models import GraphNode


@dataclass(slots=True)
class GraphPreparationState:
    """Own the mutable in-memory state used during build-time preparation."""

    recipes: List[GraphNode] = field(default_factory=list)
    ingredients: List[GraphNode] = field(default_factory=list)
    cooking_steps: List[GraphNode] = field(default_factory=list)
    documents: List[TextDocument] = field(default_factory=list)
    chunks: List[TextDocument] = field(default_factory=list)
