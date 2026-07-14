from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _file_line_count(path: str) -> int:
    return len((ROOT / path).read_text(encoding="utf-8").splitlines())


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


MAX_PRODUCTION_FUNCTION_LINES = 80
MAX_STATE_MACHINE_EXCEPTIONS = 3
STATE_MACHINE_FUNCTION_ALLOWLIST: dict[tuple[str, str], str] = {}
_MIGRATION_FUNCTION_LENGTH_DEBT = {
    (
        "rag_modules/query_understanding/graph_intent.py",
        "infer_query_semantic_profile",
    ): 110,
    (
        "rag_modules/infra/milvus/writer.py",
        "_MilvusWriterOperations.build_vector_index",
    ): 95,
    (
        "rag_modules/query_understanding/planning/calibration.py",
        "QueryPlanCalibrator.calibrate",
    ): 94,
    (
        "rag_modules/generation/execution/engine.py",
        "GenerationExecutionEngine.generate_with_trace",
    ): 92,
    (
        "rag_modules/routing/strategies/graph.py",
        "GraphRouteStrategy.execute",
    ): 91,
    (
        "rag_modules/query_understanding/planning/rule_based.py",
        "RuleBasedPlanner.plan",
    ): 83,
    (
        "rag_modules/domain/shared/semantic_schema.py",
        "infer_recipe_semantics",
    ): 83,
    (
        "rag_modules/generation/execution/two_stage.py",
        "TwoStageCompletionRunner.run",
    ): 82,
}


@dataclass(frozen=True)
class _FunctionSpan:
    path: str
    qualified_name: str
    line_count: int

    @property
    def key(self) -> tuple[str, str]:
        return self.path, self.qualified_name


def _production_function_spans() -> list[_FunctionSpan]:
    spans: list[_FunctionSpan] = []
    for path in sorted((ROOT / "rag_modules").rglob("*.py")):
        relative_path = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            spans.append(
                _FunctionSpan(
                    path=relative_path,
                    qualified_name=".".join(_qualified_name_parts(tree, node)),
                    line_count=(node.end_lineno or node.lineno) - node.lineno + 1,
                )
            )
    return spans


class HotspotFunctionRatchetsTests(unittest.TestCase):
    def test_all_production_functions_respect_default_limit(self) -> None:
        spans = _production_function_spans()
        by_key = {span.key: span for span in spans}
        self.assertLessEqual(
            len(STATE_MACHINE_FUNCTION_ALLOWLIST),
            MAX_STATE_MACHINE_EXCEPTIONS,
        )

        exception_errors: list[str] = []
        for key, reason in STATE_MACHINE_FUNCTION_ALLOWLIST.items():
            span = by_key.get(key)
            if span is None:
                exception_errors.append(f"missing state-machine exception target: {key!r}")
            elif span.line_count <= MAX_PRODUCTION_FUNCTION_LINES:
                exception_errors.append(f"stale state-machine exception: {key!r}")
            if not reason.startswith("state machine:"):
                exception_errors.append(f"invalid state-machine reason: {key!r}")

        debt_errors: list[str] = []
        for key, baseline in _MIGRATION_FUNCTION_LENGTH_DEBT.items():
            span = by_key.get(key)
            if span is None:
                debt_errors.append(f"missing migration debt target: {key!r}")
            elif span.line_count <= MAX_PRODUCTION_FUNCTION_LINES:
                debt_errors.append(f"stale migration debt: {key!r}")
            elif span.line_count > baseline:
                debt_errors.append(
                    f"migration debt grew: {key!r} is {span.line_count} lines > {baseline}"
                )

        oversize = [
            f"{span.path}:{span.qualified_name} is "
            f"{span.line_count} lines > {MAX_PRODUCTION_FUNCTION_LINES}"
            for span in spans
            if span.line_count > MAX_PRODUCTION_FUNCTION_LINES
            and span.key not in STATE_MACHINE_FUNCTION_ALLOWLIST
            and span.key not in _MIGRATION_FUNCTION_LENGTH_DEBT
        ]
        self.assertEqual(exception_errors + debt_errors + oversize, [])

    def test_pressure_script_stays_a_thin_direct_entrypoint(self) -> None:
        path = ROOT / "scripts/pressure_api_service.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        definitions = [
            node
            for node in tree.body
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        self.assertLessEqual(_file_line_count("scripts/pressure_api_service.py"), 20)
        self.assertEqual(definitions, [])

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
