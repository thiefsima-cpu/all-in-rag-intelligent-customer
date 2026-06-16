"""Offline golden smoke for the end-to-end answer pipeline snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.app.services.answer_workflow import AnswerWorkflow
from rag_modules.configuration.testing import build_test_config
from rag_modules.query_understanding import QueryPlan
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import (
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RouteResolution,
    RouteSnapshot,
    RouteStageSnapshot,
)
from scripts.smoke_answer_pipeline_support import (
    OfflineGenerationModule as _OfflineGenerationModule,
    build_tracer as _build_tracer,
)


DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "answer_pipeline_corpus.json"
)


class _OfflineQueryRouter:
    def __init__(self, *, case: "AnswerPipelineCase", top_k: int = 5) -> None:
        self.case = case
        self.top_k = top_k
        self.route_trace = build_route_snapshot(case, requested_top_k=top_k)
        self.graph_trace = build_graph_snapshot(case, requested_top_k=top_k)
        if self.graph_trace.has_content():
            stage_name = (
                "combined"
                if self.route_trace.strategy == "combined"
                else "graph_rag"
            )
            stage = self.route_trace.stages.get(stage_name)
            if stage is not None:
                stage.details["graph_trace"] = self.graph_trace.to_dict()

    def explain_routing_decision(self, question: str) -> str:
        return f"offline-route::{question}::{self.case.analysis.strategy_name}"

    def route(self, question: str, top_k: int):
        del top_k
        understanding = build_understanding_snapshot(self.case)
        outcome = RetrievalOutcome(
            query=question,
            strategy=self.case.analysis.strategy_name,
            evidence_documents=list(self.case.evidence_documents),
            route_trace=self.route_trace,
            metadata={"query_understanding": understanding.to_dict()},
        )
        return RouteResolution(
            understanding=understanding,
            retrieval=outcome,
        )

    def route_with_trace(self, question: str, top_k: int):
        return self.route(question, top_k), RouteSnapshot.from_dict(
            self.route_trace.to_dict()
        )


@dataclass
class AnswerPipelineCase:
    name: str
    question: str
    analysis: QueryAnalysis
    evidence_documents: List[EvidenceDocument]
    answer_text: str
    expected_route_strategy: str
    expected_generation_mode: str
    expected_graph_doc_count: int
    expected_stage_names: List[str] = field(default_factory=list)
    required_failure_reasons: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "AnswerPipelineCase":
        return cls(
            name=str(payload.get("name") or "").strip(),
            question=str(payload.get("question") or "").strip(),
            analysis=QueryAnalysis.from_dict(payload.get("analysis") or {}),
            evidence_documents=[
                EvidenceDocument.from_dict(item)
                for item in (payload.get("evidence_documents") or [])
                if isinstance(item, dict)
            ],
            answer_text=str(payload.get("answer_text") or "").strip(),
            expected_route_strategy=str(payload.get("expected_route_strategy") or "").strip(),
            expected_generation_mode=str(payload.get("expected_generation_mode") or "").strip(),
            expected_graph_doc_count=int(payload.get("expected_graph_doc_count") or 0),
            expected_stage_names=[
                str(item).strip()
                for item in (payload.get("expected_stage_names") or [])
                if str(item).strip()
            ],
            required_failure_reasons=[
                str(item).strip()
                for item in (payload.get("required_failure_reasons") or [])
                if str(item).strip()
            ],
        )


def load_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[AnswerPipelineCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Answer pipeline corpus at {corpus_path} must be a JSON list.")
    return [AnswerPipelineCase.from_dict(item) for item in payload if isinstance(item, dict)]


def _graph_doc_count(documents: Iterable[EvidenceDocument]) -> int:
    count = 0
    for doc in documents:
        evidence_units = doc.evidence_units or []
        if any(bool(unit.get("is_graph_evidence")) for unit in evidence_units):
            count += 1
    return count


def build_route_snapshot(case: AnswerPipelineCase, *, requested_top_k: int) -> RouteSnapshot:
    strategy = case.expected_route_strategy
    graph_doc_count = _graph_doc_count(case.evidence_documents) if strategy != "hybrid_traditional" else 0
    final_doc_count = len(case.evidence_documents)
    snapshot = RouteSnapshot(
        query=case.question,
        strategy=strategy,
        requested_top_k=requested_top_k,
    )
    snapshot.add_stage(
        "plan",
        RouteStageSnapshot(
            latency_ms=1.0,
            doc_count=0,
            details={"used_cache": True, "strategy": strategy},
        ),
    )
    if strategy == "graph_rag":
        snapshot.add_stage(
            "graph_rag",
            RouteStageSnapshot(latency_ms=2.0, doc_count=final_doc_count, sources={"graph_rag": final_doc_count}),
        )
    elif strategy == "hybrid_traditional":
        snapshot.add_stage(
            "hybrid",
            RouteStageSnapshot(latency_ms=2.0, doc_count=final_doc_count, sources={"hybrid": final_doc_count}),
        )
    elif strategy == "combined":
        snapshot.add_stage(
            "graph_rag",
            RouteStageSnapshot(latency_ms=1.5, doc_count=graph_doc_count, sources={"graph_rag": graph_doc_count}),
        )
        snapshot.add_stage(
            "combined",
            RouteStageSnapshot(latency_ms=2.5, doc_count=final_doc_count, sources={"combined": final_doc_count}),
        )
    snapshot.add_stage(
        "post_process",
        RouteStageSnapshot(latency_ms=0.8, doc_count=final_doc_count, sources={strategy: final_doc_count}),
    )
    snapshot.finalize(total_latency_ms=4.2, final_doc_count=final_doc_count)
    return snapshot


def build_graph_snapshot(case: AnswerPipelineCase, *, requested_top_k: int) -> GraphRetrievalSnapshot:
    strategy = case.expected_route_strategy
    if strategy == "hybrid_traditional":
        return GraphRetrievalSnapshot()
    graph_doc_count = _graph_doc_count(case.evidence_documents)
    snapshot = GraphRetrievalSnapshot(
        query=case.question,
        strategy="graph_rag",
        requested_top_k=requested_top_k,
        query_type="multi_hop" if case.analysis.reasoning_required else "entity_relation",
        relation_types=["CONTRIBUTES_TO"] if graph_doc_count else [],
        path_count=graph_doc_count,
        evidence_unit_count=sum(len(doc.evidence_units or []) for doc in case.evidence_documents),
        doc_count=graph_doc_count,
        total_latency_ms=2.1,
    )
    snapshot.add_event("plan", latency_ms=0.4, details={"strategy": strategy})
    snapshot.add_event("execute", latency_ms=1.2, details={"graph_doc_count": graph_doc_count})
    snapshot.add_event("postprocess", latency_ms=0.5, details={"doc_count": graph_doc_count})
    return snapshot


def build_understanding_snapshot(case: AnswerPipelineCase):
    return QueryUnderstandingSnapshot(
        query=case.question,
        query_plan=QueryPlan(
            query=case.question,
            strategy=case.expected_route_strategy,
            complexity=case.analysis.query_complexity,
            relationship_intensity=case.analysis.relationship_intensity,
            reasoning_required=case.analysis.reasoning_required,
            confidence=case.analysis.confidence,
            reasoning=case.analysis.reasoning,
            semantic_profile=case.analysis.semantic_profile,
        ),
        analysis=case.analysis,
        semantic_profile=case.analysis.semantic_profile,
    )

def evaluate_case(case: AnswerPipelineCase) -> dict:
    router = _OfflineQueryRouter(case=case)
    generation_module = _OfflineGenerationModule([case.answer_text])
    tracer, sink = _build_tracer()
    config = build_test_config({"retrieval": {"top_k": 5}})
    service = AnswerWorkflow(
        config=config,
        query_router=router,
        generation_module=generation_module,
        query_tracer=tracer,
    )
    result = service.answer_question(case.question)
    response = result.to_response()
    event = sink.events[-1]
    route_trace = response.route_trace
    route_diagnostics = route_trace.get("diagnostics") or {}
    route_resolution = response.route_resolution
    route_resolution_analysis = (
        route_resolution.get("understanding", {}).get("analysis", {})
        if isinstance(route_resolution, dict)
        else {}
    )
    answer_context = response.answer_context
    answer_understanding = (
        answer_context.get("understanding", {})
        if isinstance(answer_context, dict)
        else {}
    )

    failures: List[str] = []
    if result.analysis is None or response.strategy != case.expected_route_strategy:
        failures.append(
            f"expected_route_strategy={case.expected_route_strategy} "
            f"actual_route_strategy={response.strategy}"
        )
    if route_trace.get("strategy") != case.expected_route_strategy:
        failures.append(
            f"route_snapshot_strategy_mismatch={route_trace.get('strategy', '')}"
        )
    if route_resolution_analysis.get("recommended_strategy") != case.expected_route_strategy:
        failures.append(
            "route_resolution_strategy_mismatch="
            f"{route_resolution_analysis.get('recommended_strategy', '')}"
        )
    if not answer_understanding:
        failures.append("missing_answer_context_understanding")
    elif answer_understanding.get("analysis", {}).get("recommended_strategy") != case.expected_route_strategy:
        failures.append(
            "answer_context_strategy_mismatch="
            f"{answer_understanding.get('analysis', {}).get('recommended_strategy', '')}"
        )
    if response.generation_trace.get("mode") != case.expected_generation_mode:
        failures.append(
            "expected_generation_mode="
            f"{case.expected_generation_mode} actual_generation_mode={response.generation_trace.get('mode', '')}"
        )
    stage_names = list((route_trace.get("stages") or {}).keys())
    if stage_names != case.expected_stage_names:
        failures.append(f"expected_stage_names={case.expected_stage_names} actual_stage_names={stage_names}")
    if route_diagnostics.get("graph_doc_count") != case.expected_graph_doc_count:
        failures.append(
            f"expected_graph_doc_count={case.expected_graph_doc_count} "
            f"actual_graph_doc_count={route_diagnostics.get('graph_doc_count')}"
        )
    for reason in case.required_failure_reasons:
        if reason not in (route_diagnostics.get("failure_reasons") or []):
            failures.append(f"missing_failure_reason={reason}")
    if case.answer_text not in response.answer:
        failures.append("answer_text_mismatch")
    if event.strategy != case.expected_route_strategy:
        failures.append(f"trace_event_strategy_mismatch={event.strategy}")
    if event.retrieval.doc_count != len(case.evidence_documents):
        failures.append(
            f"trace_event_doc_count_mismatch={event.retrieval.doc_count}"
        )

    return {
        "name": case.name,
        "question": case.question,
        "passed": not failures,
        "failures": failures,
        "strategy": response.strategy,
        "generation_mode": response.generation_trace.get("mode", ""),
        "answer_preview": response.answer[:120],
        "answer_response": response.to_dict(),
    }


def run_smoke(corpus_path: str | Path = DEFAULT_CORPUS_PATH) -> dict:
    results = [evaluate_case(case) for case in load_cases(corpus_path)]
    failures = [item for item in results if not item["passed"]]
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
        "results": results,
        "failures": failures,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS_PATH))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = run_smoke(args.corpus)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"case_count={report['case_count']} passed_count={report['passed_count']}")
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(
                f"[{status}] {item['name']} "
                f"strategy={item['strategy']} generation_mode={item['generation_mode']}"
            )
            if item["failures"]:
                print(f"  failures={item['failures']}")

    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
