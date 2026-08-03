from __future__ import annotations

from importlib import import_module


def test_graph_preparation_dtos_are_owned_by_contracts() -> None:
    contracts = import_module("rag_modules.contracts.graph_preparation")

    graph_node = contracts.GraphNode(
        node_id=7,
        labels=["Recipe", ""],
        name=None,
        properties={"difficulty": "easy"},
    )
    counts = contracts.GraphLoadCounts(
        total_entities=6,
        entity_groups={"primary": 1, "related": 5},
    )
    stats = contracts.GraphPreparationStats(
        domain_name="customer_service",
        total_entities=1,
        total_chunks=4,
    )

    assert contracts.GraphNode.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphLoadCounts.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphPreparationStats.__module__ == "rag_modules.contracts.graph_preparation"
    assert graph_node.node_id == "7"
    assert graph_node.labels == ["Recipe"]
    assert graph_node.name == ""
    assert counts.to_dict() == {
        "total_entities": 6,
        "entity_groups": {"primary": 1, "related": 5},
    }
    assert stats.to_dict() == {
        "domain_name": "customer_service",
        "total_entities": 1,
        "total_documents": 0,
        "total_chunks": 4,
        "domain_metrics": {},
    }


def test_contract_package_exports_graph_preparation_dtos() -> None:
    contracts = import_module("rag_modules.contracts")

    assert contracts.GraphNode.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphLoadCounts.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphPreparationStats.__module__ == "rag_modules.contracts.graph_preparation"
    assert {"GraphNode", "GraphLoadCounts", "GraphPreparationStats"} <= set(contracts.__all__)


def test_build_pipeline_no_longer_exports_contract_owned_dtos() -> None:
    build_pipeline = import_module("rag_modules.build_pipeline")
    graph_preparation = import_module("rag_modules.build_pipeline.graph_preparation")
    models = import_module(
        ".".join(("rag_modules", "build_pipeline", "graph_preparation", "models"))
    )
    statistics = import_module(
        ".".join(("rag_modules", "build_pipeline", "graph_preparation", "statistics"))
    )

    assert not hasattr(build_pipeline, "GraphNode")
    assert "GraphNode" not in build_pipeline.__all__
    assert not hasattr(graph_preparation, "GraphNode")
    assert "GraphNode" not in graph_preparation.__all__
    assert not hasattr(models, "GraphNode")
    assert not hasattr(models, "GraphLoadCounts")
    assert not hasattr(statistics, "GraphPreparationStats")
