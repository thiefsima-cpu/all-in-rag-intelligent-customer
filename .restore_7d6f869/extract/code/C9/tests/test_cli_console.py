from __future__ import annotations

import unittest

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.artifacts import ARTIFACT_HEALTH_MISSING, ARTIFACT_HEALTH_READY, ARTIFACT_HEALTH_STALE
from rag_modules.interfaces.cli_console import build_knowledge_base_only, run_qa_cli


def _diagnostics(
    *,
    mode: str,
    system_ready: bool,
    artifact_health: str | None = None,
) -> StartupDiagnostics:
    resolved_health = artifact_health or (
        ARTIFACT_HEALTH_READY if system_ready else ARTIFACT_HEALTH_MISSING
    )
    resolved_stage = (
        "ready"
        if resolved_health == ARTIFACT_HEALTH_READY
        else "stale"
        if resolved_health == ARTIFACT_HEALTH_STALE
        else "missing"
    )
    return StartupDiagnostics(
        mode=mode,
        llm_model="qwen3.7-plus",
        embedding_model="qwen3-vl-embedding",
        rerank_model="qwen3-vl-rerank",
        trace_enabled=True,
        trace_path="trace.jsonl",
        trace_stats={"dropped_events": 0, "queued_events": 0, "async_enabled": True},
        build_initialized=(mode == "build"),
        serving_initialized=(mode == "serve"),
        artifacts_ready=system_ready,
        system_ready=system_ready,
        retrieval_engines_initialized=system_ready,
        manifest=ArtifactManifestDiagnostics(
            stage=resolved_stage,
            health=resolved_health,
            updated_at="",
            collection_name="recipes",
            manifest_path="storage/indexes/artifact_manifest.json",
            documents_path="storage/indexes/documents.json",
            chunks_path="storage/indexes/chunks.json",
            total_documents=2,
            total_chunks=4,
            vector_rows=4,
            cache_hit=False,
            last_error="",
            build_metadata={},
        ),
    )


class _FakeCliSystem:
    def __init__(self, *, system_ready: bool, artifact_health: str | None = None) -> None:
        self.system_ready = system_ready
        self.artifact_health = artifact_health
        self.build_initialized = False
        self.serving_initialized = False
        self.initialize_build_calls = 0
        self.initialize_serving_calls = 0
        self.build_calls = 0
        self.rebuild_calls = 0
        self.run_interactive_calls = 0

    def is_build_initialized(self) -> bool:
        return self.build_initialized

    def is_serving_initialized(self) -> bool:
        return self.serving_initialized

    def initialize_build_runtime(self, progress=None, *, neo4j_manager=None):
        del neo4j_manager
        self.initialize_build_calls += 1
        self.build_initialized = True
        if progress:
            progress("build-runtime-ready")
        return None

    def initialize_serving_runtime(self, progress=None, *, query_tracer=None, neo4j_manager=None):
        del query_tracer, neo4j_manager
        self.initialize_serving_calls += 1
        self.serving_initialized = True
        if progress:
            progress("serving-runtime-ready")
        return None

    def build_knowledge_base(self, progress=None) -> None:
        self.build_calls += 1
        if progress:
            progress("build-kb")

    def rebuild_knowledge_base(self, progress=None) -> None:
        self.rebuild_calls += 1
        if progress:
            progress("rebuild-kb")

    def collect_system_stats(self) -> dict:
        return {
            "artifact_manifest": {
                "health": self.artifact_health
                or (ARTIFACT_HEALTH_READY if self.system_ready else ARTIFACT_HEALTH_MISSING),
                "stage": "ready" if self.system_ready else "missing",
                "cache_hit": False,
                "total_documents": 2,
                "total_chunks": 4,
            }
        }

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        return _diagnostics(
            mode=mode,
            system_ready=self.system_ready,
            artifact_health=self.artifact_health,
        )

    def answer_question(self, *args, **kwargs):
        del args, kwargs
        return None

    def run_interactive(self, input_func=input, output_func=print) -> None:
        del input_func, output_func
        self.run_interactive_calls += 1

    def close(self) -> None:
        return None


class CliConsoleTests(unittest.TestCase):
    def test_build_knowledge_base_only_accepts_protocol_system(self) -> None:
        system = _FakeCliSystem(system_ready=True)
        output_lines: list[str] = []

        result = build_knowledge_base_only(
            system=system,
            output_func=output_lines.append,
        )

        self.assertIs(result, system)
        self.assertEqual(system.initialize_build_calls, 1)
        self.assertEqual(system.build_calls, 1)
        self.assertIn("[OK] Knowledge-base artifacts are ready.", output_lines)

    def test_run_qa_cli_warns_when_artifacts_are_not_ready(self) -> None:
        system = _FakeCliSystem(system_ready=False)
        output_lines: list[str] = []

        result = run_qa_cli(
            system=system,
            input_func=lambda _: "quit",
            output_func=output_lines.append,
        )

        self.assertIs(result, system)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.run_interactive_calls, 0)
        self.assertTrue(
            any("required artifacts are not ready" in line for line in output_lines)
        )

    def test_run_qa_cli_surfaces_stale_artifact_warning(self) -> None:
        system = _FakeCliSystem(
            system_ready=False,
            artifact_health=ARTIFACT_HEALTH_STALE,
        )
        output_lines: list[str] = []

        run_qa_cli(
            system=system,
            input_func=lambda _: "quit",
            output_func=output_lines.append,
        )

        self.assertTrue(any("artifacts are stale" in line for line in output_lines))

    def test_run_qa_cli_runs_interactive_when_ready(self) -> None:
        system = _FakeCliSystem(system_ready=True)
        output_lines: list[str] = []

        result = run_qa_cli(
            system=system,
            input_func=lambda _: "quit",
            output_func=output_lines.append,
        )

        self.assertIs(result, system)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.run_interactive_calls, 1)

    def test_collect_system_stats_payload_can_surface_artifact_health(self) -> None:
        system = _FakeCliSystem(
            system_ready=False,
            artifact_health=ARTIFACT_HEALTH_STALE,
        )

        stats = system.collect_system_stats()

        self.assertEqual(stats["artifact_manifest"]["health"], ARTIFACT_HEALTH_STALE)


if __name__ == "__main__":
    unittest.main()
