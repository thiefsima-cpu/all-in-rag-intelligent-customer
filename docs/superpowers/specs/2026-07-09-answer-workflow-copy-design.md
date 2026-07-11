# Answer Workflow Copy Extraction Design

## Goal

Move answer workflow product copy out of pipeline and result-factory code so customers can
customize no-evidence answers, answer progress messages, stream fallback warnings, and fatal answer
failure text through the existing versioned policy bundle.

## Scope

This change covers the answer-serving workflow only:

- no-evidence fallback answer;
- answer progress messages emitted through `message_callback`;
- streaming interruption fallback warning;
- final completion progress message;
- fatal answer error text returned by `QuestionAnswerResultFactory.from_error`.

It does not cover build-job progress, API operation messages, OpenAPI examples, generation prompts,
retrieval behavior, policy routing terms, or the standalone `agent/` package.

## Architecture

The existing query policy bundle is the customization surface. Add a typed
`AnswerWorkflowCopyPolicy` to `rag_modules/query_policy/models.py` and parse it from a new
`generation.answer_workflow_copy` object in each policy `policy.json`.

Serving runtime assembly already resolves the selected policy bundle before workflow services are
built. Extend the existing `ApplicationServiceProvider.provide_answer_workflow` contract with the
same optional `policy_bundle` keyword used by generation and retrieval providers. The answer
workflow receives the already parsed copy policy and injects it into:

- `AnswerPipelineService`, which formats no-evidence and progress messages;
- `QuestionAnswerResultFactory`, which formats fatal answer failure text.

`AnswerPipelineService` and `QuestionAnswerResultFactory` must not import `query_policy` or load
resources themselves. They consume a typed copy object passed by `AnswerWorkflow`, preserving the
current import direction and testability.

## Copy Contract

The default policy bundle adds:

```json
{
  "generation": {
    "answer_workflow_copy": {
      "no_evidence_answer": "Sorry, I could not find enough relevant retrieval evidence to answer that question.",
      "answer_failed": "The answer could not be generated.",
      "query_routing_started": "Running query routing...",
      "answer_generation_started": "Generating answer...",
      "streaming_interrupted_fallback": "\n[WARN] Streaming output interrupted. Falling back to standard mode...",
      "answer_complete_template": "\nAnswer complete in {latency_seconds:.2f}s",
      "strategy_summary_template": "{strategy_icon} Strategy: {strategy}\nComplexity: {complexity:.2f}, Relationship intensity: {relationship_intensity:.2f}",
      "document_summary_template": "Found {document_count} relevant documents: {document_summaries}",
      "document_summary_total_template": "\n    Total results: {document_count}",
      "unknown_recipe_name": "unknown",
      "unknown_search_type": "unknown"
    }
  }
}
```

The parser requires every key above. Templates are Python `str.format` templates with fixed
variables:

- `answer_complete_template`: `latency_seconds`;
- `strategy_summary_template`: `strategy_icon`, `strategy`, `complexity`,
  `relationship_intensity`;
- `document_summary_template`: `document_count`, `document_summaries`;
- `document_summary_total_template`: `document_count`.

Missing keys or invalid template variables fail policy loading through `PolicyLoadError`, the same
failure family used for other generation policy defects.

## Data Flow

1. Configuration/profile loading selects and parses the policy bundle.
2. `ServingRuntimeFactory` resolves shared modules, including the selected `QueryPolicyBundle`.
3. `ServingRuntimeFactory._resolve_workflow_modules()` passes that bundle to
   `services.provide_answer_workflow(..., policy_bundle=shared.policy_bundle)`.
4. The default application service provider passes
   `policy_bundle.generation.answer_workflow_copy` into `AnswerWorkflow`.
5. `AnswerPipelineService` uses that object for runtime message emission and no-evidence answer
   text.
6. `QuestionAnswerResultFactory` uses the same object for fatal answer failure text.
7. SSE event types and response schemas remain unchanged; only the message strings become
   resource-backed.

## Error Handling

Policy loading rejects incomplete `answer_workflow_copy` resources before serving runtime assembly.
Runtime formatting failures are prevented by parser validation. The fallback behavior itself remains
unchanged: no evidence still returns an empty-mode failed generation snapshot, and stream generation
failure still logs a safe error before falling back to standard generation.

## Testing

Focused tests should be added or updated for:

- `tests/test_query_policy.py`: the default bundle exposes `answer_workflow_copy` and custom test
  bundles must include it;
- `tests/test_query_policy.py`: missing copy keys are rejected with a field path under
  `generation.answer_workflow_copy`;
- `tests/test_answer_workflow.py`: custom copy injected through `AnswerWorkflow` controls
  no-evidence answer and routing progress text;
- `tests/test_answer_workflow.py`: custom copy controls stream fallback warning;
- `tests/test_answer_workflow.py`: custom copy controls fatal answer failure text;
- `tests/test_serving_runtime_factory.py`: serving runtime assembly passes the resolved
  `policy_bundle` to `provide_answer_workflow`;
- `tests/test_api_sse.py`: existing SSE tests keep the same event shape and default message text.

Run the narrow slice first:

```powershell
python -m pytest tests/test_query_policy.py tests/test_answer_workflow.py tests/test_api_sse.py -q
```

Then run formatting/lint equivalent for touched files, or `pre-commit run --all-files` if the
change is ready for a broader gate.

## Documentation Impact

No public API schema changes are expected. If the implementation lands, update `README.md` or
`docs/` only if customer policy-bundle customization instructions already cover similar resource
overrides nearby; otherwise the code and tests are sufficient for this narrow internal
customization path.

## Acceptance Criteria

- No user-visible answer workflow copy remains hard-coded in `AnswerPipelineService` or
  `QuestionAnswerResultFactory`.
- Answer workflow copy is parsed from the selected policy bundle and can be overridden by tests with
  a custom bundle.
- Answer pipeline and result factory consume typed copy data without importing `query_policy`.
- SSE and answer response payload shapes are unchanged.
- Focused query policy, answer workflow, and SSE tests pass.
