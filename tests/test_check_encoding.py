from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.graph.evidence_builder import GraphEvidenceBuilder
from scripts.check_encoding import audit_file


READABLE_SUBGRAPH_NAME = "\u77e5\u8bc6\u5b50\u56fe"
LEAKED_SUBGRAPH_NAME = "\u942d\u30e8\u7611\u701b\u612c\u6d58"


class CheckEncodingTests(unittest.TestCase):
    def test_audit_flags_graph_subgraph_name_mojibake(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "sample.py"
            path.write_text(f'name = "{LEAKED_SUBGRAPH_NAME}"\n', encoding="utf-8")

            issues = audit_file(path, root)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].kind, "mojibake")
        self.assertEqual(issues[0].line, 1)


class GraphEvidenceBuilderEncodingTests(unittest.TestCase):
    def test_subgraph_evidence_uses_readable_name_when_no_recipe_name_exists(self) -> None:
        subgraph = SimpleNamespace(
            central_nodes=[],
            connected_nodes=[],
            relationships=[],
            graph_metrics={},
        )

        evidence = GraphEvidenceBuilder().subgraph_to_evidence(subgraph, [], "query")

        self.assertEqual(evidence[0].recipe_name, READABLE_SUBGRAPH_NAME)
        self.assertEqual(evidence[0].metadata["recipe_name"], READABLE_SUBGRAPH_NAME)
