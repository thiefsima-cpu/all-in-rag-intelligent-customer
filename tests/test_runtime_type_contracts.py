from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    VectorIndexModulePort,
)
from rag_modules.runtime import QueryAnalysis, ensure_optional_query_analysis
from rag_modules.text_document import TextDocument


class _GraphDataFake:
    def __init__(self) -> None:
        self.documents = [TextDocument(content="doc")]
        self.chunks = [TextDocument(content="chunk")]
        self.closed = False

    def load_graph_data(self) -> dict[str, object]:
        return {"recipes": 1}

    def build_recipe_documents(self) -> list[TextDocument]:
        return list(self.documents)

    def chunk_documents(self, chunk_size: int = 500, chunk_overlap: int = 50) -> list[TextDocument]:
        del chunk_size, chunk_overlap
        return list(self.chunks)

    def get_statistics(self) -> dict[str, object]:
        return {"total_chunks": len(self.chunks)}

    def close(self) -> None:
        self.closed = True


class _VectorIndexFake:
    def __init__(self) -> None:
        self.collection_name = "recipes"
        self.closed = False

    def has_collection(self, collection_name: str | None = None) -> bool:
        return bool(collection_name or self.collection_name)

    def load_collection(self, collection_name: str | None = None) -> bool:
        self.collection_name = collection_name or self.collection_name
        return True

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool:
        self.collection_name = collection_name or self.collection_name
        return bool(chunks)

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        del filters
        return [{"text": query, "score": float(k), "metadata": {}}]

    def get_collection_stats(self, collection_name: str | None = None) -> dict[str, object]:
        return {"collection_name": collection_name or self.collection_name}

    def delete_collection(self, collection_name: str | None = None) -> bool:
        del collection_name
        return True

    def close(self) -> None:
        self.closed = True


class _Neo4jManagerFake:
    def __init__(self) -> None:
        self.driver = SimpleNamespace(name="driver")
        self.closed = False

    def session(self, **kwargs: object) -> object:
        return {"kwargs": kwargs}

    def close(self) -> None:
        self.closed = True


def _uses_graph_data_port(port: GraphDataModulePort) -> dict[str, object]:
    return port.get_statistics()


def _uses_vector_index_port(port: VectorIndexModulePort) -> list[dict[str, object]]:
    return port.similarity_search("tofu", k=2)


def _uses_neo4j_port(port: Neo4jManagerPort) -> object:
    return port.driver


class RuntimeTypeContractTests(unittest.TestCase):
    def test_runtime_protocols_accept_existing_structural_shapes(self) -> None:
        self.assertEqual(_uses_graph_data_port(_GraphDataFake()), {"total_chunks": 1})
        self.assertEqual(_uses_vector_index_port(_VectorIndexFake())[0]["text"], "tofu")
        self.assertEqual(getattr(_uses_neo4j_port(_Neo4jManagerFake()), "name"), "driver")

    def test_optional_analysis_normalizer_preserves_none(self) -> None:
        self.assertIsNone(ensure_optional_query_analysis(None))

    def test_optional_analysis_normalizer_accepts_mapping(self) -> None:
        analysis = ensure_optional_query_analysis(
            {
                "query_complexity": 0.8,
                "relationship_intensity": 0.7,
                "recommended_strategy": "graph_rag",
            }
        )

        self.assertIsInstance(analysis, QueryAnalysis)
        self.assertEqual(analysis.strategy_name, "graph_rag")


if __name__ == "__main__":
    unittest.main()
