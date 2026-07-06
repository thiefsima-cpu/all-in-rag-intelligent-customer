from __future__ import annotations

import importlib


def test_app_diagnostics_facade_reexports_split_models_and_formatter() -> None:
    facade = importlib.import_module("rag_modules.app.diagnostics")
    models = importlib.import_module("rag_modules.app.diagnostics_models")
    artifacts = importlib.import_module("rag_modules.app.diagnostics_artifact_models")
    formatter = importlib.import_module("rag_modules.app.diagnostics_formatters")
    runtime = importlib.import_module("rag_modules.app.diagnostics_runtime_models")
    stats = importlib.import_module("rag_modules.app.diagnostics_stats_models")

    for name, owner in (
        ("ArtifactManifestDiagnostics", artifacts),
        ("DataStatsDiagnostics", stats),
        ("StartupDiagnostics", runtime),
        ("SystemStatsDiagnostics", runtime),
        ("TraceStatsDiagnostics", stats),
    ):
        assert getattr(facade, name) is getattr(models, name)
        assert getattr(models, name) is getattr(owner, name)
    assert facade.startup_diagnostics_lines is formatter.startup_diagnostics_lines


def test_answer_debug_facade_reexports_split_response_models() -> None:
    facade = importlib.import_module("rag_modules.interfaces.api.answer_debug_models")
    route = importlib.import_module("rag_modules.interfaces.api.answer_debug_route_models")
    traces = importlib.import_module("rag_modules.interfaces.api.answer_debug_trace_models")
    payloads = importlib.import_module("rag_modules.interfaces.api.answer_debug_payload_models")

    for name in (
        "RouteDiagnosticsResponseModel",
        "RouteSnapshotResponseModel",
        "RouteStageSnapshotResponseModel",
    ):
        assert getattr(facade, name) is getattr(route, name)
    for name in (
        "GenerationSnapshotResponseModel",
        "QueryTraceEventResponseModel",
        "RetrievalTraceSnapshotResponseModel",
    ):
        assert getattr(facade, name) is getattr(traces, name)
    for name in ("AnswerPayloadModel", "AnswerResponseModel", "AnswerTracesModel"):
        assert getattr(facade, name) is getattr(payloads, name)


def test_query_understanding_features_facade_reexports_split_domain_features() -> None:
    facade = importlib.import_module("rag_modules.query_understanding.features")
    lexical = importlib.import_module("rag_modules.query_understanding.lexical_features")
    entities = importlib.import_module("rag_modules.query_understanding.entity_features")
    graph = importlib.import_module("rag_modules.query_understanding.graph_features")
    constraints = importlib.import_module("rag_modules.query_understanding.constraint_features")

    for name in ("clean_entity_phrase", "extract_query_tokens", "has_filtering_intent"):
        assert getattr(facade, name) is getattr(lexical, name)
    for name in ("extract_entity_candidates", "fallback_entity_phrases"):
        assert getattr(facade, name) is getattr(entities, name)
    for name in ("infer_graph_query_type", "infer_relation_types"):
        assert getattr(facade, name) is getattr(graph, name)
    for name in ("extract_minutes", "infer_query_constraints"):
        assert getattr(facade, name) is getattr(constraints, name)
