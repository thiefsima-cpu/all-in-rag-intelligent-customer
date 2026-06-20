"""
Import the CSV knowledge graph into the running Neo4j service.
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))
from neo4j import GraphDatabase
from rag_modules.configuration import load_config


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


def main() -> None:
    config = load_config()
    script_path = Path(__file__).resolve().parents[1] / "cypher" / "neo4j_import.cypher"
    script = script_path.read_text(encoding="utf-8")
    script = script.replace("file:///nodes.csv", "file:///cypher/nodes.csv")
    script = script.replace("file:///relationships.csv", "file:///cypher/relationships.csv")
    statements = split_cypher(script)
    storage = config.storage
    driver = GraphDatabase.driver(
        storage.neo4j_uri,
        auth=(storage.neo4j_user, storage.neo4j_password),
    )
    try:
        with driver.session(database=storage.neo4j_database) as session:
            for index, statement in enumerate(statements, start=1):
                preview = statement.splitlines()[0][:80]
                print(f"[{index}/{len(statements)}] {preview}")
                result = session.run(statement)
                list(result)

            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            print(f"Imported graph: {node_count} nodes, {rel_count} relationships")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
