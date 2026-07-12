from __future__ import annotations

from pathlib import Path


def test_aggregate_runtime_contract_modules_are_deleted() -> None:
    assert not Path("rag_modules/runtime_contracts.py").exists()
    assert not Path("rag_modules/app/runtime_contracts.py").exists()


def test_each_consumer_owns_its_ports() -> None:
    from rag_modules.application.ports import QueryTracerPort
    from rag_modules.build_pipeline.ports import (
        GraphDataModulePort as BuildGraphDataModulePort,
    )
    from rag_modules.build_pipeline.ports import (
        VectorIndexModulePort as BuildVectorIndexModulePort,
    )
    from rag_modules.generation.ports import LLMClientPort as GenerationLLMClientPort
    from rag_modules.graph.ports import Neo4jDriverPort as GraphNeo4jDriverPort
    from rag_modules.infra.milvus.ports import EmbeddingClientPort
    from rag_modules.query_understanding.ports import LLMClientPort as PlanningLLMClientPort
    from rag_modules.retrieval.ports import RerankClientPort
    from rag_modules.routing.ports import GraphRAGRetrievalPort, HybridRetrievalPort
    from rag_modules.runtime.ports import GraphDataModulePort as RuntimeGraphDataModulePort

    assert QueryTracerPort.__module__ == "rag_modules.application.ports"
    assert BuildGraphDataModulePort.__module__ == "rag_modules.build_pipeline.ports"
    assert BuildVectorIndexModulePort.__module__ == "rag_modules.build_pipeline.ports"
    assert GenerationLLMClientPort.__module__ == "rag_modules.generation.ports"
    assert GraphNeo4jDriverPort.__module__ == "rag_modules.graph.ports"
    assert EmbeddingClientPort.__module__ == "rag_modules.infra.milvus.ports"
    assert PlanningLLMClientPort.__module__ == "rag_modules.query_understanding.ports"
    assert RerankClientPort.__module__ == "rag_modules.retrieval.ports"
    assert GraphRAGRetrievalPort.__module__ == "rag_modules.routing.ports"
    assert HybridRetrievalPort.__module__ == "rag_modules.routing.ports"
    assert RuntimeGraphDataModulePort.__module__ == "rag_modules.runtime.ports"
