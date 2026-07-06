"""
Import the CSV knowledge graph into the running Neo4j service.
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from rag_modules.configuration import load_config
from rag_modules.infra.neo4j import create_neo4j_driver


def split_cypher(script: str) -> list[str]:
    statements = []
    buffer = []
    for line in script.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            statements.append(statement[:-1].strip())
            buffer = []
    if buffer:
        statements.append("\n".join(buffer).strip())
    return statements


def _load_import_statements() -> list[str]:
    script_path = Path(__file__).resolve().parents[1] / "cypher" / "neo4j_import.cypher"
    script = script_path.read_text(encoding="utf-8")
    script = script.replace("file:///nodes.csv", "file:///cypher/nodes.csv")
    script = script.replace("file:///relationships.csv", "file:///cypher/relationships.csv")
    return split_cypher(script)


def _has_recipe_data(session) -> bool:
    record = session.run("MATCH (recipe:Recipe) RETURN count(recipe) AS recipe_count").single()
    return bool(record and int(record["recipe_count"] or 0) > 0)


def import_graph(
    config,
    *,
    only_if_empty: bool = False,
    driver_factory=create_neo4j_driver,
) -> bool:
    storage = config.storage
    driver = driver_factory(
        storage.neo4j_uri,
        storage.neo4j_user,
        storage.neo4j_password,
    )
    try:
        with driver.session(database=storage.neo4j_database) as session:
            if only_if_empty and _has_recipe_data(session):
                print("Neo4j recipe data already exists; skipping CSV import.")
                return False

            statements = _load_import_statements()
            for index, statement in enumerate(statements, start=1):
                preview = statement.splitlines()[0][:80]
                print(f"[{index}/{len(statements)}] {preview}")
                result = session.run(statement)
                list(result)

            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(f"Imported graph: {node_count} nodes, {rel_count} relationships")
            return True
    finally:
        driver.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="Skip CSV import when Neo4j already contains Recipe nodes.",
    )
    args = parser.parse_args(argv)
    import_graph(load_config(), only_if_empty=args.if_empty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
