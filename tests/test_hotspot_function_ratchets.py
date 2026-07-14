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
    parents = _ast_parent_map(tree)
    parts = qualified_name.split(".")
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _qualified_name_parts(parents, node) == parts:
            return (node.end_lineno or node.lineno) - node.lineno + 1
    raise AssertionError(f"Could not find function {qualified_name!r} in {path}")


def _ast_parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _qualified_name_parts(parents: dict[ast.AST, ast.AST], target: ast.AST) -> list[str]:
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
        parents = _ast_parent_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            spans.append(
                _FunctionSpan(
                    path=relative_path,
                    qualified_name=".".join(_qualified_name_parts(parents, node)),
                    line_count=(node.end_lineno or node.lineno) - node.lineno + 1,
                )
            )
    return spans


def _function_ratchet_errors(
    spans: list[_FunctionSpan],
    allowlist: dict[tuple[str, str], str],
) -> list[str]:
    spans_by_key: dict[tuple[str, str], list[tuple[int, _FunctionSpan]]] = {}
    for index, span in enumerate(spans):
        spans_by_key.setdefault(span.key, []).append((index, span))

    errors: list[str] = []
    exempt_span_indexes: set[int] = set()
    reason_prefix = "state machine:"
    if len(allowlist) > MAX_STATE_MACHINE_EXCEPTIONS:
        errors.append(
            f"too many state-machine exceptions: {len(allowlist)} > {MAX_STATE_MACHINE_EXCEPTIONS}"
        )
    for key, reason in allowlist.items():
        matches = spans_by_key.get(key, [])
        oversized_matches = [
            (index, span)
            for index, span in matches
            if span.line_count > MAX_PRODUCTION_FUNCTION_LINES
        ]
        if not matches:
            errors.append(f"missing state-machine exception target: {key!r}")
        elif not oversized_matches:
            errors.append(f"stale state-machine exception: {key!r}")
        elif len(oversized_matches) > 1:
            errors.append(f"ambiguous state-machine exception: {key!r}")
        else:
            exempt_span_indexes.add(oversized_matches[0][0])

        explanation = (
            reason[len(reason_prefix) :].strip() if reason.startswith(reason_prefix) else ""
        )
        if not explanation:
            errors.append(f"invalid state-machine reason: {key!r}")

    errors.extend(
        f"{span.path}:{span.qualified_name} is "
        f"{span.line_count} lines > {MAX_PRODUCTION_FUNCTION_LINES}"
        for index, span in enumerate(spans)
        if span.line_count > MAX_PRODUCTION_FUNCTION_LINES and index not in exempt_span_indexes
    )
    return errors


class HotspotFunctionRatchetsTests(unittest.TestCase):
    def test_duplicate_oversized_allowlist_matches_are_ambiguous(self) -> None:
        key = ("rag_modules/duplicate.py", "duplicate")
        spans = [
            _FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES + 1),
            _FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES + 2),
        ]

        errors = _function_ratchet_errors(spans, {key: "state machine: duplicated definitions"})

        self.assertTrue(any("ambiguous state-machine exception" in error for error in errors))

    def test_allowlist_rejects_missing_stale_reasons_and_excess_entries(self) -> None:
        key = ("rag_modules/target.py", "target")
        oversize = _FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES + 1)
        cases = [
            ([], {key: "state machine: target must exist"}, "missing state-machine"),
            (
                [_FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES)],
                {key: "state machine: target must remain oversized"},
                "stale state-machine",
            ),
            ([oversize], {key: "complex orchestration"}, "invalid state-machine reason"),
            ([oversize], {key: "state machine:"}, "invalid state-machine reason"),
            ([oversize], {key: "state machine:   "}, "invalid state-machine reason"),
            (
                [
                    _FunctionSpan(
                        "rag_modules/limit.py",
                        f"state_machine_{index}",
                        MAX_PRODUCTION_FUNCTION_LINES + 1,
                    )
                    for index in range(4)
                ],
                {
                    ("rag_modules/limit.py", f"state_machine_{index}"): (
                        f"state machine: exception {index}"
                    )
                    for index in range(4)
                },
                "too many state-machine exceptions: 4 > 3",
            ),
        ]

        for spans, allowlist, message in cases:
            with self.subTest(message=message):
                errors = _function_ratchet_errors(spans, allowlist)
                self.assertTrue(any(message in error for error in errors), errors)

    def test_allowlist_exempts_the_only_oversized_duplicate_match(self) -> None:
        key = ("rag_modules/duplicate.py", "duplicate")
        spans = [
            _FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES),
            _FunctionSpan(*key, MAX_PRODUCTION_FUNCTION_LINES + 1),
        ]

        self.assertEqual(
            _function_ratchet_errors(
                spans,
                {key: "state machine: one oversized definition"},
            ),
            [],
        )

    def test_qualified_names_cover_nested_and_async_functions(self) -> None:
        tree = ast.parse(
            """
class Outer:
    async def execute(self):
        def nested():
            return None
        return nested()

async def top_level():
    async def nested_async():
        return None
    return await nested_async()
"""
        )
        parents = _ast_parent_map(tree)
        functions = sorted(
            (
                node.lineno,
                ".".join(_qualified_name_parts(parents, node)),
            )
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )

        self.assertEqual(
            [name for _, name in functions],
            [
                "Outer.execute",
                "Outer.execute.nested",
                "top_level",
                "top_level.nested_async",
            ],
        )

    def test_production_allowlist_starts_empty_and_caps_exceptions_at_three(self) -> None:
        self.assertEqual(STATE_MACHINE_FUNCTION_ALLOWLIST, {})
        self.assertEqual(MAX_STATE_MACHINE_EXCEPTIONS, 3)

    def test_all_production_functions_respect_default_limit(self) -> None:
        spans = _production_function_spans()
        self.assertEqual(_function_ratchet_errors(spans, STATE_MACHINE_FUNCTION_ALLOWLIST), [])

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
