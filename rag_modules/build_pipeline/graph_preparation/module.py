"""Facade for split graph-preparation services."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from neo4j import Driver, GraphDatabase

from ...text_document import TextDocument
from .chunker import RecipeDocumentChunker
from .document_builder import RecipeDocumentBuilder
from .loader import Neo4jGraphDataLoader
from .models import GraphNode
from .state import GraphPreparationState
from .statistics import GraphPreparationStatisticsService

logger = logging.getLogger(__name__)


class GraphDataPreparationModule:
    """Load recipe graph data from Neo4j and materialize recipe documents."""

    def __init__(
        self,
        uri: str = "",
        user: str = "",
        password: str = "",
        database: str = "neo4j",
        *,
        driver: Optional[Driver] = None,
        state: GraphPreparationState | None = None,
        loader: Neo4jGraphDataLoader | None = None,
        document_builder: RecipeDocumentBuilder | None = None,
        chunker: RecipeDocumentChunker | None = None,
        statistics_service: GraphPreparationStatisticsService | None = None,
    ):
        self.database = database
        self.state = state or GraphPreparationState()
        self.loader = loader or Neo4jGraphDataLoader()
        self.document_builder = document_builder or RecipeDocumentBuilder()
        self.chunker = chunker or RecipeDocumentChunker()
        self.statistics_service = statistics_service or GraphPreparationStatisticsService()
        self._owns_driver = False

        if driver is not None:
            self.driver = driver
        else:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            self._owns_driver = True
            with self.driver.session(database=self.database) as session:
                session.run("RETURN 1 AS test").single()
            logger.info("Connected to Neo4j database: %s", uri)

    @property
    def recipes(self) -> List[GraphNode]:
        return self.state.recipes

    @recipes.setter
    def recipes(self, value: List[GraphNode]) -> None:
        self.state.recipes = list(value or [])

    @property
    def ingredients(self) -> List[GraphNode]:
        return self.state.ingredients

    @ingredients.setter
    def ingredients(self, value: List[GraphNode]) -> None:
        self.state.ingredients = list(value or [])

    @property
    def cooking_steps(self) -> List[GraphNode]:
        return self.state.cooking_steps

    @cooking_steps.setter
    def cooking_steps(self, value: List[GraphNode]) -> None:
        self.state.cooking_steps = list(value or [])

    @property
    def documents(self) -> List[TextDocument]:
        return self.state.documents

    @documents.setter
    def documents(self, value: List[TextDocument]) -> None:
        self.state.documents = list(value or [])

    @property
    def chunks(self) -> List[TextDocument]:
        return self.state.chunks

    @chunks.setter
    def chunks(self, value: List[TextDocument]) -> None:
        self.state.chunks = list(value or [])

    def close(self) -> None:
        """Close the owned Neo4j driver if this module created it."""

        if self._owns_driver and self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed.")

    def load_graph_data(self) -> Dict[str, Any]:
        """Load recipes, ingredients, and cooking steps from Neo4j."""

        loaded = self.loader.load(self.driver, database=self.database)
        self.recipes = loaded.recipes
        self.ingredients = loaded.ingredients
        self.cooking_steps = loaded.cooking_steps
        return loaded.to_counts()

    def build_recipe_documents(self) -> List[TextDocument]:
        """Build recipe documents with semantic tags in batch mode."""

        logger.info("Building recipe documents in batch mode...")
        documents = self.document_builder.build(
            driver=self.driver,
            database=self.database,
            recipes=self.recipes,
        )
        self.documents = documents
        logger.info("Built %d recipe documents.", len(documents))
        return documents

    def _build_recipe_document(
        self,
        *,
        recipe: GraphNode,
        raw_ingredients: List[Dict[str, Any]],
        raw_steps: List[Dict[str, Any]],
    ) -> TextDocument:
        return self.document_builder.build_document(
            recipe=recipe,
            raw_ingredients=raw_ingredients,
            raw_steps=raw_steps,
        )

    def chunk_documents(self, chunk_size: int = 500, chunk_overlap: int = 50) -> List[TextDocument]:
        """Split recipe documents into retrieval chunks."""

        logger.info(
            "Chunking recipe documents with chunk_size=%d chunk_overlap=%d",
            chunk_size,
            chunk_overlap,
        )
        if not self.documents:
            raise ValueError("Build recipe documents before chunking.")

        chunks = self.chunker.chunk(
            self.documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.chunks = chunks
        logger.info("Chunking complete: generated %d chunks.", len(chunks))
        return chunks

    def get_statistics(self) -> Dict[str, Any]:
        """Return dataset statistics for diagnostics and UI output."""

        return self.statistics_service.build(self.state)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
