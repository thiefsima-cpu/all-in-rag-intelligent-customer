from __future__ import annotations

import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rag_modules.configuration.testing import build_test_config
from scripts.eval_queries import (
    DEFAULT_CORPUS_PATH,
    EvalCase,
    EvalResponseMode,
    build_eval_report,
    evaluate_case,
    evaluate_offline_quality_queries,
    evaluate_queries,
    load_eval_cases,
    run_eval,
)


def _valid_strict_eval_payload() -> dict:
    return {
        "id": "grounded-01",
        "query": "宫保鸡丁怎么做？",
        "category": "single_recipe",
        "dimensions": ["single_recipe"],
        "expectation": {
            "response_mode": "grounded_answer",
            "strategy": "hybrid_traditional",
            "recipe_names": ["宫保鸡丁"],
            "answer_terms": ["宫保鸡丁"],
            "recipe_relevance": {"宫保鸡丁": 3.0},
        },
        "offline_fixture": {
            "strategy": "hybrid_traditional",
            "answer": "依据菜谱证据 #1，宫保鸡丁需要鸡丁、花生和调味汁。",
            "evidence": [
                {
                    "recipe_name": "宫保鸡丁",
                    "content": "宫保鸡丁需要鸡丁、花生和调味汁。",
                    "score": 1.0,
                    "evidence_type": "text",
                }
            ],
        },
    }


def _load_temporary_eval_payload(payload: object):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "quality-eval.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return load_eval_cases(path)


def _load_temporary_eval_text(payload: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "quality-eval.json"
        path.write_text(payload, encoding="utf-8")
        return load_eval_cases(path)


class StrictEvalCaseContractTests(unittest.TestCase):
    def test_review_rejects_empty_dimensions(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["dimensions"] = []

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*grounded-01.*dimensions.*non-empty",
        ):
            _load_temporary_eval_payload([payload])

    def test_review_rejects_duplicate_json_keys_at_root_and_nested_levels(self) -> None:
        encoded = json.dumps([_valid_strict_eval_payload()], ensure_ascii=False)
        payloads = {
            "root": encoded.replace('"query":', '"query": "duplicate", "query":', 1),
            "nested": encoded.replace(
                '"response_mode":',
                '"response_mode": "no_evidence", "response_mode":',
                1,
            ),
        }

        for level, payload in payloads.items():
            with (
                self.subTest(level=level),
                self.assertRaisesRegex(
                    ValueError,
                    r"quality-eval\.json.*duplicate JSON object key",
                ),
            ):
                _load_temporary_eval_text(payload)

    def test_review_json_decode_error_includes_corpus_path(self) -> None:
        with self.assertRaisesRegex(ValueError, r"quality-eval\.json.*invalid JSON"):
            _load_temporary_eval_text("[")

    def test_review_rejects_normalized_recipe_relevance_key_collisions(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expectation"]["recipe_names"] = ["recipe"]
        payload["expectation"]["recipe_relevance"] = {"recipe": 3.0, " recipe ": 1.0}
        payload["offline_fixture"]["evidence"][0]["recipe_name"] = "recipe"

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*grounded-01.*recipe_relevance.*collision",
        ):
            _load_temporary_eval_payload([payload])

    def test_review_rejects_all_zero_recipe_relevance(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expectation"]["recipe_relevance"] = {"宫保鸡丁": 0.0}

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*grounded-01.*recipe_relevance.*positive",
        ):
            _load_temporary_eval_payload([payload])

    def test_review_allows_zero_grade_recipe_without_fixture_evidence(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expectation"]["recipe_relevance"]["鱼香肉丝"] = 0.0

        case = _load_temporary_eval_payload([payload])[0]

        self.assertEqual(case.expectation.recipe_relevance["鱼香肉丝"], 0.0)
        self.assertEqual(len(case.offline_fixture.evidence), 1)

    def test_review_distinguishes_boolean_and_wrong_numeric_types(self) -> None:
        bool_score = _valid_strict_eval_payload()
        bool_score["offline_fixture"]["evidence"][0]["score"] = True
        string_relevance = _valid_strict_eval_payload()
        string_relevance["expectation"]["recipe_relevance"]["宫保鸡丁"] = "high"

        with self.assertRaisesRegex(ValueError, r"score.*number, not a boolean"):
            _load_temporary_eval_payload([bool_score])
        with self.assertRaisesRegex(ValueError, r"recipe_relevance.*number.*got str"):
            _load_temporary_eval_payload([string_relevance])

    def test_strict_contract_parses_nested_case(self) -> None:
        case = _load_temporary_eval_payload([_valid_strict_eval_payload()])[0]

        self.assertEqual(case.case_id, "grounded-01")
        self.assertEqual(case.dimensions, ("single_recipe",))
        self.assertIs(case.expectation.response_mode, EvalResponseMode.GROUNDED_ANSWER)
        self.assertEqual(case.expectation.recipe_relevance, {"宫保鸡丁": 3.0})
        self.assertEqual(case.offline_fixture.evidence[0].recipe_name, "宫保鸡丁")

    def test_strict_contract_allows_unspecified_expected_strategy(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expectation"]["strategy"] = None

        case = _load_temporary_eval_payload([payload])[0]

        self.assertIsNone(case.expectation.strategy)
        self.assertEqual(case.offline_fixture.strategy, "hybrid_traditional")

    def test_strict_contract_rejects_legacy_expected_field(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expected_strategy"] = "hybrid_traditional"

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*grounded-01.*legacy.*expected_strategy",
        ):
            _load_temporary_eval_payload([payload])

    def test_strict_contract_rejects_duplicate_ids(self) -> None:
        payload = _valid_strict_eval_payload()

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[1\].*grounded-01.*duplicate",
        ):
            _load_temporary_eval_payload([payload, payload])

    def test_strict_contract_rejects_abstention_evidence(self) -> None:
        payload = _valid_strict_eval_payload()
        payload["expectation"]["response_mode"] = "no_evidence"
        payload["expectation"]["recipe_names"] = []
        payload["expectation"]["recipe_relevance"] = {}

        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*grounded-01.*abstention.*evidence",
        ):
            _load_temporary_eval_payload([payload])

    def test_strict_contract_rejects_non_object_rows(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            r"quality-eval\.json.*case\[0\].*JSON object",
        ):
            _load_temporary_eval_payload(["not-an-object"])

    def test_strict_contract_rejects_unknown_and_missing_keys_at_each_level(self) -> None:
        payloads: list[tuple[str, dict, str]] = []
        root_unknown = _valid_strict_eval_payload()
        root_unknown["surprise"] = True
        payloads.append(("root unknown", root_unknown, "surprise"))
        expectation_unknown = _valid_strict_eval_payload()
        expectation_unknown["expectation"]["surprise"] = True
        payloads.append(("expectation unknown", expectation_unknown, "surprise"))
        fixture_unknown = _valid_strict_eval_payload()
        fixture_unknown["offline_fixture"]["surprise"] = True
        payloads.append(("fixture unknown", fixture_unknown, "surprise"))
        evidence_unknown = _valid_strict_eval_payload()
        evidence_unknown["offline_fixture"]["evidence"][0]["surprise"] = True
        payloads.append(("evidence unknown", evidence_unknown, "surprise"))
        missing_root = _valid_strict_eval_payload()
        del missing_root["query"]
        payloads.append(("missing root", missing_root, "query"))
        missing_nested = _valid_strict_eval_payload()
        del missing_nested["expectation"]["strategy"]
        payloads.append(("missing nested", missing_nested, "strategy"))

        for label, payload, field_name in payloads:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    ValueError,
                    rf"quality-eval\.json.*case\[0\].*grounded-01.*{field_name}",
                ),
            ):
                _load_temporary_eval_payload([payload])

    def test_strict_contract_rejects_invalid_strings_lists_and_response_modes(self) -> None:
        payloads: list[tuple[str, dict, str]] = []
        empty_query = _valid_strict_eval_payload()
        empty_query["query"] = "  "
        payloads.append(("empty query", empty_query, "query"))
        empty_evidence_type = _valid_strict_eval_payload()
        empty_evidence_type["offline_fixture"]["evidence"][0]["evidence_type"] = ""
        payloads.append(("empty evidence type", empty_evidence_type, "evidence_type"))
        duplicate_dimensions = _valid_strict_eval_payload()
        duplicate_dimensions["dimensions"] = ["single_recipe", "single_recipe"]
        payloads.append(("duplicate dimensions", duplicate_dimensions, "dimensions"))
        unknown_mode = _valid_strict_eval_payload()
        unknown_mode["expectation"]["response_mode"] = "unsupported"
        payloads.append(("unknown mode", unknown_mode, "response_mode"))

        for label, payload, field_name in payloads:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    ValueError,
                    rf"quality-eval\.json.*case\[0\].*grounded-01.*{field_name}",
                ),
            ):
                _load_temporary_eval_payload([payload])

    def test_strict_contract_rejects_invalid_numeric_values(self) -> None:
        payloads: list[tuple[str, dict, str]] = []
        bool_relevance = _valid_strict_eval_payload()
        bool_relevance["expectation"]["recipe_relevance"]["宫保鸡丁"] = True
        payloads.append(("bool relevance", bool_relevance, "recipe_relevance"))
        negative_relevance = _valid_strict_eval_payload()
        negative_relevance["expectation"]["recipe_relevance"]["宫保鸡丁"] = -0.1
        payloads.append(("negative relevance", negative_relevance, "recipe_relevance"))
        nonfinite_relevance = _valid_strict_eval_payload()
        nonfinite_relevance["expectation"]["recipe_relevance"]["宫保鸡丁"] = math.inf
        payloads.append(("nonfinite relevance", nonfinite_relevance, "recipe_relevance"))
        bool_score = _valid_strict_eval_payload()
        bool_score["offline_fixture"]["evidence"][0]["score"] = False
        payloads.append(("bool score", bool_score, "score"))
        negative_score = _valid_strict_eval_payload()
        negative_score["offline_fixture"]["evidence"][0]["score"] = -0.1
        payloads.append(("negative score", negative_score, "score"))
        nonfinite_score = _valid_strict_eval_payload()
        nonfinite_score["offline_fixture"]["evidence"][0]["score"] = math.nan
        payloads.append(("nonfinite score", nonfinite_score, "score"))
        overflowing_score = _valid_strict_eval_payload()
        overflowing_score["offline_fixture"]["evidence"][0]["score"] = 10**400
        payloads.append(("overflowing score", overflowing_score, "score"))

        for label, payload, field_name in payloads:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    ValueError,
                    rf"quality-eval\.json.*case\[0\].*grounded-01.*{field_name}",
                ),
            ):
                _load_temporary_eval_payload([payload])

    def test_strict_contract_rejects_cross_field_inconsistencies(self) -> None:
        payloads: list[tuple[str, dict, str]] = []
        strategy_mismatch = _valid_strict_eval_payload()
        strategy_mismatch["offline_fixture"]["strategy"] = "graph_rag"
        payloads.append(("strategy mismatch", strategy_mismatch, "strategy"))
        grounded_without_evidence = _valid_strict_eval_payload()
        grounded_without_evidence["offline_fixture"]["evidence"] = []
        payloads.append(("grounded without evidence", grounded_without_evidence, "evidence"))
        missing_expected_recipe = _valid_strict_eval_payload()
        missing_expected_recipe["offline_fixture"]["evidence"][0]["recipe_name"] = "鱼香肉丝"
        payloads.append(("missing expected recipe", missing_expected_recipe, "宫保鸡丁"))
        abstention_recipe_names = _valid_strict_eval_payload()
        abstention_recipe_names["expectation"]["response_mode"] = "clarification"
        abstention_recipe_names["offline_fixture"]["evidence"] = []
        abstention_recipe_names["expectation"]["recipe_relevance"] = {}
        payloads.append(("abstention recipe names", abstention_recipe_names, "recipe_names"))
        abstention_relevance = _valid_strict_eval_payload()
        abstention_relevance["expectation"]["response_mode"] = "constraint_conflict"
        abstention_relevance["offline_fixture"]["evidence"] = []
        abstention_relevance["expectation"]["recipe_names"] = []
        payloads.append(("abstention relevance", abstention_relevance, "recipe_relevance"))

        for label, payload, detail in payloads:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    ValueError,
                    rf"quality-eval\.json.*case\[0\].*grounded-01.*{detail}",
                ),
            ):
                _load_temporary_eval_payload([payload])


class _FakeResponse:
    def __init__(
        self,
        *,
        answer: str,
        strategy: str,
        evidence_documents: list[dict],
        route_resolution: dict,
        latency_ms: float = 12.5,
        generation_trace: dict | None = None,
        route_trace: dict | None = None,
        diagnostics: dict | None = None,
        degradation_summary: dict | None = None,
    ) -> None:
        self.answer = answer
        self.strategy = strategy
        self.evidence_documents = list(evidence_documents)
        self.route_resolution = dict(route_resolution)
        self.latency_ms = latency_ms
        self.generation_trace = dict(generation_trace or {"mode": "two_stage"})
        self.route_trace = dict(route_trace or {"strategy": self.strategy})
        self.diagnostics = dict(diagnostics or {})
        self.degradation_summary = dict(degradation_summary or {})

    def to_dict(self) -> dict:
        return {
            "summary": {
                "answer": self.answer,
                "strategy": self.strategy,
                "latency_ms": self.latency_ms,
                "doc_count": len(self.evidence_documents),
                "has_evidence": bool(self.evidence_documents),
                "fallback_used": bool(self.generation_trace.get("fallback_used")),
                "error": "",
            },
            "grounding": {
                "retrieval_outcome": {
                    "query": self.route_resolution.get("understanding", {})
                    .get("query_plan", {})
                    .get("query", ""),
                    "strategy": self.strategy,
                    "doc_count": len(self.evidence_documents),
                    "evidence_documents": list(self.evidence_documents),
                    "degradation_summary": dict(self.degradation_summary),
                },
                "answer_context": {},
                "route_resolution": dict(self.route_resolution),
                "evidence_documents": list(self.evidence_documents),
            },
            "diagnostics": {
                "analysis": {
                    "recommended_strategy": self.strategy,
                },
                "diagnostics": {},
            },
            "traces": {
                "route_trace": dict(self.route_trace),
                "graph_trace": {},
                "generation_trace": dict(self.generation_trace),
                "trace_event": {"strategy": self.strategy},
            },
        }


class _FakeRouteResolution:
    def __init__(
        self,
        *,
        strategy: str,
        evidence_documents: list[dict],
        query: str,
    ) -> None:
        self.retrieval = SimpleNamespace(evidence_documents=list(evidence_documents))
        self.analysis = SimpleNamespace(recommended_strategy=SimpleNamespace(value=strategy))
        self.understanding = SimpleNamespace(
            query_plan=SimpleNamespace(
                to_dict=lambda: {
                    "query": query,
                    "used_cache": False,
                    "validation_errors": [],
                }
            )
        )
        self._payload = {
            "understanding": {
                "query": query,
                "query_plan": {
                    "query": query,
                    "used_cache": False,
                    "validation_errors": [],
                },
                "analysis": {
                    "recommended_strategy": strategy,
                },
            },
            "retrieval": {
                "query": query,
                "strategy": strategy,
                "doc_count": len(evidence_documents),
                "evidence_documents": list(evidence_documents),
            },
            "metadata": {},
        }

    def to_dict(self) -> dict:
        return dict(self._payload)


class _FakeSystem:
    def __init__(
        self,
        *,
        response: _FakeResponse | None = None,
        route_resolution: _FakeRouteResolution | None = None,
    ) -> None:
        self._response = response
        self.retrieval = SimpleNamespace(
            routing_workflow=SimpleNamespace(route=lambda query, top_k: route_resolution)
        )

    def answer_question_response(self, query: str, **kwargs) -> _FakeResponse:
        del query, kwargs
        if self._response is None:
            raise AssertionError("response was not configured")
        return self._response


class EvalQueriesTests(unittest.TestCase):
    def test_evaluate_queries_returns_report_and_closes_system(self) -> None:
        config = build_test_config()
        config.profile_name = "eval_quality"
        case = EvalCase(query="quality query")
        item = {"query": case.query, "passed": True}
        metrics = {"case_count": 1, "pass_rate": 1.0}
        system = MagicMock()

        with (
            patch("scripts.eval_queries.load_eval_cases", return_value=[case]),
            patch("scripts.eval_queries.load_config", return_value=config) as load_config,
            patch("scripts.eval_queries.AdvancedGraphRAGSystem", return_value=system),
            patch("scripts.eval_queries.evaluate_case", return_value=item),
            patch("scripts.eval_queries.calculate_eval_metrics", return_value=metrics),
        ):
            report = evaluate_queries(
                top_k=6,
                generate=True,
                profile="eval_quality",
            )

        load_config.assert_called_once_with(profile="eval_quality", profile_path=None)
        system.initialize_system.assert_called_once_with()
        system.build_knowledge_base.assert_called_once_with()
        system.close.assert_called_once_with()
        self.assertEqual(report["metrics"]["case_count"], 1)
        self.assertEqual(report["results"], [item])
        self.assertEqual(report["failures"], [])
        self.assertEqual(report["profile"]["name"], "eval_quality")
        self.assertTrue(report["generate"])

    def test_run_eval_preserves_json_output_and_failure_exit_code(self) -> None:
        item = {"query": "quality query", "passed": False}
        report = {
            "generated_at": "2026-06-27T00:00:00+00:00",
            "profile": {"name": "eval_quality", "path": "", "hash": ""},
            "corpus": str(DEFAULT_CORPUS_PATH.resolve()),
            "top_k": 6,
            "generate": True,
            "metrics": {"case_count": 1, "pass_rate": 0.0},
            "results": [item],
            "failures": [item],
        }

        with (
            patch("scripts.eval_queries.evaluate_queries", return_value=report),
            redirect_stdout(io.StringIO()) as stdout,
        ):
            exit_code = run_eval(
                top_k=6,
                as_json=True,
                generate=True,
                profile="eval_quality",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(stdout.getvalue()), report)

    def test_curated_eval_corpus_loads_from_fixture(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        cases = load_eval_cases(DEFAULT_CORPUS_PATH)

        self.assertGreaterEqual(len(cases), 9)
        self.assertTrue(any(case.expected_strategy == "graph_rag" for case in cases))
        self.assertTrue(any(case.category == "subgraph" for case in cases))
        self.assertTrue(any(case.category == "constrained_recommendation" for case in cases))
        self.assertTrue(any("水煮肉片" in case.query for case in cases))
        self.assertFalse(any("\ufffd" in case.query for case in cases))

    def test_offline_quality_queries_return_gate_metrics_without_runtime_services(self) -> None:
        with patch("scripts.eval_queries.AdvancedGraphRAGSystem") as system:
            report = evaluate_offline_quality_queries(
                top_k=6,
                generate=True,
                profile="eval_quality",
            )

        system.assert_not_called()
        metrics = report["metrics"]
        self.assertGreaterEqual(metrics["case_count"], 9)
        self.assertEqual(metrics["pass_rate"], 1.0)
        self.assertGreaterEqual(metrics["recall_at_k"], 0.8)
        self.assertGreaterEqual(metrics["faithfulness"], 0.8)
        self.assertGreaterEqual(metrics["citation_accuracy"], 0.8)
        self.assertEqual(metrics["fallback_rate"], 0.0)
        self.assertEqual(metrics["retrieval_degradation_rate"], 0.0)
        self.assertLessEqual(metrics["p95_latency_ms"], 2000.0)
        self.assertLessEqual(metrics["estimated_cost_usd"], 1.0)
        self.assertEqual(report["profile"]["name"], "eval_quality")
        self.assertFalse(report["failures"])

    def test_evaluate_case_generate_returns_response_native_contract(self) -> None:
        case = EvalCase(
            query="为什么水煮肉片里的豆瓣酱和花椒会共同形成麻辣鲜香？",
            category="complex_relation",
            expected_strategy="graph_rag",
            expected_recipe_names=["水煮肉片"],
            expected_answer_terms=["依据"],
        )
        evidence_documents = [
            {
                "recipe_name": "水煮肉片",
                "doc_id": "doc-1",
                "recipe_id": "recipe-1",
                "score": 0.96,
                "graph_evidence": {"relationships": [{"type": "CONTRIBUTES_TO"}]},
                "evidence_units": [{"is_graph_evidence": True}],
            }
        ]
        route_resolution = {
            "understanding": {
                "query_plan": {
                    "query": case.query,
                    "used_cache": True,
                    "validation_errors": [],
                }
            }
        }
        response = _FakeResponse(
            answer="依据菜谱证据和图谱关系，豆瓣酱与花椒共同贡献麻辣鲜香。",
            strategy="graph_rag",
            evidence_documents=evidence_documents,
            route_resolution=route_resolution,
        )

        item = evaluate_case(
            _FakeSystem(response=response),
            case,
            top_k=3,
            generate=True,
        )

        self.assertTrue(item["passed"])
        self.assertEqual(item["evaluation"]["strategy"], "graph_rag")
        self.assertTrue(item["evaluation"]["answer_checked"])
        self.assertEqual(item["retrieval"]["recipe_names"], ["水煮肉片"])
        self.assertEqual(item["runtime"]["plan_used_cache"], True)
        self.assertEqual(item["contracts"]["route_resolution"], {})
        self.assertEqual(
            set(item["contracts"]["answer_response"].keys()),
            {"summary", "grounding", "diagnostics", "traces"},
        )

    def test_evaluate_case_route_only_returns_route_resolution_contract(self) -> None:
        case = EvalCase(
            query="宫保鸡丁怎么做？",
            category="general",
            expected_strategy="hybrid_traditional",
            expected_recipe_names=["宫保鸡丁"],
        )
        evidence_documents = [
            {
                "recipe_name": "宫保鸡丁",
                "doc_id": "doc-2",
                "recipe_id": "recipe-2",
                "score": 0.9,
                "graph_evidence": {},
                "evidence_units": [],
            }
        ]
        route_resolution = _FakeRouteResolution(
            strategy="hybrid_traditional",
            evidence_documents=evidence_documents,
            query=case.query,
        )

        item = evaluate_case(
            _FakeSystem(route_resolution=route_resolution),
            case,
            top_k=2,
            generate=False,
        )

        self.assertTrue(item["passed"])
        self.assertFalse(item["evaluation"]["answer_checked"])
        self.assertEqual(item["contracts"]["answer_response"], {})
        self.assertEqual(
            item["contracts"]["route_resolution"]["retrieval"]["strategy"],
            "hybrid_traditional",
        )
        self.assertEqual(item["retrieval"]["doc_count"], 1)

    def test_evaluate_case_reports_fallback_and_degraded_sources(self) -> None:
        case = EvalCase(
            query="解释带降级的回答",
            category="complex_relation",
            expected_strategy="graph_rag",
            expected_recipe_names=["水煮肉片"],
            expected_answer_terms=["依据"],
        )
        evidence_documents = [
            {
                "recipe_name": "水煮肉片",
                "doc_id": "doc-1",
                "recipe_id": "recipe-1",
                "score": 0.96,
                "content": "水煮肉片使用花椒和豆瓣酱形成麻辣风味。",
                "graph_evidence": {"relationships": [{"type": "CONTRIBUTES_TO"}]},
                "evidence_units": [
                    {"claim": "花椒和豆瓣酱共同贡献麻辣风味。", "is_graph_evidence": True}
                ],
            }
        ]
        response = _FakeResponse(
            answer="依据 Evidence 1，花椒和豆瓣酱共同贡献麻辣风味。",
            strategy="graph_rag",
            evidence_documents=evidence_documents,
            route_resolution={
                "understanding": {
                    "query_plan": {
                        "query": case.query,
                        "used_cache": False,
                        "validation_errors": [],
                    }
                }
            },
            generation_trace={
                "status": "degraded",
                "mode": "two_stage",
                "fallback_used": True,
                "fallback_reason": "two_stage_to_direct_model",
            },
            route_trace={
                "strategy": "graph_rag",
                "fallbacks": ["graph_empty_to_hybrid"],
                "diagnostics": {
                    "used_fallback": True,
                    "fallback_count": 1,
                    "retrieval_degraded": True,
                    "degraded_sources": ["vector"],
                    "degraded_candidates": [{"source": "vector", "reason": "circuit_open"}],
                },
            },
            diagnostics={
                "retrieval_degraded": True,
                "degraded_sources": ["vector"],
                "degraded_candidates": [{"source": "vector", "reason": "circuit_open"}],
            },
            degradation_summary={
                "retrieval_degraded": True,
                "degraded_sources": ["vector"],
                "degraded_candidates": [{"source": "vector", "reason": "circuit_open"}],
            },
        )

        item = evaluate_case(
            _FakeSystem(response=response),
            case,
            top_k=3,
            generate=True,
        )

        self.assertTrue(item["resilience"]["fallback_used"])
        self.assertEqual(
            item["resilience"]["fallback_reasons"],
            ["two_stage_to_direct_model", "graph_empty_to_hybrid"],
        )
        self.assertTrue(item["resilience"]["retrieval_degraded"])
        self.assertEqual(item["resilience"]["degraded_sources"], ["vector"])
        self.assertEqual(
            item["resilience"]["degraded_candidates"],
            [{"source": "vector", "reason": "circuit_open"}],
        )

    def test_build_eval_report_includes_profile_metadata(self) -> None:
        config = build_test_config()
        config.profile_name = "eval_fast"
        config.profile_path = "profiles/eval_fast.toml"
        config.profile_hash = "abc123"

        report = build_eval_report(
            metrics={"case_count": 1, "pass_rate": 1.0},
            results=[{"query": "q", "passed": True}],
            failures=[],
            config=config,
            corpus_path=DEFAULT_CORPUS_PATH,
            top_k=3,
            generate=False,
            generated_at="2026-01-01T00:00:00+00:00",
        )

        self.assertEqual(report["profile"]["name"], "eval_fast")
        self.assertEqual(report["profile"]["hash"], "abc123")
        self.assertEqual(report["top_k"], 3)
        self.assertFalse(report["generate"])
        self.assertEqual(report["metrics"]["pass_rate"], 1.0)
        self.assertEqual(report["policy"]["policy_version"], "c9-default-policy-v1")
        self.assertEqual(report["policy"]["prompt_version"], "c9-default-prompts-v1")
        self.assertTrue(report["policy"]["policy_hash"].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
