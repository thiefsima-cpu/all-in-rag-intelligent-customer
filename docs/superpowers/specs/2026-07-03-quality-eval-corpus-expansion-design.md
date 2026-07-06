# Quality Eval Corpus Expansion Design

## Context

The default release gate requires the deterministic offline `quality_eval` suite, but its curated
corpus contains only nine cases. The current case schema is a flat collection of positive-match
expectations. It cannot express a correct no-evidence response, a clarification request, or a
constraint-conflict response. The offline evaluator also synthesizes supporting evidence for every
case, so adding a query labelled "no evidence" would not exercise abstention behavior.

This change expands the corpus to 18 cases and replaces the existing expectation model instead of
adding compatibility fields or special-case branches.

## Goals

- Replace the flat evaluation case schema with one strict, typed schema.
- Represent grounded answers, no-evidence responses, clarification requests, and constraint
  conflicts as mutually exclusive response modes.
- Give no-evidence and safe-abstention cases meaningful offline behavior.
- Cover no-evidence, ambiguity, multi-hop, constraint-conflict, long-query, and colloquial Chinese
  dimensions with at least two cases each.
- Use one scorer for runtime evaluation and deterministic offline release-gate evaluation.
- Raise release-gate case, dimension, and outcome-accuracy requirements with the corpus expansion.

## Non-goals

- Preserve or dual-read the old flat corpus schema.
- Add model-backed judging or external-service dependencies to the offline release gate.
- Change production routing, retrieval, or generation behavior.
- Store complete serialized `AnswerResponse` goldens in the corpus.
- Lower existing quality, reliability, latency, or cost thresholds.

## Corpus Contract

Each case uses this structure:

```json
{
  "id": "constraint-conflict-01",
  "query": "不要花生但必须保留花生，给我做一道宫保鸡丁。",
  "category": "constrained_recommendation",
  "dimensions": ["constraint_conflict", "colloquial_zh"],
  "expectation": {
    "response_mode": "constraint_conflict",
    "strategy": "hybrid_traditional",
    "recipe_names": [],
    "answer_terms": ["冲突", "放宽"],
    "recipe_relevance": {}
  },
  "offline_fixture": {
    "strategy": "hybrid_traditional",
    "answer": "这些条件互相冲突，请放宽其中一个条件。",
    "evidence": []
  }
}
```

The Python representation uses dataclasses and a string enum. `response_mode` accepts exactly:

- `grounded_answer`
- `no_evidence`
- `clarification`
- `constraint_conflict`

The loader rejects malformed corpus data before evaluation. Required validation includes:

- non-empty and unique case IDs;
- non-empty queries, categories, and dimensions;
- known response modes;
- required nested `expectation` and `offline_fixture` objects;
- finite, non-negative relevance grades;
- no recipe expectations or evidence fixtures for abstention modes;
- at least one fixture evidence document for grounded cases, with every explicitly expected recipe
  represented in that evidence;
- fixture strategy matching an explicit expected strategy;
- no legacy `expected_*` fields.

There is no old-schema fallback and no migration layer. All 18 cases are converted in the same
change.

## Corpus Composition

The existing nine cases remain semantically represented but are migrated to the new schema. Nine
new cases are added:

- two no-evidence cases;
- two ambiguity cases that require clarification;
- one additional multi-hop relation case;
- two mutually conflicting constraint cases;
- one additional long-query case;
- one additional colloquial-Chinese case.

Dimensions may overlap. Existing complex-relation and sufficiently detailed queries receive
`multi_hop` or `long_query` dimensions where appropriate. New ambiguity and recommendation cases
also carry `colloquial_zh` where the wording is conversational. The final corpus contains exactly
18 cases and at least two cases for each required dimension:

- `no_evidence`
- `ambiguity`
- `multi_hop`
- `constraint_conflict`
- `long_query`
- `colloquial_zh`

## Evaluation Architecture

Runtime and offline evaluation normalize their inputs into one internal `EvalObservation` value.
It contains the selected strategy, answer text, evidence documents, ranked recipe names, fallback
and degradation signals, latency, cost, and the existing response contracts.

The two producers are intentionally separate from scoring:

1. Runtime evaluation creates an observation from `AnswerResponse` or route-only output.
2. Offline evaluation creates an observation from the case's `offline_fixture` without initializing
   the application, model, Milvus, or Neo4j.
3. A shared scorer compares the observation with the typed expectation and emits the existing
   result structure plus response-mode fields.

Keeping `offline_fixture` separate from `expectation` prevents the evaluator from generating an
answer or evidence directly from values it is supposed to verify. The fixture remains compact: it
contains only strategy, answer, and evidence inputs rather than a full serialized API response.

## Response-mode Scoring

`grounded_answer` requires evidence, all required recipe names and answer terms, the expected
strategy when specified, and the existing grounding and citation checks. Retrieval metrics and
grounding metrics apply only to these cases.

`no_evidence` requires zero evidence, no returned recipe names, an answer that includes the curated
insufficiency terms, no citation claims, and no fallback or degradation.

`clarification` requires zero evidence, no returned recipe names, an answer containing the curated
clarification terms, and no unsupported commitment to a recipe or citation.

`constraint_conflict` requires zero evidence, no returned recipe names, an answer that identifies
the conflict and asks the user to relax a condition, and no unsupported recipe or citation.

An expected abstention is a successful primary outcome, not a fallback. This preserves the existing
`fallback_rate == 0.0` policy while distinguishing safe refusal from generation failure.

## Metrics and Release Policy

The evaluator retains all existing metrics. Recall, MRR, nDCG, faithfulness, and citation accuracy
aggregate only cases for which those metrics are applicable. Two metrics are added:

- `response_mode_accuracy`: cases whose observed behavior satisfies their expected response mode
  divided by all cases;
- `abstention_accuracy`: successful `no_evidence`, `clarification`, and `constraint_conflict` cases
  divided by all abstention cases.

The report also exposes deterministic counts by `response_mode` and by dimension. The release policy
changes are:

- `suite_minimum_cases.quality_eval`: 18;
- `minimum_total_cases`: 57;
- each of the six required quality dimensions: at least 2;
- `quality_eval.metrics.response_mode_accuracy`: minimum 1.0;
- `quality_eval.metrics.abstention_accuracy`: minimum 1.0.

Existing pass-rate, retrieval, grounding, fallback, degradation, latency, and cost thresholds remain
unchanged. The gate evaluates required quality dimensions from the `quality_eval` report rather than
trusting corpus size as a proxy for scenario diversity.

## Error Handling

Corpus contract errors fail immediately with the corpus path, case index or ID, and field-specific
reason. Unsupported response modes and legacy fields are configuration errors, not skipped cases.
An empty applicable metric set remains `None`; the default 18-case corpus always includes grounded
and abstention cases, so every gated metric is numeric.

Individual observation mismatches remain structured case failures. They do not abort the suite, so
the report shows every regression in one run. Dependency failures retain the release gate's existing
failure-type behavior.

## Testing Strategy

Implementation follows test-driven development:

1. Add failing loader tests for the new schema, duplicate IDs, legacy fields, and contradictory
   response-mode data.
2. Add failing shared-scorer tests for the four response modes and metric applicability.
3. Add failing corpus contract tests for exactly 18 cases and the six minimum dimension counts.
4. Add failing release-policy tests for the new suite size, total size, dimensions, and metrics.
5. Implement the typed contract, shared observation/scorer path, corpus migration, and gate policy
   changes in the smallest increments that make those tests pass.
6. Update the offline release-gate documentation and examples to use the new schema and thresholds.

Verification runs, in order:

- focused evaluation tests;
- focused release-gate tests;
- the complete pytest suite;
- repository pre-commit hooks;
- `python scripts/release_gate.py`.

## Files and Boundaries

- `scripts/eval_queries.py`: typed corpus contract, observation normalization, shared scoring, and
  evaluation metrics.
- `tests/fixtures/curated_eval_corpus.json`: all 18 strict-schema cases and compact offline fixtures.
- `tests/test_eval_queries.py`: loader, scorer, corpus, and metric behavior tests.
- `eval/release_gate.json`: raised case thresholds, required dimensions, and new metric gates.
- `scripts/release_gate.py`: generic validation and checks for quality dimension coverage.
- `tests/test_release_gate.py`: policy and report enforcement tests.
- `docs/offline_evaluation_release_gate.md`: new corpus contract, coverage, and metric documentation.

No production package boundary changes are needed because this work remains in the evaluation and
release-policy tooling.

## Acceptance Criteria

- The corpus contains exactly 18 valid cases in only the new schema.
- Each required quality dimension has at least two cases.
- Offline no-evidence, clarification, and constraint-conflict cases contain no synthetic evidence.
- Runtime and offline paths use the same response-mode scorer.
- The quality report exposes numeric response-mode and abstention accuracy, both equal to 1.0 for
  the curated corpus.
- The default policy requires 18 quality cases, 57 total cases, all six dimensions, and both new
  accuracy thresholds.
- Focused tests, full pytest, pre-commit, and the offline release gate pass.
