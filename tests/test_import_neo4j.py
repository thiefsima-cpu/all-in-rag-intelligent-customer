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
    def __init__(self, *, recipe_count: int) -> None:
        self.recipe_count = recipe_count
        self.statements: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def run(self, statement: str):
        self.statements.append(statement)
        if "AS recipe_count" in statement:
            return _FakeResult({"recipe_count": self.recipe_count})
        if "MATCH (n) RETURN count(n) AS c" in statement:
            return _FakeResult({"c": 12})
        if "MATCH ()-[r]->() RETURN count(r) AS c" in statement:
            return _FakeResult({"c": 18})
        return _FakeResult()


class _FakeDriver:
    def __init__(self, *, recipe_count: int) -> None:
        self.fake_session = _FakeSession(recipe_count=recipe_count)
        self.closed = False

    def session(self, *, database: str):
        del database
        return self.fake_session

    def close(self) -> None:
        self.closed = True


def _config():
    return SimpleNamespace(
        storage=SimpleNamespace(
            neo4j_uri="bolt://neo4j:7687",
            neo4j_user="neo4j",
            neo4j_password="password",
            neo4j_database="neo4j",
        )
    )


class ImportNeo4jTests(unittest.TestCase):
    def test_import_graph_skips_existing_recipe_data_when_requested(self) -> None:
        driver = _FakeDriver(recipe_count=3)
        self.assertTrue(hasattr(import_neo4j, "import_graph"))

        imported = import_neo4j.import_graph(
            _config(),
            only_if_empty=True,
            driver_factory=lambda *args: driver,
        )

        self.assertFalse(imported)
        self.assertEqual(1, len(driver.fake_session.statements))
        self.assertIn("AS recipe_count", driver.fake_session.statements[0])
        self.assertTrue(driver.closed)

    def test_import_graph_runs_csv_script_when_recipe_data_is_missing(self) -> None:
        driver = _FakeDriver(recipe_count=0)
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


if __name__ == "__main__":
    unittest.main()
