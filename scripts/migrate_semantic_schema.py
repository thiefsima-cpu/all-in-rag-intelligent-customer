"""
Maintain semantic schema versions in Neo4j.

Default mode reports semantic schema versions. Use --cleanup-stale to remove
semantic relationships and orphan semantic nodes whose schemaVersion does not
match the current code version.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from neo4j import GraphDatabase

from rag_modules.configuration import load_config
from rag_modules.semantic_schema import SEMANTIC_SCHEMA_VERSION


def _run(dry_run: bool, cleanup_stale: bool) -> dict:
    config = load_config()
    storage = config.storage
    driver = GraphDatabase.driver(
        storage.neo4j_uri,
        auth=(storage.neo4j_user, storage.neo4j_password),
    )
    try:
        with driver.session(database=storage.neo4j_database) as session:
            report = session.execute_read(_report_versions)
            report["current_schema_version"] = SEMANTIC_SCHEMA_VERSION
            report["dry_run"] = dry_run
            if cleanup_stale:
                if dry_run:
                    report["cleanup"] = session.execute_read(_stale_counts)
                else:
                    report["cleanup"] = session.execute_write(_cleanup_stale)
            return report
    finally:
        driver.close()


def _report_versions(tx) -> dict:
    query = """
    MATCH ()-[r]->()
    WHERE r.createdFrom = 'semantic_schema'
    RETURN coalesce(r.schemaVersion, 'unknown') AS version, count(r) AS relationships
    ORDER BY version
    """
    relationship_versions = [
        {"version": row["version"], "relationships": row["relationships"]} for row in tx.run(query)
    ]
    node_query = """
    MATCH (n)
    WHERE n.createdFrom = 'semantic_schema'
    RETURN coalesce(n.schemaVersion, 'unknown') AS version, count(n) AS nodes
    ORDER BY version
    """
    node_versions = [
        {"version": row["version"], "nodes": row["nodes"]} for row in tx.run(node_query)
    ]
    return {"relationship_versions": relationship_versions, "node_versions": node_versions}


def _stale_counts(tx) -> dict:
    rel_query = """
    MATCH ()-[r]->()
    WHERE r.createdFrom = 'semantic_schema' AND coalesce(r.schemaVersion, '') <> $version
    RETURN count(r) AS relationships
    """
    node_query = """
    MATCH (n)
    WHERE n.createdFrom = 'semantic_schema' AND coalesce(n.schemaVersion, '') <> $version
    RETURN count(n) AS nodes
    """
    rels = tx.run(rel_query, version=SEMANTIC_SCHEMA_VERSION).single()["relationships"]
    nodes = tx.run(node_query, version=SEMANTIC_SCHEMA_VERSION).single()["nodes"]
    return {"stale_relationships": rels, "stale_nodes": nodes}


def _cleanup_stale(tx) -> dict:
    counts = _stale_counts(tx)
    rel_delete = """
    MATCH ()-[r]->()
    WHERE r.createdFrom = 'semantic_schema' AND coalesce(r.schemaVersion, '') <> $version
    DELETE r
    """
    node_delete = """
    MATCH (n)
    WHERE n.createdFrom = 'semantic_schema'
      AND coalesce(n.schemaVersion, '') <> $version
      AND NOT (n)--()
    DELETE n
    """
    tx.run(rel_delete, version=SEMANTIC_SCHEMA_VERSION)
    tx.run(node_delete, version=SEMANTIC_SCHEMA_VERSION)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-stale", action="store_true")
    parser.add_argument(
        "--apply", action="store_true", help="Apply cleanup. Without this, cleanup is dry-run."
    )
    args = parser.parse_args()
    report = _run(dry_run=not args.apply, cleanup_stale=args.cleanup_stale)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
