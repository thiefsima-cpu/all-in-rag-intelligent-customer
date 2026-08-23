"""
Import the CSV knowledge graph into the running Neo4j service.
"""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from rag_modules.configuration import load_config
from rag_modules.domains import DEFAULT_DOMAIN_NAME, DomainPack, get_domain_pack
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


def _domain_name(config) -> str:
    domain = getattr(config, "domain", None)
    return str(getattr(domain, "name", DEFAULT_DOMAIN_NAME) or DEFAULT_DOMAIN_NAME).strip().lower()


def _load_import_statements(domain_pack: DomainPack) -> list[str]:
    if not domain_pack.graph_import_resource:
        raise ValueError(f"Domain {domain_pack.name!r} does not define a graph import resource.")
    script_path = Path(__file__).resolve().parents[1] / "cypher" / domain_pack.graph_import_resource
    script = script_path.read_text(encoding="utf-8")
    for source, target in domain_pack.graph_import_replacements:
        script = script.replace(source, target)
    return split_cypher(script)


def _has_domain_data(session, domain_pack: DomainPack) -> bool:
    record = session.run(
        """
        MATCH (entity)
        WHERE entity.domain = $domain_name
           OR ($allow_domainless_graph_records
               AND entity.domain IS NULL
               AND any(label IN labels(entity) WHERE label IN $primary_labels))
        RETURN count(entity) AS domain_entity_count
        """,
        {
            "domain_name": domain_pack.name,
            "primary_labels": list(domain_pack.ontology.primary_labels),
            "allow_domainless_graph_records": domain_pack.allow_domainless_graph_records,
        },
    ).single()
    return bool(record and int(record["domain_entity_count"] or 0) > 0)


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
            domain_name = _domain_name(config)
            domain_pack = get_domain_pack(domain_name)
            if only_if_empty and _has_domain_data(session, domain_pack):
                print(f"Neo4j {domain_name} data already exists; skipping graph import.")
                return False

            statements = _load_import_statements(domain_pack)
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
        help="Skip graph import when Neo4j already contains data for the selected domain.",
    )
    args = parser.parse_args(argv)
    import_graph(load_config(), only_if_empty=args.if_empty)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
