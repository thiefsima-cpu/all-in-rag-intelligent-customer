from __future__ import annotations

from rag_modules.infra.semantic_graph_writer import SemanticGraphSchemaWriter


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
