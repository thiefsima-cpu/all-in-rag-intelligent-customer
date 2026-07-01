"""
Import derived semantic recipe schema into Neo4j.

This script is useful when documents are already cached and you only want to
refresh semantic graph nodes/relationships.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.build_pipeline.document_artifacts import build_or_load_documents
from rag_modules.build_pipeline.graph_data_preparation import GraphDataPreparationModule
from rag_modules.configuration import load_config
from rag_modules.infra.semantic_graph_writer import SemanticGraphSchemaWriter


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    storage = config.storage
    data_module = GraphDataPreparationModule(
        uri=storage.neo4j_uri,
        user=storage.neo4j_user,
        password=storage.neo4j_password,
        database=storage.neo4j_database,
    )
    try:
        data_module.load_graph_data()
        build_or_load_documents(data_module, config)
        writer = SemanticGraphSchemaWriter(config)
        stats = writer.persist_from_documents(data_module.documents)
    finally:
        data_module.close()

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(
            "semantic schema imported: "
            f"recipes={stats.get('recipes', 0)} "
            f"nodes={stats.get('nodes', 0)} "
            f"relationships={stats.get('relationships', 0)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
