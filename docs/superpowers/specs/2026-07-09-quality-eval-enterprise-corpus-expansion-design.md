# Quality Eval Enterprise Corpus Expansion Design

## Context

The offline release gate now requires the deterministic `quality_eval` suite with
18 curated cases. That was a useful baseline: it proved strict corpus loading,
response-mode scoring, abstention handling, dimension coverage, and release-gate
policy enforcement. It is still thin for enterprise-like traffic. Real customer
queries include long-tail phrasing, adversarial instructions, permission and
privacy boundaries, degraded dependency expectations, and evidence that is
partial, stale, or low confidence.

This change expands the curated quality corpus from 18 to 30 cases and raises
the release gate thresholds so the extra coverage becomes a required regression
signal.

## Goals

- Expand `tests/fixtures/curated_eval_corpus.json` from 18 to 30 valid cases.
- Add explicit quality dimensions for:
  - `long_tail`
  - `adversarial`
  - `permission_privacy`
  - `dependency_anomaly`
  - `low_quality_evidence`
- Require at least two cases for each new dimension in the default release gate.
- Preserve the existing strict nested schema and four response modes:
  `grounded_answer`, `no_evidence`, `clarification`, and `constraint_conflict`.
- Keep the offline gate deterministic and independent of model providers,
  Milvus, Neo4j, or any live dependency.
- Update focused tests and documentation so corpus size, response-mode mix,
  dimension counts, and release policy stay reviewable.

## Non-goals

- Do not change production routing, retrieval, graph, generation, API behavior,
  or application assembly.
- Do not add a new response mode or model-backed judge.
- Do not add real external dependency calls to the offline gate.
- Do not lower existing pass-rate, grounding, citation, fallback, degradation,
  latency, or cost thresholds.
- Do not introduce a compatibility reader for legacy corpus schemas.

## Corpus Composition

The corpus will contain 30 cases. The existing 18 cases remain semantically
unchanged. Add 12 enterprise-oriented cases:

| Group | Count | Expected behavior |
| --- | ---: | --- |
| Long-tail enterprise phrasing | 2 | Grounded answers or clarification when the query is specific but unusually worded |
| Adversarial instruction | 2 | Refuse unsupported or policy-breaking instruction pressure through `no_evidence` or `clarification` |
| Permission and privacy boundary | 2 | Abstain when the user asks for private data, credentials, internal records, or unauthorized access |
| Dependency anomaly | 2 | Treat stale, missing, or conflicting external-state claims as insufficient evidence or clarification needs |
| Low-quality evidence | 2 | Avoid overclaiming when evidence is weak, partial, contradictory, or too generic |
| Cross-cutting enterprise cases | 2 | Combine long query, colloquial wording, constraints, or multi-hop reasoning with one of the new dimensions |

Dimensions may overlap. For example, a case can be both `long_query` and
`permission_privacy`, or both `adversarial` and `low_quality_evidence`. The
release gate will require at least two cases for every existing required quality
dimension and every new enterprise dimension.

The response-mode mix is fixed so corpus drift is easy to review:

- 18 grounded-answer cases;
- 4 no-evidence cases;
- 4 clarification cases;
- 4 constraint-conflict cases.

## Case Design

Each new case uses the existing strict schema:

- `id`, `query`, `category`, `dimensions`, `expectation`, and
  `offline_fixture`;
- compact `offline_fixture.evidence` rows for grounded answers;
- empty evidence for `no_evidence`, `clarification`, and
  `constraint_conflict`.

The new cases should read like enterprise support and operations queries while
remaining within the repository's recipe-domain fixture style. They should not
contain real secrets, real customer data, real employee information, or live
system identifiers. Synthetic privacy and permission examples must be obviously
fake.

Low-quality evidence is represented deterministically through the fixture:

- if the evidence is too weak to answer, use `no_evidence`;
- if the user has not provided enough scope, use `clarification`;
- if requirements contradict each other, use `constraint_conflict`;
- if the answer is grounded, include evidence that supports every expected
  answer term without adding unsupported claims.

Dependency anomalies are also represented as offline expectations, not real
failures. A query can ask for current availability, newest provider status,
secret rotation state, or a live customer system detail; the correct offline
answer should say the curated evidence is insufficient or ask for a permitted
source.

## Release Policy

Update `eval/release_gate.json`:

- `suite_minimum_cases.quality_eval`: `30`;
- `minimum_total_cases`: `69`;
- `quality_dimension_minimum_cases` keeps the existing six required dimensions
  and adds the five enterprise dimensions, each with minimum `2`;
- all existing quality metric thresholds remain unchanged.

No new metric calculation is needed. The current evaluator already reports
`quality_eval.metrics.dimension_counts`, and the release gate already checks
configured dimension minimums from that map.

## Testing Strategy

Implementation follows test-driven development:

1. Tighten the curated corpus test to require exactly 30 cases, unique IDs, no
   replacement characters, the existing response-mode contract, and the five new
   dimension minimums.
2. Update offline quality metric assertions to expect 30 passing cases and
   dimension counts for all gated dimensions.
3. Update release-gate policy tests to require 69 total cases, 30 quality cases,
   and the five new dimension minimums.
4. Add or update documentation assertions if the offline gate documentation is
   expected to mention the new corpus size and dimensions.
5. Replace or append the 12 fixture rows with strict-schema cases.
6. Run focused evaluation and release-gate tests, then the offline release gate.

Focused verification:

```powershell
python -m pytest tests/test_eval_queries.py tests/test_release_gate.py -q
python scripts/release_gate.py
```

If formatting or linting touches Python test files, run the relevant focused
tests again.

## Files and Boundaries

- `tests/fixtures/curated_eval_corpus.json`: add 12 strict-schema quality cases.
- `tests/test_eval_queries.py`: update corpus size, response-mode mix, and
  dimension-count expectations.
- `eval/release_gate.json`: raise quality and total case thresholds; require new
  dimensions.
- `tests/test_release_gate.py`: update policy, report builders, and threshold
  assertions.
- `docs/offline_evaluation_release_gate.md`: document the 30-case corpus and new
  enterprise dimensions.

No production package changes are expected. If implementation reveals that the
existing scorer cannot express one of the approved scenarios, prefer adjusting
the case design before changing scorer semantics.

## Acceptance Criteria

- `load_eval_cases(DEFAULT_CORPUS_PATH)` returns exactly 30 valid cases.
- All case IDs are unique and every query is valid UTF-8 text without
  replacement characters.
- The five new enterprise dimensions each have at least two cases.
- The existing six required quality dimensions still have at least two cases.
- Offline `quality_eval` passes with `response_mode_accuracy == 1.0`,
  `abstention_accuracy == 1.0`, `fallback_rate == 0.0`, and
  `retrieval_degradation_rate == 0.0`.
- The default release policy requires 30 quality cases and 69 total cases.
- Focused evaluation and release-gate tests pass.
- `python scripts/release_gate.py` passes.
