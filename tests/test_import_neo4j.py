from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts import import_neo4j


class _FakeResult:
    def __init__(self, record: dict | None = None) -> None:
        self.record = record

    def __iter__(self):
        return iter(())

    def single(self):
        return self.record


class _FakeSession:
    def __init__(self, *, domain_entity_count: int = 0) -> None:
        self.domain_entity_count = domain_entity_count
        self.statements: list[str] = []
        self.parameters: list[object | None] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def run(self, statement: str, parameters: object | None = None):
        self.statements.append(statement)
        self.parameters.append(parameters)
        if "AS domain_entity_count" in statement:
            return _FakeResult({"domain_entity_count": self.domain_entity_count})
        if "MATCH (n) RETURN count(n) AS c" in statement:
            return _FakeResult({"c": 12})
        if "MATCH ()-[r]->() RETURN count(r) AS c" in statement:
            return _FakeResult({"c": 18})
        return _FakeResult()


class _FakeDriver:
    def __init__(self, *, domain_entity_count: int = 0) -> None:
        self.fake_session = _FakeSession(domain_entity_count=domain_entity_count)
        self.closed = False

    def session(self, *, database: str):
        del database
        return self.fake_session

    def close(self) -> None:
        self.closed = True


def _config(domain_name: str = "recipe"):
    return SimpleNamespace(
        domain=SimpleNamespace(name=domain_name),
        storage=SimpleNamespace(
            neo4j_uri="bolt://neo4j:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            neo4j_database="neo4j",
        ),
    )


class ImportNeo4jTests(unittest.TestCase):
    def test_import_graph_skips_existing_recipe_data_when_requested(self) -> None:
        driver = _FakeDriver(domain_entity_count=3)
        self.assertTrue(hasattr(import_neo4j, "import_graph"))

        imported = import_neo4j.import_graph(
            _config(),
            only_if_empty=True,
            driver_factory=lambda *args: driver,
        )

        self.assertFalse(imported)
        self.assertEqual(1, len(driver.fake_session.statements))
        self.assertIn("AS domain_entity_count", driver.fake_session.statements[0])
        self.assertEqual(
            driver.fake_session.parameters[0],
            {
                "domain_name": "recipe",
                "primary_labels": ["Recipe"],
                "allow_domainless_graph_records": True,
            },
        )
        self.assertTrue(driver.closed)

    def test_import_graph_runs_csv_script_when_recipe_data_is_missing(self) -> None:
        driver = _FakeDriver(domain_entity_count=0)
        self.assertTrue(hasattr(import_neo4j, "import_graph"))

        imported = import_neo4j.import_graph(
            _config(),
            only_if_empty=True,
            driver_factory=lambda *args: driver,
        )

        self.assertTrue(imported)
        self.assertGreater(len(driver.fake_session.statements), 5)
        self.assertTrue(
            any("LOAD CSV WITH HEADERS" in item for item in driver.fake_session.statements)
        )
        self.assertTrue(driver.closed)

    def test_customer_service_domain_imports_customer_knowledge_seed(self) -> None:
        driver = _FakeDriver(domain_entity_count=0)

        imported = import_neo4j.import_graph(
            _config("customer_service"),
            only_if_empty=True,
            driver_factory=lambda *args: driver,
        )

        self.assertTrue(imported)
        self.assertTrue(
            any("POL-REFUND-2026-07" in item for item in driver.fake_session.statements)
        )
        self.assertFalse(
            any("LOAD CSV WITH HEADERS" in item for item in driver.fake_session.statements)
        )

    def test_customer_service_domain_skips_only_when_customer_data_exists(self) -> None:
        driver = _FakeDriver(domain_entity_count=2)

        imported = import_neo4j.import_graph(
            _config("customer_service"),
            only_if_empty=True,
            driver_factory=lambda *args: driver,
        )

        self.assertFalse(imported)
        self.assertEqual(1, len(driver.fake_session.statements))
        self.assertIn("AS domain_entity_count", driver.fake_session.statements[0])


if __name__ == "__main__":
    unittest.main()
