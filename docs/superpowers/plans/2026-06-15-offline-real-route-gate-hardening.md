# Offline Real-Route Gate Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the offline real-route release gate so it fails on broken plan, request, trace, graph, evidence, or offline-planner contracts.

**Architecture:** Keep the existing deterministic smoke suite and add focused contract helpers inside `scripts/smoke_answer_pipeline_real_route.py`. Expose suite-level metrics, gate them in `eval/release_gate.json`, and extend tests so synthetic reports must satisfy the new policy.

**Tech Stack:** Python dataclasses, unittest, pytest, existing RAG runtime contracts, JSON release policy.

---

## File Structure

- Modify `scripts/smoke_answer_pipeline_real_route.py`: add contract metric constants, per-case contract helpers, suite metric aggregation, and contract details in each result.
- Modify `rag_modules/runtime/graph_models.py`: preserve graph `retrieval_request` in stage details so graph trace reconstruction keeps the request contract.
- Modify `tests/test_answer_pipeline_real_route_smoke.py`: assert the default corpus emits all contract metrics at `1.0`.
- Modify `eval/release_gate.json`: add metric thresholds for the real-route suite.
- Modify `tests/test_release_gate.py`: update synthetic suite reports and add policy-regression tests for missing and failing real-route metrics.
- Modify `docs/offline_evaluation_release_gate.md`: document the stricter real-route contract metrics.

### Task 1: Real-Route Smoke Metrics Test

**Files:**
- Modify: `tests/test_answer_pipeline_real_route_smoke.py`

- [ ] **Step 1: Write the failing metrics assertion**

Replace the test body with this version:

```python
class AnswerPipelineRealRouteSmokeTests(unittest.TestCase):
    def test_real_route_answer_pipeline_smoke_corpus_passes(self) -> None:
        self.assertTrue(DEFAULT_CORPUS_PATH.exists())

        report = run_smoke(DEFAULT_CORPUS_PATH)

        self.assertEqual(report["case_count"], report["passed_count"])
        self.assertFalse(report["failures"])
        self.assertEqual(
            report["metrics"],
            {
                "plan_contract_pass_rate": 1.0,
                "request_contract_pass_rate": 1.0,
                "trace_contract_pass_rate": 1.0,
                "graph_contract_pass_rate": 1.0,
                "evidence_contract_pass_rate": 1.0,
                "offline_planner_guard_pass_rate": 1.0,
            },
        )
        for result in report["results"]:
            self.assertTrue(result["contract_checks"])
            self.assertTrue(
                all(check["passed"] for check in result["contract_checks"].values()),
                result["contract_checks"],
            )
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
python -m pytest tests/test_answer_pipeline_real_route_smoke.py -q
```

Expected: FAIL with a missing `metrics` key or missing `contract_checks` key.

### Task 2: Contract Helpers And Suite Metrics

**Files:**
- Modify: `scripts/smoke_answer_pipeline_real_route.py`
- Modify: `rag_modules/runtime/graph_models.py`

- [ ] **Step 1: Add metric constants and helpers near the dataclass**

Insert these helpers after `RealRouteAnswerPipelineCase.from_dict`:

```python
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
```

- [ ] **Step 2: Add the per-case contract evaluator**

Insert this function before `evaluate_case`:

```python
def evaluate_contracts(
    *,
    case: RealRouteAnswerPipelineCase,
    result,
    response,
    event,
    plan: QueryPlan | None,
) -> dict[str, dict]:
    checks = {
        key: {"passed": True, "failures": []}
        for key in CONTRACT_METRIC_NAMES
    }

    def fail(category: str, reason: str) -> None:
        checks[category]["passed"] = False
        checks[category]["failures"].append(reason)

    route_trace = response.route_trace
    graph_trace = response.graph_trace
    route_request = result.route_trace.retrieval_request
    graph_expected = _graph_expected(case)

    if plan is None:
        fail("plan", "missing_query_plan")
        fail("offline_planner", "missing_query_plan")
    else:
        if plan.query != case.question:
            fail("plan", "plan_query_mismatch")
        if plan.strategy != case.expected_route_strategy:
            fail("plan", f"plan_strategy_mismatch={plan.strategy}")
        if case.expected_graph_query_type and plan.graph_query_type != case.expected_graph_query_type:
            fail("plan", f"plan_graph_query_type_mismatch={plan.graph_query_type}")
        if plan.validation_errors:
            fail("plan", f"plan_validation_errors={plan.validation_errors}")
        if plan.planner_mode not in {"fast_rule", "fallback_rule"}:
            fail("offline_planner", f"planner_mode_not_offline={plan.planner_mode}")

    if route_request is None:
        fail("request", "missing_route_retrieval_request")
    else:
        if route_request.query != case.question:
            fail("request", "route_request_query_mismatch")
        if route_request.top_k != case.top_k:
            fail("request", f"route_request_top_k_mismatch={route_request.top_k}")
        if route_request.effective_candidate_k < case.top_k:
            fail("request", f"candidate_k_below_top_k={route_request.effective_candidate_k}")
        if route_request.strategy != case.expected_route_strategy:
            fail("request", f"route_request_strategy_mismatch={route_request.strategy}")
        if route_request.query_plan is None:
            fail("request", "route_request_missing_query_plan")

    trace_event = response.trace_event
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
    if plan and event_plan.get("graph_query_type") != plan.graph_query_type:
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
        if case.expected_graph_query_type and graph_trace.get("query_type") != case.expected_graph_query_type:
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
            fail("evidence", f"hybrid_case_has_graph_evidence_units={graph_evidence_units}")
        if not result.evidence_documents:
            fail("evidence", "hybrid_case_missing_evidence_documents")

    return checks
```

- [ ] **Step 3: Attach contract checks to each case result**

Inside `evaluate_case`, after the existing functional checks and before the return statement, add:

```python
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
```

Then add `"contract_checks": contract_checks,` to the returned dictionary.

- [ ] **Step 4: Aggregate metrics in `run_smoke`**

Add this function before `run_smoke`:

```python
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
```

Then update `run_smoke` to include:

```python
    return {
        "case_count": len(results),
        "passed_count": len(results) - len(failures),
        "metrics": calculate_contract_metrics(results),
        "results": results,
        "failures": failures,
    }
```

- [ ] **Step 5: Run the focused smoke test**

If the graph contract fails with `graph_trace_missing_request_query`, update
`GraphRetrievalSnapshot.to_stage_details()` to include:

```python
"retrieval_request": (
    self.retrieval_request.to_dict() if self.retrieval_request else {}
),
```

This keeps the graph trace request contract intact when
`QueryRouterTraceAdapter.graph_trace_for_question()` reconstructs the graph
snapshot from route stage details.

Run:

```powershell
python -m pytest tests/test_answer_pipeline_real_route_smoke.py -q
```

Expected: PASS.

### Task 3: Release Policy Metric Gate

**Files:**
- Modify: `eval/release_gate.json`
- Modify: `tests/test_release_gate.py`

- [ ] **Step 1: Add real-route thresholds to the policy**

Add this top-level field after `required_route_categories`:

```json
  "metric_thresholds": {
    "answer_pipeline_real_route.metrics.plan_contract_pass_rate": {"minimum": 1.0},
    "answer_pipeline_real_route.metrics.request_contract_pass_rate": {"minimum": 1.0},
    "answer_pipeline_real_route.metrics.trace_contract_pass_rate": {"minimum": 1.0},
    "answer_pipeline_real_route.metrics.graph_contract_pass_rate": {"minimum": 1.0},
    "answer_pipeline_real_route.metrics.evidence_contract_pass_rate": {"minimum": 1.0},
    "answer_pipeline_real_route.metrics.offline_planner_guard_pass_rate": {"minimum": 1.0}
  }
```

- [ ] **Step 2: Add synthetic metric helpers in `tests/test_release_gate.py`**

Add these helpers below `_suite_report`:

```python
def _real_route_metrics(value: float = 1.0) -> dict:
    return {
        "plan_contract_pass_rate": value,
        "request_contract_pass_rate": value,
        "trace_contract_pass_rate": value,
        "graph_contract_pass_rate": value,
        "evidence_contract_pass_rate": value,
        "offline_planner_guard_pass_rate": value,
    }


def _real_route_suite_report(case_count: int, metric_value: float = 1.0) -> dict:
    report = _suite_report(case_count)
    report["metrics"] = _real_route_metrics(metric_value)
    return report
```

Update every synthetic `answer_pipeline_real_route` report from `_suite_report(3)` to `_real_route_suite_report(3)`.

- [ ] **Step 3: Add a failing metric regression test**

Add this test method:

```python
    def test_gate_fails_when_real_route_contract_metric_regresses(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {
                    category: 1
                    for category in policy["required_route_categories"]
                },
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _real_route_suite_report(3, metric_value=0.5),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn(
            "metric_minimum:answer_pipeline_real_route.metrics.plan_contract_pass_rate",
            failed_names,
        )
```

- [ ] **Step 4: Add a missing metric regression test**

Add this test method:

```python
    def test_gate_fails_when_real_route_contract_metric_is_missing(self) -> None:
        policy = load_policy(DEFAULT_POLICY_PATH)
        suite_reports = {
            "route_semantics": {
                **_suite_report(24),
                "category_counts": {
                    category: 1
                    for category in policy["required_route_categories"]
                },
            },
            "answer_pipeline": _suite_report(3),
            "answer_pipeline_real_route": _suite_report(3),
            "generation_plans": _suite_report(3),
            "generation_prompts": _suite_report(6),
        }

        report = evaluate_gate(policy, suite_reports)

        self.assertFalse(report["passed"])
        failed_names = {item["name"] for item in report["failed_checks"]}
        self.assertIn(
            "metric_available:answer_pipeline_real_route.metrics.plan_contract_pass_rate",
            failed_names,
        )
```

- [ ] **Step 5: Run release-gate tests**

Run:

```powershell
python -m pytest tests/test_release_gate.py -q
```

Expected: PASS.

### Task 4: Documentation And Final Verification

**Files:**
- Modify: `docs/offline_evaluation_release_gate.md`

- [ ] **Step 1: Document the stricter contract metrics**

Add this paragraph under `## Gate Policy` after the default-policy bullet list:

```markdown
The `answer_pipeline_real_route` suite also exposes contract pass rates for
plan, request, trace, graph, evidence, and offline-planner behavior. The
release policy requires each contract metric to remain `1.0`, so a route can no
longer pass the gate by preserving only the expected strategy and answer text.
```

- [ ] **Step 2: Run focused verification**

Run:

```powershell
python -m pytest tests/test_answer_pipeline_real_route_smoke.py tests/test_release_gate.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS with `cases=39/39`, `answer_pipeline_real_route: 3/3`, and no failed checks.

- [ ] **Step 4: Stage only the related files**

Run:

```powershell
git -c safe.directory=E:/ai-project/all-in-rag add `
  docs/superpowers/specs/2026-06-15-offline-real-route-gate-hardening-design.md `
  docs/superpowers/plans/2026-06-15-offline-real-route-gate-hardening.md `
  rag_modules/runtime/graph_models.py `
  scripts/smoke_answer_pipeline_real_route.py `
  tests/test_answer_pipeline_real_route_smoke.py `
  eval/release_gate.json `
  tests/test_release_gate.py `
  docs/offline_evaluation_release_gate.md
```

Expected: files are staged. Do not commit.
