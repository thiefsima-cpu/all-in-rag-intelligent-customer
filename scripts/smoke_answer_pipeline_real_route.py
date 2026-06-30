"""Offline golden smoke for answer pipeline snapshots with real query understanding."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rag_modules.app.services.answer_workflow import AnswerWorkflow
from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import (
    EvidenceDocument,
    QueryPlan,
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
    RetrievalRequest,
)
from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.query_understanding import QueryPlanner
from rag_modules.retrieval.hybrid_outcome import HybridRetrievalOutcome
from rag_modules.retrieval.runtime_profile import (
    RetrievalCandidateSizingSettings,
    RetrievalPostProcessSettings,
    RetrievalRuntimeProfile,
)
from rag_modules.routing import IntelligentQueryRouter
from rag_modules.runtime import GraphRetrievalSnapshot, QueryUnderstandingSnapshot
from scripts.smoke_answer_pipeline_support import (
    OfflineGenerationModule,
    build_tracer,
)

DEFAULT_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "tests"
    / "fixtures"
    / "answer_pipeline_real_route_corpus.json"
)


@dataclass
class RealRouteAnswerPipelineCase:
    name: str
    question: str
    answer_text: str
    expected_route_strategy: str
    expected_generation_mode: str
    expected_stage_names: List[str] = field(default_factory=list)
    required_failure_reasons: List[str] = field(default_factory=list)
    expected_graph_event_names: List[str] = field(default_factory=list)
    expected_graph_query_type: str = ""
    expected_graph_doc_count: int = 0
    expected_graph_snapshot_doc_count: int = 0
    min_complexity: float = 0.0
    min_relationship_intensity: float = 0.0
    top_k: int = 2
    hybrid_documents: List[EvidenceDocument] = field(default_factory=list)
    graph_documents: List[EvidenceDocument] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict) -> "RealRouteAnswerPipelineCase":
        return cls(
            name=str(payload.get("name") or "").strip(),
            question=str(payload.get("question") or "").strip(),
            answer_text=str(payload.get("answer_text") or "").strip(),
            expected_route_strategy=str(payload.get("expected_route_strategy") or "").strip(),
            expected_generation_mode=str(payload.get("expected_generation_mode") or "").strip(),
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
            expected_graph_event_names=[
                str(item).strip()
                for item in (payload.get("expected_graph_event_names") or [])
                if str(item).strip()
            ],
            expected_graph_query_type=str(payload.get("expected_graph_query_type") or "").strip(),
            expected_graph_doc_count=int(payload.get("expected_graph_doc_count") or 0),
            expected_graph_snapshot_doc_count=int(
                payload.get("expected_graph_snapshot_doc_count") or 0
            ),
            min_complexity=float(payload.get("min_complexity") or 0.0),
            min_relationship_intensity=float(payload.get("min_relationship_intensity") or 0.0),
            top_k=max(1, int(payload.get("top_k") or 2)),
            hybrid_documents=[
                EvidenceDocument.from_dict(item)
                for item in (payload.get("hybrid_documents") or [])
                if isinstance(item, dict)
            ],
            graph_documents=[
                EvidenceDocument.from_dict(item)
                for item in (payload.get("graph_documents") or [])
                if isinstance(item, dict)
            ],
        )


CONTRACT_METRIC_NAMES = {
    "plan": "plan_contract_pass_rate",
    "request": "request_contract_pass_rate",
    "trace": "trace_contract_pass_rate",
    "graph": "graph_contract_pass_rate",
    "evidence": "evidence_contract_pass_rate",
    "offline_planner": "offline_planner_guard_pass_rate",
}


def _graph_expected(case: RealRouteAnswerPipelineCase) -> bool:
    return (
        case.expected_route_strategy in {"graph_rag", "combined"}
        or case.expected_graph_doc_count > 0
        or bool(case.expected_graph_query_type)
    )


def _graph_evidence_unit_count(documents: List[EvidenceDocument]) -> int:
    return sum(
        1
        for document in documents
        for unit in (document.evidence_units or [])
        if unit.get("is_graph_evidence")
    )


def _rate(passed_count: int, total_count: int) -> float:
    return passed_count / total_count if total_count else 0.0


def load_cases(path: str | Path = DEFAULT_CORPUS_PATH) -> List[RealRouteAnswerPipelineCase]:
    corpus_path = Path(path).resolve()
    with corpus_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Answer pipeline corpus at {corpus_path} must be a JSON list.")
    return [
        RealRouteAnswerPipelineCase.from_dict(item) for item in payload if isinstance(item, dict)
    ]


class _StaticHybridRetrieval:
    def __init__(self, case: RealRouteAnswerPipelineCase) -> None:
        self.case = case

    def hybrid_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        candidate_k: int | None = None,
        query_plan: QueryPlan | None = None,
    ) -> HybridRetrievalOutcome:
        del top_k, constraints, candidate_k, query_plan
        request = self._normalize_request(request_or_query)
        limit = request.effective_candidate_k
        documents = list(self.case.hybrid_documents[:limit])
        return HybridRetrievalOutcome(
            documents=documents,
            candidate_counts={"static_hybrid": len(documents)},
        )

    @staticmethod
    def enrich_to_parent_evidence_documents(
        docs: List[EvidenceDocument],
        top_n: int | None = None,
    ) -> List[EvidenceDocument]:
        if top_n is None:
            return list(docs)
        return list(docs[:top_n])

    def close(self) -> None:
        return None

    @staticmethod
    def _normalize_request(request_or_query: str | RetrievalRequest) -> RetrievalRequest:
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(query=str(request_or_query or ""))


class _StaticGraphRetrieval:
    def __init__(self, case: RealRouteAnswerPipelineCase) -> None:
        self.case = case

    def graph_rag_evidence_search(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> List[EvidenceDocument]:
        documents, _trace = self.graph_rag_evidence_search_with_trace(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            query_plan=query_plan,
        )
        return documents

    def graph_rag_evidence_search_with_trace(
        self,
        request_or_query: str | RetrievalRequest,
        top_k: int = 5,
        constraints: QueryConstraints | None = None,
        query_plan: QueryPlan | None = None,
    ) -> tuple[List[EvidenceDocument], GraphRetrievalSnapshot]:
        del constraints
        request = self._normalize_request(
            request_or_query,
            top_k=top_k,
            query_plan=query_plan,
        )
        documents = list(self.case.graph_documents[: request.effective_candidate_k])
        trace = self._build_snapshot(
            request=request,
            query_plan=query_plan,
            documents=documents,
        )
        return documents, trace

    def initialize(self) -> None:
        return None

    def close(self) -> None:
        return None

    @staticmethod
    def _normalize_request(
        request_or_query: str | RetrievalRequest,
        *,
        top_k: int,
        query_plan: QueryPlan | None,
    ) -> RetrievalRequest:
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(
            query=str(request_or_query or ""),
            top_k=top_k,
            candidate_k=top_k,
            query_plan=query_plan,
        )

    @staticmethod
    def _build_snapshot(
        *,
        request: RetrievalRequest,
        query_plan: QueryPlan | None,
        documents: List[EvidenceDocument],
    ) -> GraphRetrievalSnapshot:
        plan = query_plan or request.query_plan
        snapshot = GraphRetrievalSnapshot(
            query=request.query,
            strategy="graph_rag",
            requested_top_k=request.top_k,
            retrieval_request=request,
            query_type=plan.graph_query_type_value if plan else "",
            source_entities=list(plan.source_entities if plan else []),
            target_entities=list(plan.target_entities if plan else []),
            relation_types=list(plan.relation_types if plan else []),
            path_count=len(documents),
            evidence_unit_count=sum(len(doc.evidence_units or []) for doc in documents),
            doc_count=len(documents),
            retrieval_plan=plan.to_dict() if plan else {},
            total_latency_ms=2.1,
        )
        snapshot.add_event(
            "plan",
            latency_ms=0.3,
            details={
                "query_type": snapshot.query_type,
                "source_entities": list(snapshot.source_entities or []),
            },
        )
        snapshot.add_event(
            "execute",
            latency_ms=1.2,
            details={
                "graph_doc_count": len(documents),
                "relation_types": list(snapshot.relation_types or []),
            },
        )
        snapshot.add_event(
            "postprocess",
            latency_ms=0.6,
            details={
                "evidence_unit_count": snapshot.evidence_unit_count,
            },
        )
        return snapshot


class _OfflineQueryUnderstandingService:
    def __init__(self, retrieval_profile: RetrievalRuntimeProfile) -> None:
        self.query_planner = QueryPlanner(
            None,
            settings=retrieval_profile.planner,
            semantic_settings=retrieval_profile.semantics,
        )

    def understand(self, query: str) -> QueryUnderstandingSnapshot:
        return QueryUnderstandingSnapshot.from_plan(self.query_planner.rule_based_plan(query))


def build_retrieval_profile(top_k: int) -> RetrievalRuntimeProfile:
    return RetrievalRuntimeProfile(
        planner=QueryPlannerRuntimeSettings(fast_rule_planning=True),
        semantics=QuerySemanticRuntimeSettings(),
        candidates=RetrievalCandidateSizingSettings(
            hybrid_default_multiplier=1,
            hybrid_default_min_candidates=top_k,
            hybrid_constraint_multiplier=1,
            hybrid_constraint_min_candidates=top_k,
            combined_multiplier=1,
            combined_min_candidates=top_k,
            graph_supplement_multiplier=1,
            graph_supplement_min_candidates=top_k,
        ),
        postprocess=RetrievalPostProcessSettings(enable_rerank=False),
    )


def evaluate_contracts(
    *,
    case: RealRouteAnswerPipelineCase,
    result,
    response,
    event,
    plan: QueryPlan | None,
) -> dict[str, dict]:
    checks = {key: {"passed": True, "failures": []} for key in CONTRACT_METRIC_NAMES}

    def fail(category: str, reason: str) -> None:
        checks[category]["passed"] = False
        checks[category]["failures"].append(reason)

    response_payload = response.to_dict()
    route_trace = response_payload["traces"]["route_trace"]
    graph_trace = response_payload["traces"]["graph_trace"]
    route_request = result.route_trace.retrieval_request
    graph_expected = _graph_expected(case)
    plan_graph_query_type = plan.graph_query_type_value if plan else ""

    plan_stage = dict((route_trace.get("stages") or {}).get("plan") or {})
    planner_mode = str(plan_stage.get("planner_mode") or "")

    if plan is None:
        fail("plan", "missing_query_plan")
        fail("offline_planner", "missing_query_plan")
    else:
        if plan.query != case.question:
            fail("plan", "plan_query_mismatch")
        if plan.strategy != case.expected_route_strategy:
            fail("plan", f"plan_strategy_mismatch={plan.strategy}")
        if (
            case.expected_graph_query_type
            and plan_graph_query_type != case.expected_graph_query_type
        ):
            fail(
                "plan",
                f"plan_graph_query_type_mismatch={plan_graph_query_type}",
            )
        if plan.validation_errors:
            fail("plan", f"plan_validation_errors={plan.validation_errors}")
        if planner_mode not in {"fast_rule", "rule_based"}:
            fail("offline_planner", f"planner_mode_not_offline={planner_mode}")
        if plan.fallback_reason == "query_planning_failed":
            fail("offline_planner", "planner_used_exception_fallback")

    if route_request is None:
        fail("request", "missing_route_retrieval_request")
    else:
        if route_request.query != case.question:
            fail("request", "route_request_query_mismatch")
        if route_request.top_k != case.top_k:
            fail("request", f"route_request_top_k_mismatch={route_request.top_k}")
        if route_request.effective_candidate_k < case.top_k:
            fail(
                "request",
                f"candidate_k_below_top_k={route_request.effective_candidate_k}",
            )
        if route_request.strategy != case.expected_route_strategy:
            fail(
                "request",
                f"route_request_strategy_mismatch={route_request.strategy}",
            )
        if route_request.query_plan is None:
            fail("request", "route_request_missing_query_plan")

    trace_event = response_payload["traces"]["trace_event"]
    event_plan = dict(event.plan or {})
    route_request_payload = dict(route_trace.get("retrieval_request") or {})
    route_plan_payload = dict(route_request_payload.get("query_plan") or {})
    if route_trace.get("strategy") != response.strategy:
        fail("trace", "route_trace_strategy_response_mismatch")
    if route_trace.get("final_doc_count") != response.doc_count:
        fail("trace", "route_trace_final_doc_count_response_mismatch")
    if trace_event.get("strategy") != response.strategy:
        fail("trace", "response_trace_event_strategy_mismatch")
    if event.strategy != response.strategy:
        fail("trace", "sink_trace_event_strategy_mismatch")
    if event.retrieval.doc_count != response.doc_count:
        fail("trace", "sink_trace_event_doc_count_mismatch")
    if not route_plan_payload:
        fail("trace", "route_trace_missing_query_plan_payload")
    if plan and event_plan.get("graph_query_type") != plan_graph_query_type:
        fail("trace", "sink_trace_event_plan_graph_query_type_mismatch")

    graph_doc_count = int(graph_trace.get("doc_count") or 0)
    graph_events = [
        str(item.get("name") or "")
        for item in (graph_trace.get("events") or [])
        if isinstance(item, dict)
    ]
    graph_request = dict(graph_trace.get("retrieval_request") or {})
    graph_plan = dict(graph_trace.get("retrieval_plan") or {})
    if graph_expected:
        if graph_doc_count != case.expected_graph_snapshot_doc_count:
            fail("graph", f"graph_doc_count_mismatch={graph_doc_count}")
        if graph_events != case.expected_graph_event_names:
            fail("graph", f"graph_events_mismatch={graph_events}")
        if not graph_request.get("query"):
            fail("graph", "graph_trace_missing_request_query")
        if not graph_plan:
            fail("graph", "graph_trace_missing_retrieval_plan")
        if (
            case.expected_graph_query_type
            and graph_trace.get("query_type") != case.expected_graph_query_type
        ):
            fail("graph", f"graph_query_type_mismatch={graph_trace.get('query_type')}")
    else:
        if graph_doc_count or graph_events or graph_plan:
            fail("graph", "hybrid_case_has_graph_trace_content")

    graph_evidence_units = _graph_evidence_unit_count(result.evidence_documents)
    if graph_expected:
        if graph_evidence_units <= 0:
            fail("evidence", "missing_graph_evidence_units")
        if int(graph_trace.get("evidence_unit_count") or 0) <= 0:
            fail("evidence", "graph_trace_missing_evidence_units")
    else:
        if graph_evidence_units:
            fail(
                "evidence",
                f"hybrid_case_has_graph_evidence_units={graph_evidence_units}",
            )
        if not result.evidence_documents:
            fail("evidence", "hybrid_case_missing_evidence_documents")

    return checks


def evaluate_case(case: RealRouteAnswerPipelineCase) -> dict:
    retrieval_profile = build_retrieval_profile(case.top_k)
    hybrid_retrieval = _StaticHybridRetrieval(case)
    graph_retrieval = _StaticGraphRetrieval(case)
    config = build_test_config({"retrieval": {"top_k": case.top_k}})
    router = IntelligentQueryRouter(
        traditional_retrieval=hybrid_retrieval,
        graph_rag_retrieval=graph_retrieval,
        llm_client=None,
        config=config,
        retrieval_profile=retrieval_profile,
        query_understanding_service=_OfflineQueryUnderstandingService(retrieval_profile),
    )
    generation_module = OfflineGenerationModule([case.answer_text])
    tracer, sink = build_tracer()
    service = AnswerWorkflow(
        config=config,
        query_router=router,
        generation_module=generation_module,
        query_tracer=tracer,
    )
    result = service.answer_question(case.question)
    response = result.to_response()
    response_payload = response.to_dict()
    event = sink.events[-1]
    plan = (
        result.route_trace.retrieval_request.query_plan
        if result.route_trace.retrieval_request
        else None
    )
    route_trace = response_payload["traces"]["route_trace"]
    route_diagnostics = route_trace.get("diagnostics") or {}
    graph_trace = response_payload["traces"]["graph_trace"]
    generation_trace = response_payload["traces"]["generation_trace"]

    failures: List[str] = []
    if result.analysis is None:
        failures.append("missing_analysis")
    else:
        if response.strategy != case.expected_route_strategy:
            failures.append(
                f"expected_route_strategy={case.expected_route_strategy} "
                f"actual_route_strategy={response.strategy}"
            )
        if result.analysis.query_complexity < case.min_complexity:
            failures.append(
                f"complexity_below_threshold={result.analysis.query_complexity:.2f}<{case.min_complexity:.2f}"
            )
        if result.analysis.relationship_intensity < case.min_relationship_intensity:
            failures.append(
                "relationship_intensity_below_threshold="
                f"{result.analysis.relationship_intensity:.2f}<{case.min_relationship_intensity:.2f}"
            )

    if route_trace.get("strategy") != case.expected_route_strategy:
        failures.append(f"route_snapshot_strategy_mismatch={route_trace.get('strategy', '')}")
    stage_names = list((route_trace.get("stages") or {}).keys())
    if stage_names != case.expected_stage_names:
        failures.append(
            f"expected_stage_names={case.expected_stage_names} actual_stage_names={stage_names}"
        )
    if generation_trace.get("mode") != case.expected_generation_mode:
        failures.append(
            "expected_generation_mode="
            f"{case.expected_generation_mode} actual_generation_mode={generation_trace.get('mode', '')}"
        )
    if route_diagnostics.get("graph_doc_count") != case.expected_graph_doc_count:
        failures.append(
            f"expected_graph_doc_count={case.expected_graph_doc_count} "
            f"actual_graph_doc_count={route_diagnostics.get('graph_doc_count')}"
        )
    if graph_trace.get("doc_count") != case.expected_graph_snapshot_doc_count:
        failures.append(
            f"expected_graph_snapshot_doc_count={case.expected_graph_snapshot_doc_count} "
            f"actual_graph_snapshot_doc_count={graph_trace.get('doc_count')}"
        )
    if case.expected_graph_query_type:
        actual_graph_query_type = plan.graph_query_type_value if plan else ""
        if actual_graph_query_type != case.expected_graph_query_type:
            failures.append(
                f"expected_graph_query_type={case.expected_graph_query_type} "
                f"actual_graph_query_type={actual_graph_query_type}"
            )
        if (
            graph_trace.get("query_type")
            and graph_trace.get("query_type") != case.expected_graph_query_type
        ):
            failures.append(f"graph_snapshot_query_type_mismatch={graph_trace.get('query_type')}")
    for reason in case.required_failure_reasons:
        if reason not in (route_diagnostics.get("failure_reasons") or []):
            failures.append(f"missing_failure_reason={reason}")
    if case.answer_text not in response.answer:
        failures.append("answer_text_mismatch")
    if event.strategy != case.expected_route_strategy:
        failures.append(f"trace_event_strategy_mismatch={event.strategy}")
    if event.retrieval.doc_count != response.doc_count:
        failures.append(
            f"trace_event_doc_count_mismatch={event.retrieval.doc_count}!={response.doc_count}"
        )
    if case.expected_graph_event_names:
        graph_event_names = [
            str(graph_event.get("name") or "")
            for graph_event in (graph_trace.get("events") or [])
            if isinstance(graph_event, dict)
        ]
        if graph_event_names != case.expected_graph_event_names:
            failures.append(
                f"expected_graph_event_names={case.expected_graph_event_names} actual_graph_event_names={graph_event_names}"
            )
    if plan and event.plan.get("graph_query_type") != plan.graph_query_type_value:
        failures.append("trace_event_plan_query_type_mismatch")

    contract_checks = evaluate_contracts(
        case=case,
        result=result,
        response=response,
        event=event,
        plan=plan,
    )
    for category, check in contract_checks.items():
        for reason in check["failures"]:
            failures.append(f"{category}_contract:{reason}")

    return {
        "name": case.name,
        "question": case.question,
        "passed": not failures,
        "failures": failures,
        "strategy": response.strategy,
        "generation_mode": generation_trace.get("mode", ""),
        "contract_checks": contract_checks,
        "answer_preview": response.answer[:120],
        "answer_response": response_payload,
    }


def calculate_contract_metrics(results: List[dict]) -> dict[str, float]:
    total = len(results)
    metrics = {}
    for category, metric_name in CONTRACT_METRIC_NAMES.items():
        passed_count = sum(
            1
            for item in results
            if (item.get("contract_checks") or {}).get(category, {}).get("passed")
        )
        metrics[metric_name] = _rate(passed_count, total)
    return metrics


def run_smoke(corpus_path: str | Path = DEFAULT_CORPUS_PATH) -> dict:
    results = [evaluate_case(case) for case in load_cases(corpus_path)]
    failures = [item for item in results if not item["passed"]]
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
        "metrics": calculate_contract_metrics(results),
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
