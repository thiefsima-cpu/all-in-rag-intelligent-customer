from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from scripts.eval_queries import (
    DEFAULT_CORPUS_PATH,
    EvalCase,
    build_eval_report,
    evaluate_case,
    load_eval_cases,
)


class _FakeResponse:
    def __init__(
        self,
        *,
        answer: str,
        strategy: str,
        evidence_documents: list[dict],
        route_resolution: dict,
        latency_ms: float = 12.5,
    ) -> None:
        self.answer = answer
        self.strategy = strategy
        self.evidence_documents = list(evidence_documents)
        self.route_resolution = dict(route_resolution)
        self.latency_ms = latency_ms

    def to_dict(self) -> dict:
        return {
            "summary": {
                "answer": self.answer,
                "strategy": self.strategy,
                "latency_ms": self.latency_ms,
                "doc_count": len(self.evidence_documents),
                "has_evidence": bool(self.evidence_documents),
                "error": "",
            },
            "grounding": {
                "retrieval_outcome": {
                    "query": self.route_resolution.get("understanding", {}).get("query_plan", {}).get("query", ""),
                    "strategy": self.strategy,
                    "doc_count": len(self.evidence_documents),
                    "evidence_documents": list(self.evidence_documents),
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
                "route_trace": {"strategy": self.strategy},
                "graph_trace": {},
                "generation_trace": {"mode": "two_stage"},
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
        self.analysis = SimpleNamespace(
            recommended_strategy=SimpleNamespace(value=strategy)
        )
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
    def test_curated_eval_corpus_loads_from_fixture(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        cases = load_eval_cases(DEFAULT_CORPUS_PATH)

        self.assertGreaterEqual(len(cases), 4)
        self.assertTrue(any(case.expected_strategy == "graph_rag" for case in cases))
        self.assertTrue(any("水煮肉片" in case.query for case in cases))
        self.assertFalse(any("\ufffd" in case.query for case in cases))

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


if __name__ == "__main__":
    unittest.main()
