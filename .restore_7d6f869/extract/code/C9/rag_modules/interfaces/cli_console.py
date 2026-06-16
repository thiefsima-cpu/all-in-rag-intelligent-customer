"""CLI interfaces for the GraphRAG application."""

from __future__ import annotations

from typing import Callable, Optional

from ..configuration.models import GraphRAGConfig

from ..app.application_protocol import GraphRAGApplication

InputFunc = Callable[[str], str]
OutputFunc = Callable[[str], None]


class InteractiveCliConsole:
    """Interactive console kept outside the application core."""

    def __init__(
        self,
        system: GraphRAGApplication,
        *,
        input_func: InputFunc = input,
        output_func: OutputFunc = print,
    ):
        self.system = system
        self.input_func = input_func
        self.output_func = output_func

    def run(self) -> None:
        self.output_func("\nWelcome to the GraphRAG cooking assistant.")
        self.output_func("Commands:")
        self.output_func("   - 'stats'   Show system statistics")
        self.output_func("   - 'rebuild' Rebuild the knowledge base")
        self.output_func("   - 'quit'    Exit")
        self.output_func("\n" + "=" * 50)

        while True:
            try:
                user_input = self.input_func("\nYour question: ").strip()
                if not user_input:
                    continue
                if user_input.lower() == "quit":
                    break
                if user_input.lower() == "stats":
                    self._show_system_stats()
                    continue
                if user_input.lower() == "rebuild":
                    self._rebuild_knowledge_base()
                    continue
                self.output_func("\nAnswer:")
                self.system.answer_question(
                    user_input,
                    stream=True,
                    explain_routing=False,
                    message_callback=self.output_func,
                    chunk_callback=self._emit_chunk,
                )
            except KeyboardInterrupt:
                break
            except Exception as exc:
                self.output_func(f"Error while handling the question: {exc}")
                import traceback

                traceback.print_exc()

        self.output_func("\nThanks for using the GraphRAG cooking assistant.")

    def _show_system_stats(self) -> None:
        stats = self.system.collect_system_stats()
        route_stats = stats.get("route_stats", {})
        data_stats = stats.get("data_stats", {})
        index_stats = stats.get("index_stats", {})
        manifest = stats.get("artifact_manifest", {})
        self.output_func("\nSystem statistics")
        self.output_func("=" * 40)
        total_queries = route_stats.get("total_queries", 0)
        if total_queries > 0:
            self.output_func(f"Total queries: {total_queries}")
            self.output_func(
                f"Traditional retrieval: {route_stats.get('traditional_count', 0)} "
                f"({route_stats.get('traditional_ratio', 0):.1%})"
            )
            self.output_func(
                f"Graph retrieval: {route_stats.get('graph_rag_count', 0)} "
                f"({route_stats.get('graph_rag_ratio', 0):.1%})"
            )
            self.output_func(
                f"Combined strategy: {route_stats.get('combined_count', 0)} "
                f"({route_stats.get('combined_ratio', 0):.1%})"
            )
        else:
            self.output_func("No query history yet.")
        self.output_func(f"Recipes: {data_stats.get('total_recipes', 0)}")
        self.output_func(f"Chunks: {data_stats.get('total_chunks', 0)}")
        self.output_func(f"Vector rows: {index_stats.get('row_count', 0)}")
        self.output_func(
            "Artifact manifest: "
            f"health={manifest.get('health', 'unknown')}, "
            f"stage={manifest.get('stage', 'unknown')}, "
            f"cache_hit={manifest.get('cache_hit', False)}, "
            f"documents={manifest.get('total_documents', 0)}, "
            f"chunks={manifest.get('total_chunks', 0)}"
        )
        if manifest.get("last_error"):
            self.output_func(f"Artifact manifest error: {manifest['last_error']}")

    def _rebuild_knowledge_base(self) -> None:
        self.output_func("\nPreparing to rebuild the knowledge base...")
        confirm = self.input_func(
            "[WARN] This builds and publishes the inactive Milvus slot. Continue? (y/N): "
        ).strip().lower()
        if confirm != "y":
            self.output_func("[INFO] Rebuild cancelled.")
            return
        self.system.rebuild_knowledge_base(progress=self.output_func)
        self.output_func("[OK] Knowledge base rebuild completed.")

    def _emit_chunk(self, chunk: str) -> None:
        if self.output_func is print:
            print(chunk, end="", flush=True)
            return
        self.output_func(chunk)


def build_knowledge_base_only(
    *,
    system: Optional[GraphRAGApplication] = None,
    config: Optional[GraphRAGConfig] = None,
    output_func: OutputFunc = print,
    rebuild: bool = False,
) -> GraphRAGApplication:
    """Initialize only the build runtime and prepare the knowledge-base artifacts."""

    output_func("Starting GraphRAG knowledge-base build...")
    rag_system = _resolve_system(system=system, config=config)
    if not rag_system.is_build_initialized():
        rag_system.initialize_build_runtime(progress=output_func)
    _emit_startup_diagnostics(
        rag_system,
        mode="build",
        output_func=output_func,
        title="Build startup diagnostics",
    )
    if rebuild:
        rag_system.rebuild_knowledge_base(progress=output_func)
    else:
        rag_system.build_knowledge_base(progress=output_func)
    _emit_startup_diagnostics(
        rag_system,
        mode="build",
        output_func=output_func,
        title="Build artifact diagnostics",
    )
    output_func("[OK] Knowledge-base artifacts are ready.")
    return rag_system


def run_qa_cli(
    *,
    system: Optional[GraphRAGApplication] = None,
    config: Optional[GraphRAGConfig] = None,
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> GraphRAGApplication:
    """Run the interactive question-answering CLI."""

    rag_system = _resolve_system(system=system, config=config)
    if not rag_system.is_serving_initialized():
        output_func("Starting GraphRAG serving runtime...")
        rag_system.initialize_serving_runtime(progress=output_func)
    _emit_startup_diagnostics(
        rag_system,
        mode="serve",
        output_func=output_func,
        title="Serving startup diagnostics",
    )
    if not rag_system.system_ready:
        diagnostics = rag_system.collect_startup_diagnostics("serve")
        artifact_health = diagnostics.manifest.health
        if artifact_health == "stale":
            output_func(
                "[WARN] Serving runtime is assembled, but the persisted retrieval artifacts are stale."
            )
        elif artifact_health == "failed":
            output_func(
                "[WARN] Serving runtime is assembled, but the persisted retrieval artifacts are in a failed state."
            )
        else:
            output_func(
                "[WARN] Serving runtime is assembled, but required artifacts are not ready."
            )
        output_func(
            "Build the knowledge base first with `main_build_kb.py` "
            "or `build_knowledge_base_only()`."
        )
        output_func(f"Manifest path: {diagnostics.manifest.manifest_path}")
        return rag_system
    rag_system.run_interactive(input_func=input_func, output_func=output_func)
    return rag_system


def run_default_cli(
    *,
    system: Optional[GraphRAGApplication] = None,
    config: Optional[GraphRAGConfig] = None,
    input_func: InputFunc = input,
    output_func: OutputFunc = print,
) -> GraphRAGApplication:
    """Backward-compatible alias for the interactive QA CLI."""

    return run_qa_cli(
        system=system,
        config=config,
        input_func=input_func,
        output_func=output_func,
    )


def _emit_startup_diagnostics(
    system: GraphRAGApplication,
    *,
    mode: str,
    output_func: OutputFunc,
    title: str,
) -> None:
    diagnostics = system.collect_startup_diagnostics(mode)
    output_func("")
    for line in diagnostics.to_lines(title=title):
        output_func(line)


def _resolve_system(
    *,
    system: Optional[GraphRAGApplication],
    config: Optional[GraphRAGConfig],
) -> GraphRAGApplication:
    if system is not None:
        return system
    from ..app.assembly import create_application_system

    return create_application_system(config=config)
