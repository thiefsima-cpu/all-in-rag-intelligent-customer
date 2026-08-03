# Offline Evaluation Release Gate

The release gate runs deterministic offline smoke suites and the curated
`quality_eval` suite. `quality_eval` is always required and uses offline
fixtures; this gate does not require a model provider, Milvus, or Neo4j.

The offline gate is the deterministic contract regression layer. It complements,
but does not replace, the live dependency participation gate
(`graph-rag-integration-gate`) or the live AI quality proof gate
(`graph-rag-live-quality-gate`).

## Run

Run the final local gate before release handoff when you need engineering and
offline release checks in one sequence:

```powershell
python scripts/local_gate.py
```

The final local gate stops at the first failing step and runs:

- `pre-commit run --all-files`
- `python scripts/check_encoding.py`
- `python -m pytest -q`
- `python scripts/release_gate.py`

Run the standalone release gate before packaging, tagging, or deploying:

```powershell
graph-rag-release-gate
```

It exits with code `0` only when every required suite and coverage threshold
passes. Reports are written to:

- `eval/reports/release_gate/report.json`
- `eval/reports/release_gate/summary.md`

Dependency outages still prevent a PASS, but the report keeps them distinct
from quality regressions through `failure_type`.

## Gate Policy

Thresholds live in `eval/release_gate.json`. The release policy requires:

- all six suites, including `quality_eval`, to be available;
- 69 or more total cases;
- 100% overall and per-suite pass rate;
- at least 24 route-semantics cases;
- all 9 required route categories;
- at least 30 quality-eval cases.

The `quality_eval` policy also requires at least two cases for each required
quality dimension. The first six dimensions cover the baseline deterministic
quality risks; the last five add enterprise long-tail and governance-oriented
coverage:

- `no_evidence`
- `ambiguity`
- `multi_hop`
- `constraint_conflict`
- `long_query`
- `colloquial_zh`
- `long_tail`
- `adversarial`
- `permission_privacy`
- `dependency_anomaly`
- `low_quality_evidence`

The gate checks these counts from `quality_eval.metrics.dimension_counts`, not
from corpus size alone.

## Quality Corpus Contract

The curated quality corpus uses a strict nested schema. The old flat
`expected_*` fields are not accepted.

Each row has:

- root fields: `id`, `query`, `category`, `dimensions`, `expectation`,
  `offline_fixture`;
- `expectation.response_mode`: one of `grounded_answer`, `no_evidence`,
  `clarification`, or `constraint_conflict`;
- `expectation.strategy`: a strategy string or `null`;
- `expectation.entity_names`, `answer_terms`, and `entity_relevance`;
- `offline_fixture.strategy`, `answer`, and compact `evidence` rows.

Grounded cases must contain fixture evidence and every positively expected
entity must appear in the fixture evidence. Abstention cases (`no_evidence`,
`clarification`, and `constraint_conflict`) must have no evidence and no entity
expectations. A successful abstention is a primary expected outcome, not a
fallback.

The checked-in corpus contains 30 cases. The enterprise expansion keeps the
original deterministic recipe-domain shape while adding long-tail phrasing,
adversarial instruction pressure, permission/privacy boundaries, dependency
anomaly questions, and low-quality-evidence scenarios. These scenarios use
synthetic data only; they must not contain real secrets, real customer data,
real employee data, or live system identifiers.

## Quality Metrics

`scripts/eval_queries.py` reports:

- Recall@K, MRR, and nDCG@K for grounded-answer cases with relevance labels;
- `entity_hit_rate` across cases with expected entity names;
- deterministic lexical faithfulness and citation accuracy for grounded-answer
  cases;
- `response_mode_accuracy` across all quality cases;
- `abstention_accuracy` across abstention cases only;
- `response_mode_counts` and `dimension_counts`;
- fallback case count, fallback rate, and fallback reasons;
- retrieval degraded case count, degradation rate, degraded sources, and source
  counts;
- P95 end-to-end latency;
- prompt, completion, and total tokens;
- estimated USD cost from configured model prices.

Retrieval and grounding averages are grounded-only. Abstention rows keep those
metrics as `None` and do not dilute grounded-answer quality signals.

The default gate requires:

- `quality_eval.metrics.recall_at_k >= 0.8`;
- `quality_eval.metrics.faithfulness >= 0.8`;
- `quality_eval.metrics.citation_accuracy >= 0.8`;
- `quality_eval.metrics.response_mode_accuracy >= 1.0`;
- `quality_eval.metrics.abstention_accuracy >= 1.0`;
- `quality_eval.metrics.fallback_rate <= 0.0`;
- `quality_eval.metrics.retrieval_degradation_rate <= 0.0`;
- `quality_eval.metrics.p95_latency_ms <= 2000`;
- `quality_eval.metrics.estimated_cost_usd <= 1.0`.

Faithfulness is an offline lexical-support heuristic, not an LLM judge. It is
stable enough for regression checks and can later be replaced by a model-backed
judge without changing the report contract.

## Updating Goldens

1. Add or change a case under `tests/fixtures/`.
2. Keep the strict nested schema; do not reintroduce flat `expected_*` fields.
3. Run `python -m pytest tests/test_eval_queries.py -q`.
4. Run `graph-rag-release-gate`.
5. Raise minimum case, dimension, or metric thresholds when coverage expands.

Do not lower a threshold merely to make a regression pass. Any intentional
behavior change should update the corpus expectation and be reviewed with the
implementation change.
