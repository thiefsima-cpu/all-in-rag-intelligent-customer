# Offline Evaluation Release Gate

The default release gate runs only deterministic offline smoke suites. It does
not call DashScope, Milvus, Neo4j, or any other external service.

## Run

Run the fast deterministic gate:

```powershell
python scripts/release_gate.py
```

Explicitly include the quality stage when its external dependencies and
credentials are ready:

```powershell
python scripts/release_gate.py --include-quality-eval
```

The equivalent environment opt-in is:

```powershell
$env:RELEASE_GATE_INCLUDE_QUALITY_EVAL = "true"
python scripts/release_gate.py
```

The command exits with code `0` only when every required suite and coverage
threshold passes. It writes:

- `eval/reports/release_gate/report.json`
- `eval/reports/release_gate/summary.md`

Use this command as a required check before packaging, tagging, or deploying a
release.

## Gate Policy

Thresholds live in `eval/release_gate.json`. The default policy requires:

- all five offline suites to be available;
- 39 or more total cases;
- 100% overall and per-suite pass rate;
- at least 24 route-semantics cases;
- all 9 required route categories.

The `answer_pipeline_real_route` suite also exposes contract pass rates for
plan, request, trace, graph, evidence, and offline-planner behavior. The
release policy requires each contract metric to remain `1.0`, so a route can no
longer pass the gate by preserving only the expected strategy and answer text.

The route corpus covers direct recipe lookup, recommendation, time and
exclusion constraints, classification, multi-hop reasoning, path finding,
subgraph retrieval, clustering, and combined retrieval.

## Quality Stage Policy

The default policy defines `quality_eval` as an optional stage. It uses the
`eval_quality` profile with `top_k=6` and answer generation enabled. When the
stage is selected, the gate requires:

- at least 6 quality cases;
- a 100% quality-suite pass rate;
- Recall@K, faithfulness, and citation accuracy of at least `0.8`;
- P95 latency no greater than `2000 ms`;
- estimated total cost no greater than `$1.00`.

The quality stage may initialize model, Milvus, and Neo4j dependencies. It is
never selected implicitly, so the default release gate remains a fast,
deterministic smoke check.

## Quality Metrics

`scripts/eval_queries.py` now reports:

- Recall@K, MRR, and nDCG@K from expected recipe relevance;
- deterministic lexical faithfulness and citation accuracy;
- P95 end-to-end latency;
- prompt, completion, and total tokens;
- estimated USD cost from configured model prices.

Use `expected_recipe_relevance` for graded relevance:

```json
{
  "expected_recipe_relevance": {
    "recipe-a": 3,
    "recipe-b": 1
  }
}
```

Faithfulness is an offline lexical-support heuristic, not an LLM judge. It is
stable enough for regression checks and can be replaced by a model-backed
judge without changing the report contract.

Release policies may gate any suite metric with `metric_thresholds`:

```json
{
  "metric_thresholds": {
    "quality_eval.metrics.recall_at_k": {"minimum": 0.8},
    "quality_eval.metrics.p95_latency_ms": {"maximum": 2000},
    "quality_eval.metrics.estimated_cost_usd": {"maximum": 1.0}
  }
}
```

## Updating Goldens

1. Add or change a case under `tests/fixtures/`.
2. Run the focused smoke script and inspect its structured failures.
3. Run `python scripts/release_gate.py`.
4. Raise minimum case or category thresholds when coverage expands.

Do not lower a threshold merely to make a regression pass. Any intentional
behavior change should update the corpus expectation and be reviewed with the
implementation change.
