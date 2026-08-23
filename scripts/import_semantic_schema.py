"""
Import the selected domain pack's derived semantic schema into Neo4j.

This script is useful when documents are already cached and you only want to
refresh semantic graph nodes/relationships.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.build_pipeline.document_artifacts import build_or_load_documents
from rag_modules.build_pipeline.graph_preparation import (
    GraphDataPreparationModule,
    create_domain_build_collaborators,
)
from rag_modules.configuration import load_config
from rag_modules.domains import get_domain_pack
from rag_modules.infra.neo4j import create_neo4j_driver


def main() -> int:
    config = load_config()
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    storage = config.storage
    domain_pack = get_domain_pack(config.domain.name)
    if not domain_pack.semantic_schema_enabled:
        raise ValueError(
            f"Domain pack {domain_pack.name!r} does not define a derived semantic schema."
        )
    writer_factory = domain_pack.semantic_graph_writer_factory
    if writer_factory is None:
        raise ValueError(f"Domain pack {domain_pack.name!r} has no semantic graph writer.")
    loader, document_builder, chunker = create_domain_build_collaborators(domain_pack)
    data_module = GraphDataPreparationModule(
        uri=storage.neo4j_uri,
        user=storage.neo4j_user,
        password=storage.neo4j_password,
        database=storage.neo4j_database,
        loader=loader,
        document_builder=document_builder,
        chunker=chunker,
        domain_name=domain_pack.name,
        domain_version=domain_pack.version,
        data_view=domain_pack.build_data_view,
    )
    try:
        data_module.load_graph_data()
        build_or_load_documents(data_module, config)
        writer = writer_factory(config, driver_factory=create_neo4j_driver)
        stats = getattr(writer, "persist_from_documents")(data_module.documents)
    finally:
        data_module.close()

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(
            "semantic schema imported: "
            f"{domain_pack.semantic_schema_count_field}="
            f"{stats.get(domain_pack.semantic_schema_count_field, 0)} "
            f"nodes={stats.get('nodes', 0)} "
            f"relationships={stats.get('relationships', 0)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
