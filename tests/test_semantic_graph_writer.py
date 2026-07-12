from __future__ import annotations

from rag_modules.configuration.testing import build_test_config
from rag_modules.infra.semantic_graph_writer import SemanticGraphSchemaWriter
from rag_modules.kernel.documents import TextDocument


class _Result(dict):
    def single(self):
        return self


class _RecordingTx:
    def __init__(self) -> None:
        self.calls = []

    def run(self, query, **kwargs):
        self.calls.append((query, kwargs))
        if "RETURN count(n) AS nodes" in query:
            return _Result(nodes=7)
        if "WHERE rel.rel_type = 'CONTRIBUTES_TO'" in query:
            return _Result(relationships=2)
        if "WHERE rel.rel_type IN" in query:
            return _Result(relationships=3)
        return _Result(relationships=len(kwargs.get("rows") or ()))


def test_semantic_graph_writer_write_rows_aggregates_query_family_counts() -> None:
    tx = _RecordingTx()
    rows = [
        {
            "recipe_id": "recipe-1",
            "recipe_name": "Mapo tofu",
            "relations": [
                {"rel_type": "HAS_FLAVOR", "name": "spicy", "causes": []},
                {"rel_type": "HAS_DIET_TAG", "name": "vegetarian", "causes": []},
                {"rel_type": "CONTRIBUTES_TO", "name": "aroma", "causes": ["pepper"]},
                {
                    "rel_type": "INGREDIENT_CONTRIBUTES_TO",
                    "name": "heat",
                    "source": "pepper",
                    "causes": ["pepper"],
                },
            ],
        }
    ]

    result = SemanticGraphSchemaWriter._write_rows(tx, rows)

    assert result == {"recipes": 1, "nodes": 7, "relationships": 7}
    simple_calls = [
        kwargs["rows"]
        for query, kwargs in tx.calls
        if "MERGE (recipe)-[edge:HAS_" in query or "MERGE (recipe)-[edge:USES_" in query
    ]
    assert simple_calls == [
        [{"recipe_id": "recipe-1", "name": "spicy", "rel_type": "HAS_FLAVOR"}],
        [{"recipe_id": "recipe-1", "name": "vegetarian", "rel_type": "HAS_DIET_TAG"}],
    ]


def test_build_rows_skips_invalid_recipes_and_normalizes_relation_families() -> None:
    writer = SemanticGraphSchemaWriter(build_test_config())
    rows = writer._build_rows(
        [
            TextDocument(content="ignored", metadata={}),
            TextDocument(
                content="recipe",
                metadata={
                    "node_id": "r1",
                    "recipe_name": "Mapo tofu",
                    "semantic_relations": {
                        "HAS_FLAVOR": [" spicy ", "spicy", ""],
                        "CONTRIBUTES_TO": [
                            {"effect": "aroma", "causes": ["pepper", "pepper", ""]},
                            {"effect": ""},
                        ],
                        "INGREDIENT_CONTRIBUTES_TO": [
                            {"source": "pepper", "effect": "heat"},
                            {"source": "", "effect": "ignored"},
                        ],
                        "TECHNIQUE_MODIFIES_TEXTURE": [{"source": "fry", "effect": "crisp"}],
                    },
                },
            ),
        ]
    )

    assert rows[0]["recipe_id"] == "r1"
    assert [item["name"] for item in rows[0]["relations"]] == [
        "spicy",
        "aroma",
        "heat",
        "crisp",
    ]
    assert rows[0]["relations"][1]["causes"] == ["pepper"]


def test_persist_guards_disabled_and_empty_documents() -> None:
    disabled = SemanticGraphSchemaWriter(
        build_test_config({"graph": {"enable_semantic_graph_schema": False}})
    )
    zero = {"recipes": 0, "nodes": 0, "relationships": 0}

    assert disabled.persist_from_documents([TextDocument(content="x")]) == zero
    assert SemanticGraphSchemaWriter(build_test_config()).persist_from_documents([]) == zero


def test_close_only_closes_owned_driver() -> None:
    class _Driver:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    writer = SemanticGraphSchemaWriter(build_test_config())
    driver = _Driver()
    writer.driver = driver
    writer._owns_driver = True

    writer.close()

    assert driver.closed is True
    assert writer.driver is None
    assert writer._owns_driver is False
