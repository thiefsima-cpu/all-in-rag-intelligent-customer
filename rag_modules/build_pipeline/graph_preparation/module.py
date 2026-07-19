"""Facade for split graph-preparation services."""

from __future__ import annotations

import logging
from typing import cast

from ...contracts.graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats
from ...infra.neo4j import create_neo4j_driver
from ...kernel.documents import TextDocument
from ..ports import Neo4jDriverPort
from .chunker import RecipeDocumentChunker
from .document_builder import RecipeDocumentBuilder
from .domain_loader import DomainDocumentBuilder, DomainGraphDataLoader
from .loader import Neo4jGraphDataLoader
from .models import PreparedIngredientInput, PreparedStepInput
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
        driver: Neo4jDriverPort | None = None,
        state: GraphPreparationState | None = None,
        loader: Neo4jGraphDataLoader | DomainGraphDataLoader | None = None,
        document_builder: RecipeDocumentBuilder | DomainDocumentBuilder | None = None,
        chunker: RecipeDocumentChunker | None = None,
        statistics_service: GraphPreparationStatisticsService | None = None,
        domain_name: str = "recipe",
    ) -> None:
        self.database = database
        self.domain_name = str(domain_name or "recipe")
        self.state = state or GraphPreparationState()
        self.loader = loader or Neo4jGraphDataLoader()
        self.document_builder = document_builder or RecipeDocumentBuilder()
        self.chunker = chunker or RecipeDocumentChunker()
        self.statistics_service = statistics_service or GraphPreparationStatisticsService(
            domain_name=self.domain_name
        )
        self._owns_driver = False

        if driver is not None:
            self.driver = driver
        else:
            self.driver = cast(Neo4jDriverPort, create_neo4j_driver(uri, user, password))
            self._owns_driver = True
            with self.driver.session(database=self.database) as session:
                session.run("RETURN 1 AS test").single()
            logger.info("Neo4j connection established")

    @property
    def recipes(self) -> list[GraphNode]:
        return self.state.recipes

    @recipes.setter
    def recipes(self, value: list[GraphNode]) -> None:
        self.state.recipes = list(value or [])

    @property
    def entities(self) -> list[GraphNode]:
        return self.state.recipes

    @entities.setter
    def entities(self, value: list[GraphNode]) -> None:
        self.state.recipes = list(value or [])

    @property
    def ingredients(self) -> list[GraphNode]:
        return self.state.ingredients

    @ingredients.setter
    def ingredients(self, value: list[GraphNode]) -> None:
        self.state.ingredients = list(value or [])

    @property
    def cooking_steps(self) -> list[GraphNode]:
        return self.state.cooking_steps

    @cooking_steps.setter
    def cooking_steps(self, value: list[GraphNode]) -> None:
        self.state.cooking_steps = list(value or [])

    @property
    def documents(self) -> list[TextDocument]:
        return self.state.documents

    @documents.setter
    def documents(self, value: list[TextDocument]) -> None:
        self.state.documents = list(value or [])

    @property
    def chunks(self) -> list[TextDocument]:
        return self.state.chunks

    @chunks.setter
    def chunks(self, value: list[TextDocument]) -> None:
        self.state.chunks = list(value or [])

    def close(self) -> None:
        """Close the owned Neo4j driver if this module created it."""

        if self._owns_driver and self.driver:
            self.driver.close()
            logger.info("Neo4j connection closed.")

    def load_graph_data(self) -> GraphLoadCounts:
        """Load entities declared by the selected domain from Neo4j."""

        loaded = self.loader.load(self.driver, database=self.database)
        self.recipes = loaded.recipes
        self.ingredients = loaded.ingredients
        self.cooking_steps = loaded.cooking_steps
        return loaded.to_counts()

    def build_documents(self) -> list[TextDocument]:
        """Build domain documents with semantic metadata in batch mode."""

        logger.info("Building %s documents in batch mode...", self.domain_name)
        documents = self.document_builder.build(
            driver=self.driver,
            database=self.database,
            recipes=self.recipes,
        )
        self.documents = documents
        logger.info("Built %d %s documents.", len(documents), self.domain_name)
        return documents

    def build_recipe_documents(self) -> list[TextDocument]:
        """Compatibility alias for the retired recipe-specific build port."""

        return self.build_documents()

    def _build_recipe_document(
        self,
        *,
        recipe: GraphNode,
        ingredients: list[PreparedIngredientInput],
        steps: list[PreparedStepInput],
    ) -> TextDocument:
        recipe_builder = cast(RecipeDocumentBuilder, self.document_builder)
        return recipe_builder.build_document(
            recipe=recipe,
            ingredients=ingredients,
            steps=steps,
        )

    def chunk_documents(self, chunk_size: int = 500, chunk_overlap: int = 50) -> list[TextDocument]:
        """Split domain documents into retrieval chunks."""

        logger.info(
            "Chunking domain documents with chunk_size=%d chunk_overlap=%d",
            chunk_size,
            chunk_overlap,
        )
        if not self.documents:
            raise ValueError("Build domain documents before chunking.")

        chunks = self.chunker.chunk(
            self.documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.chunks = chunks
        logger.info("Chunking complete: generated %d chunks.", len(chunks))
        return chunks

    def get_statistics(self) -> GraphPreparationStats:
        """Return dataset statistics for diagnostics and UI output."""

        return self.statistics_service.build(self.state)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
