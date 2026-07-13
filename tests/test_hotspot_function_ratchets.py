from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _function_line_count(path: str, qualified_name: str) -> int:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
    parts = qualified_name.split(".")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        parents = _qualified_name_parts(tree, node)
        if parents == parts:
            return (node.end_lineno or node.lineno) - node.lineno + 1
    raise AssertionError(f"Could not find function {qualified_name!r} in {path}")


def _qualified_name_parts(tree: ast.Module, target: ast.AST) -> list[str]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent

    names: list[str] = []
    current: ast.AST | None = target
    while current is not None:
        if isinstance(current, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(current.name)
        current = parents.get(current)
    return list(reversed(names))


class HotspotFunctionRatchetsTests(unittest.TestCase):
    def test_named_hotspot_functions_stay_small_enough_to_review(self) -> None:
        limits = {
            (
                "rag_modules/runtime/build_jobs/file_repository_operations.py",
                "claim_next",
            ): 35,
            (
                "rag_modules/runtime/build_jobs/file_repository_operations.py",
                "recover_expired_leases",
            ): 25,
            (
                "rag_modules/interfaces/api/services/serving_streams.py",
                "ServingSseRunner.stream_answer_question_events",
            ): 40,
            (
                "rag_modules/build_pipeline/knowledge_base_workflow.py",
                "KnowledgeBaseBuildWorkflow.build",
            ): 45,
            (
                "rag_modules/app/composition/serving_runtime_factory.py",
                "ServingRuntimeFactory.build",
            ): 45,
            (
                "rag_modules/graph_index/entity_index_builder.py",
                "EntityIndexBuilder.build",
            ): 25,
            (
                "rag_modules/generation/clients/adapter.py",
                "GenerationClientAdapter.stream_prompt",
            ): 35,
            (
                "rag_modules/application/answering/answer_pipeline.py",
                "AnswerPipelineService.execute",
            ): 35,
            (
                "rag_modules/evidence_processing/extraction.py",
                "extract_evidence_units",
            ): 35,
            (
                "rag_modules/evidence_processing/extraction.py",
                "_graph_relationship_units",
            ): 45,
            (
                "scripts/pressure/runner.py",
                "run_pressure_test",
            ): 45,
            (
                "scripts/pressure/runner.py",
                "_run_answer_pressure_scenario",
            ): 45,
            (
                "scripts/pressure/runner.py",
                "_run_sse_pressure_scenario",
            ): 45,
        }

        oversize = []
        for (path, qualified_name), max_lines in limits.items():
            actual = _function_line_count(path, qualified_name)
            if actual > max_lines:
                oversize.append(f"{path}:{qualified_name} is {actual} lines > {max_lines}")

        self.assertEqual(oversize, [])


if __name__ == "__main__":
    unittest.main()
