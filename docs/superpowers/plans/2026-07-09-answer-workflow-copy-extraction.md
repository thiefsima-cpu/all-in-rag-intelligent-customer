# Answer Workflow Copy Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move answer workflow product copy out of pipeline and result-factory code into the versioned query policy bundle.

**Architecture:** Add typed answer workflow copy to `query_policy`, pass the resolved policy copy through serving runtime assembly, and let app services consume it through an app-owned protocol. `AnswerPipelineService` and `QuestionAnswerResultFactory` format messages from injected copy only; they never load policy resources.

**Tech Stack:** Python 3.11, dataclasses, protocols, JSON policy resources, pytest, existing FastAPI/SSE tests.

## Global Constraints

- Use Python 3.11; `pyproject.toml` requires `>=3.11,<3.12`.
- No new production or development dependencies.
- Scope is answer-serving workflow copy only: no build-job progress, API operation messages, OpenAPI examples, generation prompts, retrieval behavior, policy routing terms, or `agent/`.
- SSE event types and response schemas must remain unchanged.
- `AnswerPipelineService` and `QuestionAnswerResultFactory` must not import `query_policy`.
- Modify behavior test-first and run the narrow tests before wider verification.

---

## File Structure

- `rag_modules/query_policy/models.py`: owns the typed `AnswerWorkflowCopyPolicy` dataclass as part of the query policy bundle.
- `rag_modules/query_policy/parsers/generation.py`: validates and parses `generation.answer_workflow_copy`.
- `rag_modules/query_policy/resources/c9-default-v1/policy.json`: holds the default English answer workflow copy.
- `rag_modules/app/services/answer_copy.py`: new app-owned protocol consumed by pipeline/result factory without importing `query_policy`.
- `rag_modules/app/services/answer_pipeline.py`: consumes injected copy for no-evidence and callback messages.
- `rag_modules/app/services/answer_result_factory.py`: consumes injected copy for fatal answer failures.
- `rag_modules/app/services/answer_workflow.py`: resolves copy once and injects it into the pipeline and result factory.
- `rag_modules/app/providers/contracts.py`: adds `policy_bundle` to `provide_answer_workflow`.
- `rag_modules/app/providers/services.py`: passes selected policy copy into `AnswerWorkflow`.
- `rag_modules/app/composition/serving_runtime_factory.py`: passes the already resolved policy bundle to `provide_answer_workflow`.
- `tests/test_query_policy.py`: covers policy parsing, default copy, and invalid copy resources.
- `tests/test_answer_workflow.py`: covers custom copy in direct workflow behavior.
- `tests/test_serving_runtime_factory.py`: covers policy bundle propagation into answer workflow assembly.
- `tests/test_api_sse.py`: keeps current SSE event shape and default message expectations.

### Task 1: Query Policy Copy Contract

**Files:**
- Modify: `tests/test_query_policy.py:20`
- Modify: `rag_modules/query_policy/models.py:160`
- Modify: `rag_modules/query_policy/parsers/generation.py:1`
- Modify: `rag_modules/query_policy/resources/c9-default-v1/policy.json:1239`

**Interfaces:**
- Produces: `AnswerWorkflowCopyPolicy` with string attributes:
  `no_evidence_answer`, `answer_failed`, `user_question_template`,
  `query_routing_started`, `answer_generation_started`,
  `streaming_interrupted_fallback`, `answer_complete_template`,
  `strategy_summary_template`, `strategy_icon_hybrid_traditional`,
  `strategy_icon_graph_rag`, `strategy_icon_combined`, `strategy_icon_default`,
  `document_summary_template`, `document_summary_total_template`,
  `unknown_recipe_name`, `unknown_search_type`.
- Produces: `GenerationPolicy.answer_workflow_copy: AnswerWorkflowCopyPolicy`.
- Consumes later: `AnswerWorkflow` receives `policy_bundle.generation.answer_workflow_copy`.

- [ ] **Step 1: Write failing query policy tests**

In `tests/test_query_policy.py`, add this helper above `_minimal_policy_payload()`:

```python
def _answer_workflow_copy_payload() -> dict[str, str]:
    return {
        "no_evidence_answer": "No evidence.",
        "answer_failed": "Answer failed.",
        "user_question_template": "Question: {question}",
        "query_routing_started": "Routing started.",
        "answer_generation_started": "Generation started.",
        "streaming_interrupted_fallback": "Stream interrupted.",
        "answer_complete_template": "Done in {latency_seconds:.2f}s",
        "strategy_summary_template": (
            "{strategy_icon} Strategy: {strategy}\n"
            "Complexity: {complexity:.2f}, "
            "Relationship intensity: {relationship_intensity:.2f}"
        ),
        "strategy_icon_hybrid_traditional": "[HYBRID]",
        "strategy_icon_graph_rag": "[GRAPH]",
        "strategy_icon_combined": "[COMBINED]",
        "strategy_icon_default": "[ROUTE]",
        "document_summary_template": (
            "Found {document_count} relevant documents: {document_summaries}"
        ),
        "document_summary_total_template": "\n    Total results: {document_count}",
        "unknown_recipe_name": "unknown",
        "unknown_search_type": "unknown",
    }
```

Inside `_minimal_policy_payload()["generation"]`, add:

```python
            "answer_workflow_copy": _answer_workflow_copy_payload(),
```

Add these tests near the existing generation policy tests:

```python
    def test_policy_bundle_exposes_answer_workflow_copy(self) -> None:
        copy = get_query_policy().generation.answer_workflow_copy

        self.assertEqual(
            copy.no_evidence_answer,
            "Sorry, I could not find enough relevant retrieval evidence to answer that question.",
        )
        self.assertEqual(copy.answer_failed, "The answer could not be generated.")
        self.assertEqual(copy.user_question_template, "\nUser question: {question}")
        self.assertEqual(copy.query_routing_started, "Running query routing...")
        self.assertEqual(copy.answer_generation_started, "Generating answer...")
        self.assertEqual(copy.strategy_icon_graph_rag, "[GRAPH]")
        self.assertEqual(copy.unknown_recipe_name, "unknown")


def test_policy_loader_rejects_missing_answer_workflow_copy_key(tmp_path: Path) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["generation"]["answer_workflow_copy"].pop("query_routing_started")
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PolicyLoadError,
        match="generation.answer_workflow_copy.query_routing_started",
    ):
        load_policy_bundle(tmp_path)


def test_policy_loader_rejects_unknown_answer_workflow_template_variable(
    tmp_path: Path,
) -> None:
    from rag_modules.query_policy.loader import PolicyLoadError, load_policy_bundle

    _write_bundle(tmp_path)
    policy_path = tmp_path / "policy.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    policy["generation"]["answer_workflow_copy"]["answer_complete_template"] = (
        "Done in {seconds}s"
    )
    policy_path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        PolicyLoadError,
        match="generation.answer_workflow_copy.answer_complete_template.seconds",
    ):
        load_policy_bundle(tmp_path)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
python -m pytest tests/test_query_policy.py::QueryPolicyTests::test_policy_bundle_exposes_answer_workflow_copy tests/test_query_policy.py::test_policy_loader_rejects_missing_answer_workflow_copy_key tests/test_query_policy.py::test_policy_loader_rejects_unknown_answer_workflow_template_variable -q
```

Expected: FAIL because `GenerationPolicy` has no `answer_workflow_copy`, and the loader does not reject incomplete or invalid answer workflow copy resources yet.

- [ ] **Step 3: Add the typed policy model**

In `rag_modules/query_policy/models.py`, add this dataclass before `GenerationAnswerTypePolicy`:

```python
@dataclass(frozen=True)
class AnswerWorkflowCopyPolicy:
    no_evidence_answer: str
    answer_failed: str
    user_question_template: str
    query_routing_started: str
    answer_generation_started: str
    streaming_interrupted_fallback: str
    answer_complete_template: str
    strategy_summary_template: str
    strategy_icon_hybrid_traditional: str
    strategy_icon_graph_rag: str
    strategy_icon_combined: str
    strategy_icon_default: str
    document_summary_template: str
    document_summary_total_template: str
    unknown_recipe_name: str
    unknown_search_type: str
```

Update `GenerationPolicy` in the same file:

```python
@dataclass(frozen=True)
class GenerationPolicy:
    answer_types: dict[str, GenerationAnswerTypePolicy]
    relation_explanation_markers: tuple[str, ...]
    rule_plan: GenerationRulePlanPolicy
    decision: GenerationDecisionPolicy
    fallback_answer: dict[str, str]
    answer_workflow_copy: AnswerWorkflowCopyPolicy
```

- [ ] **Step 4: Parse and validate answer workflow copy**

In `rag_modules/query_policy/parsers/generation.py`, add imports:

```python
from string import Formatter
```

and include these model imports:

```python
    AnswerWorkflowCopyPolicy,
    PolicyLoadError,
```

Add constants below `_FALLBACK_ANSWER_KEYS`:

```python
_ANSWER_WORKFLOW_COPY_KEYS = (
    "no_evidence_answer",
    "answer_failed",
    "user_question_template",
    "query_routing_started",
    "answer_generation_started",
    "streaming_interrupted_fallback",
    "answer_complete_template",
    "strategy_summary_template",
    "strategy_icon_hybrid_traditional",
    "strategy_icon_graph_rag",
    "strategy_icon_combined",
    "strategy_icon_default",
    "document_summary_template",
    "document_summary_total_template",
    "unknown_recipe_name",
    "unknown_search_type",
)

_ANSWER_WORKFLOW_TEMPLATE_VARIABLES = {
    "user_question_template": {"question"},
    "answer_complete_template": {"latency_seconds"},
    "strategy_summary_template": {
        "strategy_icon",
        "strategy",
        "complexity",
        "relationship_intensity",
    },
    "document_summary_template": {"document_count", "document_summaries"},
    "document_summary_total_template": {"document_count"},
}
```

In `parse_generation()`, read the new section after `fallback_answer`:

```python
    answer_workflow_copy = required_mapping(
        payload,
        "answer_workflow_copy",
        root,
        field_path="generation.answer_workflow_copy",
    )
```

and pass it to `GenerationPolicy`:

```python
        answer_workflow_copy=_to_answer_workflow_copy(answer_workflow_copy, root),
```

Add these helper functions below `_to_generation_decision()`:

```python
def _template_variables(template: str) -> set[str]:
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


def _verify_answer_workflow_templates(
    value: Mapping[str, object],
    root: Path,
) -> None:
    for key, allowed_variables in _ANSWER_WORKFLOW_TEMPLATE_VARIABLES.items():
        actual_variables = _template_variables(str(value.get(key) or ""))
        unknown_variables = sorted(actual_variables - allowed_variables)
        if unknown_variables:
            unknown = unknown_variables[0]
            raise PolicyLoadError(
                f"Unsupported answer workflow copy variable: {key}.{unknown}",
                bundle_path=str(root),
                field_path=f"generation.answer_workflow_copy.{key}.{unknown}",
            )


def _to_answer_workflow_copy(
    value: Mapping[str, object],
    root: Path,
) -> AnswerWorkflowCopyPolicy:
    require_keys(value, _ANSWER_WORKFLOW_COPY_KEYS, root, "generation.answer_workflow_copy")
    _verify_answer_workflow_templates(value, root)
    return AnswerWorkflowCopyPolicy(
        no_evidence_answer=str(value.get("no_evidence_answer") or ""),
        answer_failed=str(value.get("answer_failed") or ""),
        user_question_template=str(value.get("user_question_template") or ""),
        query_routing_started=str(value.get("query_routing_started") or ""),
        answer_generation_started=str(value.get("answer_generation_started") or ""),
        streaming_interrupted_fallback=str(value.get("streaming_interrupted_fallback") or ""),
        answer_complete_template=str(value.get("answer_complete_template") or ""),
        strategy_summary_template=str(value.get("strategy_summary_template") or ""),
        strategy_icon_hybrid_traditional=str(
            value.get("strategy_icon_hybrid_traditional") or ""
        ),
        strategy_icon_graph_rag=str(value.get("strategy_icon_graph_rag") or ""),
        strategy_icon_combined=str(value.get("strategy_icon_combined") or ""),
        strategy_icon_default=str(value.get("strategy_icon_default") or ""),
        document_summary_template=str(value.get("document_summary_template") or ""),
        document_summary_total_template=str(value.get("document_summary_total_template") or ""),
        unknown_recipe_name=str(value.get("unknown_recipe_name") or ""),
        unknown_search_type=str(value.get("unknown_search_type") or ""),
    )
```

- [ ] **Step 5: Add default policy resource copy**

In `rag_modules/query_policy/resources/c9-default-v1/policy.json`, inside the `generation` object after `fallback_answer`, add:

```json
    "answer_workflow_copy": {
      "no_evidence_answer": "Sorry, I could not find enough relevant retrieval evidence to answer that question.",
      "answer_failed": "The answer could not be generated.",
      "user_question_template": "\nUser question: {question}",
      "query_routing_started": "Running query routing...",
      "answer_generation_started": "Generating answer...",
      "streaming_interrupted_fallback": "\n[WARN] Streaming output interrupted. Falling back to standard mode...",
      "answer_complete_template": "\nAnswer complete in {latency_seconds:.2f}s",
      "strategy_summary_template": "{strategy_icon} Strategy: {strategy}\nComplexity: {complexity:.2f}, Relationship intensity: {relationship_intensity:.2f}",
      "strategy_icon_hybrid_traditional": "[HYBRID]",
      "strategy_icon_graph_rag": "[GRAPH]",
      "strategy_icon_combined": "[COMBINED]",
      "strategy_icon_default": "[ROUTE]",
      "document_summary_template": "Found {document_count} relevant documents: {document_summaries}",
      "document_summary_total_template": "\n    Total results: {document_count}",
      "unknown_recipe_name": "unknown",
      "unknown_search_type": "unknown"
    }
```

Keep JSON commas valid around the inserted object.

- [ ] **Step 6: Verify green for policy tests**

Run:

```powershell
python -m pytest tests/test_query_policy.py::QueryPolicyTests::test_policy_bundle_exposes_answer_workflow_copy tests/test_query_policy.py::test_policy_loader_rejects_missing_answer_workflow_copy_key tests/test_query_policy.py::test_policy_loader_rejects_unknown_answer_workflow_template_variable -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```powershell
git add tests/test_query_policy.py rag_modules/query_policy/models.py rag_modules/query_policy/parsers/generation.py rag_modules/query_policy/resources/c9-default-v1/policy.json
git commit -m "feat: add answer workflow copy policy"
```

### Task 2: Inject Copy Into Answer Workflow Runtime

**Files:**
- Create: `rag_modules/app/services/answer_copy.py`
- Modify: `tests/test_answer_workflow.py:13`
- Modify: `rag_modules/app/services/answer_pipeline.py:29`
- Modify: `rag_modules/app/services/answer_result_factory.py:1`
- Modify: `rag_modules/app/services/answer_workflow.py:1`

**Interfaces:**
- Consumes: `AnswerWorkflowCopy` protocol from `rag_modules.app.services.answer_copy`.
- Produces: `AnswerWorkflow(..., answer_workflow_copy: AnswerWorkflowCopy | None = None)`.
- Produces: `AnswerPipelineService(..., answer_workflow_copy: AnswerWorkflowCopy)`.
- Produces: `QuestionAnswerResultFactory(answer_workflow_copy: AnswerWorkflowCopy)`.

- [ ] **Step 1: Write failing answer workflow tests**

In `tests/test_answer_workflow.py`, replace the `NO_EVIDENCE_ANSWER` import with:

```python
from rag_modules.query_policy.models import AnswerWorkflowCopyPolicy
```

Add this helper near the fake service helpers:

```python
def _answer_copy(**overrides: str) -> AnswerWorkflowCopyPolicy:
    values = {
        "no_evidence_answer": "custom no evidence",
        "answer_failed": "custom answer failed",
        "user_question_template": "custom question: {question}",
        "query_routing_started": "custom routing started",
        "answer_generation_started": "custom generation started",
        "streaming_interrupted_fallback": "custom stream fallback",
        "answer_complete_template": "custom done {latency_seconds:.2f}",
        "strategy_summary_template": (
            "{strategy_icon} custom strategy {strategy} "
            "{complexity:.2f} {relationship_intensity:.2f}"
        ),
        "strategy_icon_hybrid_traditional": "[custom-hybrid]",
        "strategy_icon_graph_rag": "[custom-graph]",
        "strategy_icon_combined": "[custom-combined]",
        "strategy_icon_default": "[custom-route]",
        "document_summary_template": "custom docs {document_count}: {document_summaries}",
        "document_summary_total_template": " custom total {document_count}",
        "unknown_recipe_name": "custom-unknown-recipe",
        "unknown_search_type": "custom-unknown-search",
    }
    values.update(overrides)
    return AnswerWorkflowCopyPolicy(**values)
```

In `test_no_evidence_returns_fallback_and_records_trace`, pass custom copy and update assertions:

```python
        service = AnswerWorkflow(
            self.config,
            router,
            generation,
            tracer,
            answer_workflow_copy=_answer_copy(
                no_evidence_answer="CUSTOM_NO_EVIDENCE",
                query_routing_started="CUSTOM_ROUTING",
            ),
        )

        result = service.answer_question(
            question,
            explain_routing=True,
            message_callback=messages.append,
        )

        self.assertEqual(result.answer, "CUSTOM_NO_EVIDENCE")
        self.assertIn("CUSTOM_ROUTING", messages)
        self.assertNotIn("Running query routing...", messages)
```

In `test_streaming_failure_falls_back_to_standard_generation`, pass custom copy and update the warning assertion:

```python
        service = AnswerWorkflow(
            self.config,
            router,
            generation,
            tracer,
            answer_workflow_copy=_answer_copy(
                streaming_interrupted_fallback="CUSTOM_STREAM_FALLBACK",
            ),
        )

        result = service.answer_question(
            question,
            stream=True,
            message_callback=messages.append,
        )

        self.assertEqual(result.answer, "fallback answer")
        self.assertEqual(generation.stream_calls, 1)
        self.assertEqual(generation.direct_calls, 1)
        self.assertIn("CUSTOM_STREAM_FALLBACK", messages)
        self.assertFalse(any("Falling back to standard mode" in message for message in messages))
```

In `test_result_factory_from_error_does_not_place_raw_exception_in_answer`, construct the factory with custom copy:

```python
        result = QuestionAnswerResultFactory(
            answer_workflow_copy=_answer_copy(answer_failed="CUSTOM_FAILED"),
        ).from_error(
            AnswerPipelineState(question="safe question"),
            latency_ms=12.5,
            trace_bundle=AnswerTraceBundle(),
            error=RuntimeError(secret),
        )

        self.assertEqual(result.answer, "CUSTOM_FAILED")
        self.assertNotIn(secret, result.answer)
```

- [ ] **Step 2: Run tests and verify red**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py::AnswerWorkflowTests::test_no_evidence_returns_fallback_and_records_trace tests/test_answer_workflow.py::AnswerWorkflowTests::test_streaming_failure_falls_back_to_standard_generation tests/test_answer_workflow.py::AnswerWorkflowTests::test_result_factory_from_error_does_not_place_raw_exception_in_answer -q
```

Expected: FAIL with unexpected keyword or constructor argument errors because answer workflow copy injection does not exist yet.

- [ ] **Step 3: Add the app-owned copy protocol**

Create `rag_modules/app/services/answer_copy.py`:

```python
"""Answer workflow product-copy contract owned by application services."""

from __future__ import annotations

from typing import Protocol


class AnswerWorkflowCopy(Protocol):
    no_evidence_answer: str
    answer_failed: str
    user_question_template: str
    query_routing_started: str
    answer_generation_started: str
    streaming_interrupted_fallback: str
    answer_complete_template: str
    strategy_summary_template: str
    strategy_icon_hybrid_traditional: str
    strategy_icon_graph_rag: str
    strategy_icon_combined: str
    strategy_icon_default: str
    document_summary_template: str
    document_summary_total_template: str
    unknown_recipe_name: str
    unknown_search_type: str


__all__ = ["AnswerWorkflowCopy"]
```

- [ ] **Step 4: Update `AnswerPipelineService` to use injected copy**

In `rag_modules/app/services/answer_pipeline.py`, remove `NO_EVIDENCE_ANSWER` and import:

```python
from .answer_copy import AnswerWorkflowCopy
```

Update the constructor:

```python
        answer_workflow_copy: AnswerWorkflowCopy,
        telemetry: RuntimeTelemetry | None = None,
    ) -> None:
        self.query_router = query_router
        self.generation_service = generation_service
        self.answer_workflow_copy = answer_workflow_copy
```

Replace the first emitted user-question message:

```python
        self._emit(
            state.message_callback,
            self.answer_workflow_copy.user_question_template.format(question=state.question),
        )
```

Replace routing and generation messages:

```python
        self._emit(state.message_callback, self.answer_workflow_copy.query_routing_started)
```

```python
        self._emit(state.message_callback, self.answer_workflow_copy.answer_generation_started)
```

Replace no-evidence answer:

```python
            state.answer = self.answer_workflow_copy.no_evidence_answer
```

Replace stream fallback warning:

```python
            self._emit(message_callback, self.answer_workflow_copy.streaming_interrupted_fallback)
```

Update `emit_completion()`:

```python
    def emit_completion(self, callback: MessageCallback, latency_ms: float) -> None:
        self._emit(
            callback,
            self.answer_workflow_copy.answer_complete_template.format(
                latency_seconds=latency_ms / 1000,
            ),
        )
```

Convert `_format_strategy_summary()` from staticmethod to instance method:

```python
    def _format_strategy_summary(self, analysis: QueryAnalysis) -> str:
        strategy_icons = {
            "hybrid_traditional": self.answer_workflow_copy.strategy_icon_hybrid_traditional,
            "graph_rag": self.answer_workflow_copy.strategy_icon_graph_rag,
            "combined": self.answer_workflow_copy.strategy_icon_combined,
        }
        strategy_icon = strategy_icons.get(
            analysis.recommended_strategy.value,
            self.answer_workflow_copy.strategy_icon_default,
        )
        return self.answer_workflow_copy.strategy_summary_template.format(
            strategy_icon=strategy_icon,
            strategy=analysis.recommended_strategy.value,
            complexity=analysis.query_complexity,
            relationship_intensity=analysis.relationship_intensity,
        )
```

Convert `_format_document_summary()` from staticmethod to instance method:

```python
    def _format_document_summary(self, documents: List[EvidenceDocument]) -> str:
        doc_info = []
        for doc in documents:
            metadata = doc.metadata or {}
            recipe_name = (
                doc.recipe_name
                or metadata.get("recipe_name")
                or self.answer_workflow_copy.unknown_recipe_name
            )
            search_type = (
                doc.search_type
                or metadata.get("route_strategy")
                or self.answer_workflow_copy.unknown_search_type
            )
            score = metadata.get("final_score", metadata.get("relevance_score", doc.score))
            try:
                score_text = f"{float(score):.3f}"
            except (TypeError, ValueError):
                score_text = str(score)
            doc_info.append(f"{recipe_name}({search_type}, {score_text})")
        summary = self.answer_workflow_copy.document_summary_template.format(
            document_count=len(documents),
            document_summaries=", ".join(doc_info[:3]),
        )
        if len(doc_info) > 3:
            summary += self.answer_workflow_copy.document_summary_total_template.format(
                document_count=len(documents),
            )
        return summary
```

Update `__all__`:

```python
__all__ = ["AnswerPipelineService"]
```

- [ ] **Step 5: Update `QuestionAnswerResultFactory`**

In `rag_modules/app/services/answer_result_factory.py`, import the protocol and add a constructor:

```python
from .answer_copy import AnswerWorkflowCopy
from .answer_models import AnswerPipelineState, AnswerTraceBundle, QuestionAnswerResult


class QuestionAnswerResultFactory:
    """Create stable question-answer responses from pipeline state."""

    def __init__(self, *, answer_workflow_copy: AnswerWorkflowCopy) -> None:
        self.answer_workflow_copy = answer_workflow_copy
```

Use copy in `from_error()`:

```python
            answer=self.answer_workflow_copy.answer_failed,
```

- [ ] **Step 6: Update `AnswerWorkflow` to resolve and inject copy**

In `rag_modules/app/services/answer_workflow.py`, add imports:

```python
from ...query_policy import get_query_policy
from .answer_copy import AnswerWorkflowCopy
```

Add this keyword parameter to `AnswerWorkflow.__init__()`:

```python
        answer_workflow_copy: AnswerWorkflowCopy | None = None,
```

Resolve copy before constructing pipeline/result factory:

```python
        resolved_copy = answer_workflow_copy or get_query_policy().generation.answer_workflow_copy
```

Pass it into `AnswerPipelineService`:

```python
            answer_workflow_copy=resolved_copy,
            telemetry=self.telemetry,
```

Pass it into `QuestionAnswerResultFactory`:

```python
        self.result_factory = result_factory or QuestionAnswerResultFactory(
            answer_workflow_copy=resolved_copy,
        )
```

Store it for inspection and future extension:

```python
        self.answer_workflow_copy = resolved_copy
```

- [ ] **Step 7: Verify green for answer workflow tests**

Run:

```powershell
python -m pytest tests/test_answer_workflow.py::AnswerWorkflowTests::test_no_evidence_returns_fallback_and_records_trace tests/test_answer_workflow.py::AnswerWorkflowTests::test_streaming_failure_falls_back_to_standard_generation tests/test_answer_workflow.py::AnswerWorkflowTests::test_result_factory_from_error_does_not_place_raw_exception_in_answer -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 2**

```powershell
git add tests/test_answer_workflow.py rag_modules/app/services/answer_copy.py rag_modules/app/services/answer_pipeline.py rag_modules/app/services/answer_result_factory.py rag_modules/app/services/answer_workflow.py
git commit -m "feat: inject answer workflow copy"
```

### Task 3: Pass Policy Bundle Through Serving Assembly

**Files:**
- Modify: `tests/test_serving_runtime_factory.py:378`
- Modify: `rag_modules/app/providers/contracts.py:209`
- Modify: `rag_modules/app/providers/services.py:1`
- Modify: `rag_modules/app/composition/serving_runtime_factory.py:189`

**Interfaces:**
- Consumes: `QueryPolicyBundle` resolved by `ServingRuntimeFactory._resolve_shared_modules()`.
- Produces: `ApplicationServiceProvider.provide_answer_workflow(..., policy_bundle: QueryPolicyBundle | None = None)`.

- [ ] **Step 1: Write failing serving assembly test**

In `tests/test_serving_runtime_factory.py::ServingRuntimeFactoryAssemblyTests.test_build_uses_query_understanding_capability_provider`, replace the `services` setup with:

```python
        service_kwargs = {}

        def provide_answer_workflow(**kwargs):
            service_kwargs.update(kwargs)
            return answer_workflow

        services = SimpleNamespace(
            provide_answer_workflow=provide_answer_workflow,
        )
```

In `_RootProvider.__init__()`, add:

```python
                self.policy_bundle = None
```

In `_RootProvider.provide_generation_module()`, capture the bundle:

```python
                self.policy_bundle = policy_bundle
```

After existing runtime assertions, add:

```python
        self.assertIn("policy_bundle", service_kwargs)
        self.assertIs(service_kwargs["policy_bundle"], provider.policy_bundle)
```

- [ ] **Step 2: Run test and verify red**

Run:

```powershell
python -m pytest tests/test_serving_runtime_factory.py::ServingRuntimeFactoryAssemblyTests::test_build_uses_query_understanding_capability_provider -q
```

Expected: FAIL because `policy_bundle` is not passed into `provide_answer_workflow`.

- [ ] **Step 3: Update provider protocol and implementation**

In `rag_modules/app/providers/contracts.py`, update the `ApplicationServiceProvider.provide_answer_workflow()` signature:

```python
    def provide_answer_workflow(
        self,
        *,
        config: GraphRAGConfig,
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowPort,
        query_tracer: QueryTracerPort,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> AnswerWorkflowPort: ...
```

In `rag_modules/app/providers/services.py`, import:

```python
from ...query_policy.models import QueryPolicyBundle
```

Update `_DefaultApplicationServiceProvider.provide_answer_workflow()`:

```python
    def provide_answer_workflow(
        self,
        *,
        config: GraphRAGConfig,
        query_router: RoutingWorkflowProtocol,
        generation_module: GenerationWorkflowPort,
        query_tracer: QueryTracerPort,
        policy_bundle: QueryPolicyBundle | None = None,
    ) -> AnswerWorkflowPort:
        answer_workflow_copy = (
            policy_bundle.generation.answer_workflow_copy if policy_bundle is not None else None
        )
        return AnswerWorkflow(
            config=config,
            query_router=query_router,
            generation_module=generation_module,
            query_tracer=query_tracer,
            answer_workflow_copy=answer_workflow_copy,
        )
```

- [ ] **Step 4: Pass policy bundle from serving runtime factory**

In `rag_modules/app/composition/serving_runtime_factory.py`, update the `provide_answer_workflow()` call:

```python
        answer_workflow = self.services.provide_answer_workflow(
            config=config,
            query_router=query_router,
            generation_module=generation_service,
            query_tracer=shared.tracer,
            policy_bundle=shared.policy_bundle,
        )
```

- [ ] **Step 5: Verify green for serving assembly**

Run:

```powershell
python -m pytest tests/test_serving_runtime_factory.py::ServingRuntimeFactoryAssemblyTests::test_build_uses_query_understanding_capability_provider -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```powershell
git add tests/test_serving_runtime_factory.py rag_modules/app/providers/contracts.py rag_modules/app/providers/services.py rag_modules/app/composition/serving_runtime_factory.py
git commit -m "feat: pass answer copy policy through serving assembly"
```

### Task 4: Default SSE Behavior And Final Verification

**Files:**
- Modify if needed: `tests/test_api_sse.py:106`
- Verify: `tests/test_answer_workflow.py`
- Verify: `tests/test_query_policy.py`
- Verify: `tests/test_serving_runtime_factory.py`

**Interfaces:**
- Consumes: default `c9-default-v1` answer workflow copy.
- Produces: unchanged SSE event types and response payload shape.

- [ ] **Step 1: Run SSE tests before edits**

Run:

```powershell
python -m pytest tests/test_api_sse.py::ApiSseTests::test_answer_stream_uses_sse_surface tests/test_api_sse.py::ApiSseTests::test_stream_answer_service_emits_typed_events -q
```

Expected: PASS. These tests should continue to expect `"Running query routing..."` because the default policy resource preserves current copy.

- [ ] **Step 2: If the SSE tests fail only because fake helpers need updated signatures, update helpers**

If a fake service in `tests/api_app_helpers.py` or `tests/test_api_sse.py` rejects the new keyword, update only that fake signature to accept the existing call shape. For example:

```python
def provide_answer_workflow(
    self,
    *,
    config,
    query_router,
    generation_module,
    query_tracer,
    policy_bundle=None,
):
    del config, query_router, generation_module, query_tracer, policy_bundle
    return self.answer_workflow
```

Run the same SSE command again and expect PASS.

- [ ] **Step 3: Run the focused slice**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_answer_workflow.py tests/test_serving_runtime_factory.py tests/test_api_sse.py -q
```

Expected: PASS.

- [ ] **Step 4: Run static checks for touched Python files**

Run:

```powershell
python -m ruff check rag_modules/query_policy/models.py rag_modules/query_policy/parsers/generation.py rag_modules/app/services/answer_copy.py rag_modules/app/services/answer_pipeline.py rag_modules/app/services/answer_result_factory.py rag_modules/app/services/answer_workflow.py rag_modules/app/providers/contracts.py rag_modules/app/providers/services.py rag_modules/app/composition/serving_runtime_factory.py tests/test_query_policy.py tests/test_answer_workflow.py tests/test_serving_runtime_factory.py tests/test_api_sse.py
```

Expected: PASS.

Run:

```powershell
python -m ruff format --check rag_modules/query_policy/models.py rag_modules/query_policy/parsers/generation.py rag_modules/app/services/answer_copy.py rag_modules/app/services/answer_pipeline.py rag_modules/app/services/answer_result_factory.py rag_modules/app/services/answer_workflow.py rag_modules/app/providers/contracts.py rag_modules/app/providers/services.py rag_modules/app/composition/serving_runtime_factory.py tests/test_query_policy.py tests/test_answer_workflow.py tests/test_serving_runtime_factory.py tests/test_api_sse.py
```

Expected: PASS.

- [ ] **Step 5: Inspect hard-coded answer workflow copy**

Run:

```powershell
rg -n "Sorry, I could not find enough relevant retrieval evidence|The answer could not be generated|Running query routing|Generating answer|Streaming output interrupted|Answer complete in|User question:" rag_modules/app/services rag_modules/query_policy/resources/c9-default-v1/policy.json
```

Expected: matches in `rag_modules/query_policy/resources/c9-default-v1/policy.json` only for product copy. Matches in tests are acceptable when they assert default behavior.

- [ ] **Step 6: Commit Task 4**

```powershell
git add tests/test_api_sse.py tests/api_app_helpers.py
git commit -m "test: verify answer workflow copy extraction"
```

If Task 4 did not require file edits, skip the commit and record the successful verification commands in the final response.

## Final Review Checklist

- [ ] `AnswerPipelineService` contains no hard-coded answer workflow product copy.
- [ ] `QuestionAnswerResultFactory` contains no hard-coded fatal answer copy.
- [ ] `AnswerPipelineService` and `QuestionAnswerResultFactory` import `AnswerWorkflowCopy`, not `query_policy`.
- [ ] `ServingRuntimeFactory` passes `shared.policy_bundle` into `provide_answer_workflow`.
- [ ] Default SSE messages remain unchanged.
- [ ] Focused tests and Ruff checks pass.
