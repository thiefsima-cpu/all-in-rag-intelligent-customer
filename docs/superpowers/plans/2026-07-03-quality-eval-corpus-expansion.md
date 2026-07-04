# Quality Eval Corpus Expansion Implementation Plan

Status: completed

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the nine-case positive-only quality corpus with a strict 18-case contract that gates grounded answers, safe abstention, ambiguity handling, multi-hop reasoning, constraint conflicts, long queries, and colloquial Chinese.

**Architecture:** Parse every corpus row into strict dataclasses with one mutually exclusive response mode and a compact offline fixture. Normalize runtime and offline outputs into one `EvalObservation`, score both paths with one function, and expose response-mode and dimension coverage metrics to the existing release gate. Delete the old flat `expected_*` schema and the expectation-driven offline evidence synthesis; do not dual-read either format.

**Tech Stack:** Python 3.11, dataclasses, `enum.StrEnum`, JSON fixtures, `unittest`/pytest, Ruff, mypy, deterministic offline release-gate scripts.

---

## File Map

- Modify `scripts/eval_queries.py`: strict case types, parsing, observation normalization, shared scorer, offline fixture conversion, and aggregate metrics.
- Replace `tests/fixtures/curated_eval_corpus.json`: migrate the original nine cases and add nine cases in the new schema.
- Modify `tests/test_eval_queries.py`: strict-loader, scorer, corpus-distribution, and aggregate-metric tests.
- Modify `eval/release_gate.json`: raise case thresholds, declare dimension minima, and gate new accuracy metrics.
- Modify `scripts/release_gate.py`: evaluate per-dimension minimum counts from the quality report.
- Modify `tests/test_release_gate.py`: update passing reports and assert dimension failures and new policy values.
- Modify `docs/offline_evaluation_release_gate.md`: document the strict schema, 18-case mix, and new metrics.

### Task 1: Replace the Flat Corpus Model With a Strict Typed Contract

**Files:**
- Modify: `scripts/eval_queries.py:15-75`
- Test: `tests/test_eval_queries.py`

- [ ] **Step 1: Write failing strict-schema tests**

Import `EvalResponseMode` with `EvalCase`, then add tests that build temporary JSON corpora:

```python
def _valid_case_payload() -> dict:
    return {
        "id": "grounded-01",
        "query": "宫保鸡丁怎么做？",
        "category": "single_recipe",
        "dimensions": ["single_recipe"],
        "expectation": {
            "response_mode": "grounded_answer",
            "strategy": "hybrid_traditional",
            "recipe_names": ["宫保鸡丁"],
            "answer_terms": ["宫保鸡丁"],
            "recipe_relevance": {"宫保鸡丁": 3.0},
        },
        "offline_fixture": {
            "strategy": "hybrid_traditional",
            "answer": "依据菜谱证据 #1，宫保鸡丁需要鸡丁、花生和调味汁。",
            "evidence": [
                {
                    "recipe_name": "宫保鸡丁",
                    "content": "宫保鸡丁需要鸡丁、花生和调味汁。",
                    "score": 1.0,
                    "evidence_type": "text",
                }
            ],
        },
    }


def test_load_eval_cases_parses_strict_nested_contract(self) -> None:
    payload = _valid_case_payload()
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "corpus.json"
        path.write_text(json.dumps([payload], ensure_ascii=False), encoding="utf-8")
        cases = load_eval_cases(path)

    self.assertEqual(cases[0].case_id, "grounded-01")
    self.assertEqual(cases[0].dimensions, ("single_recipe",))
    self.assertEqual(cases[0].expectation.response_mode, EvalResponseMode.GROUNDED_ANSWER)
    self.assertEqual(cases[0].expectation.recipe_relevance, {"宫保鸡丁": 3.0})
    self.assertEqual(cases[0].offline_fixture.evidence[0].recipe_name, "宫保鸡丁")


def test_load_eval_cases_rejects_legacy_expected_fields(self) -> None:
    payload = _valid_case_payload()
    payload["expected_strategy"] = "hybrid_traditional"
    with self.assertRaisesRegex(ValueError, "legacy fields.*expected_strategy"):
        self._load_single_payload(payload)


def test_load_eval_cases_rejects_duplicate_ids(self) -> None:
    payload = _valid_case_payload()
    with self.assertRaisesRegex(ValueError, "duplicate case id.*grounded-01"):
        self._load_payloads([payload, copy.deepcopy(payload)])


def test_load_eval_cases_rejects_abstention_with_evidence(self) -> None:
    payload = _valid_case_payload()
    payload["expectation"]["response_mode"] = "no_evidence"
    payload["expectation"]["recipe_names"] = []
    payload["expectation"]["recipe_relevance"] = {}
    with self.assertRaisesRegex(ValueError, "no_evidence.*evidence must be empty"):
        self._load_single_payload(payload)
```

Add `_load_single_payload` and `_load_payloads` methods to the test class using a temporary file; do not mock the parser.

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -k "strict_nested_contract or legacy_expected_fields or duplicate_ids or abstention_with_evidence" -q
```

Expected: collection fails because `EvalResponseMode` and the strict nested fields do not exist.

- [ ] **Step 3: Implement the strict dataclasses and parser**

Replace the current `EvalCase` fields and permissive `from_dict` with these types and responsibilities:

```python
class EvalResponseMode(StrEnum):
    GROUNDED_ANSWER = "grounded_answer"
    NO_EVIDENCE = "no_evidence"
    CLARIFICATION = "clarification"
    CONSTRAINT_CONFLICT = "constraint_conflict"

    @property
    def is_abstention(self) -> bool:
        return self is not EvalResponseMode.GROUNDED_ANSWER


@dataclass(frozen=True)
class EvalExpectation:
    response_mode: EvalResponseMode
    strategy: str | None
    recipe_names: tuple[str, ...]
    answer_terms: tuple[str, ...]
    recipe_relevance: dict[str, float]


@dataclass(frozen=True)
class OfflineEvidenceFixture:
    recipe_name: str
    content: str
    score: float
    evidence_type: str


@dataclass(frozen=True)
class OfflineEvalFixture:
    strategy: str
    answer: str
    evidence: tuple[OfflineEvidenceFixture, ...]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    query: str
    category: str
    dimensions: tuple[str, ...]
    expectation: EvalExpectation
    offline_fixture: OfflineEvalFixture
```

Use explicit allowed-key sets for every object. Reject unknown root keys, all root keys beginning with `expected_`, missing required keys, booleans used as numbers, non-finite/negative relevance or scores, duplicate dimensions, empty strings, unknown response modes, strategy mismatch, abstention evidence, and grounded fixtures with no evidence. Include `path`, case index, and case ID in `ValueError` messages. After parsing all rows, reject duplicate IDs in `load_eval_cases`.

- [ ] **Step 4: Run the strict-schema tests and verify GREEN**

Run the command from Step 2.

Expected: all selected tests pass.

- [ ] **Step 5: Run the complete evaluation test file**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -q
```

Expected: existing tests that construct the old `EvalCase` fail. This is intentional RED for Task 2; do not add compatibility properties.

- [ ] **Step 6: Commit the strict contract**

```powershell
git add scripts/eval_queries.py tests/test_eval_queries.py
git commit -m "refactor: replace quality eval case contract"
```

### Task 2: Normalize Runtime Output and Score All Response Modes Once

**Files:**
- Modify: `scripts/eval_queries.py:280-470`
- Test: `tests/test_eval_queries.py`

- [ ] **Step 1: Replace old-case tests and add four response-mode tests**

Create cases with `_eval_case(response_mode, ...)` using only the new dataclasses. Add one direct scorer test per mode. The observations must include:

```python
grounded = EvalObservation(
    strategy="hybrid_traditional",
    answer="依据菜谱证据 #1，宫保鸡丁需要鸡丁和花生。",
    documents=(
        EvidenceDocument(
            content="宫保鸡丁需要鸡丁和花生。",
            recipe_name="宫保鸡丁",
            doc_id="doc-1",
            score=1.0,
            source="test",
        ),
    ),
    latency_ms=12.5,
    plan={"used_cache": False, "validation_errors": []},
    contracts={"answer_response": {}, "route_resolution": {}},
    resilience={
        "fallback_used": False,
        "fallback_reasons": [],
        "retrieval_degraded": False,
        "degraded_sources": [],
        "degraded_candidates": [],
    },
    cost={
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "token_usage_source": "test",
    },
)
```

Assert:

```python
self.assertTrue(score_eval_observation(grounded_case, grounded, top_k=6, generate=True)["passed"])
self.assertTrue(no_evidence_result["evaluation"]["response_mode_passed"])
self.assertTrue(clarification_result["evaluation"]["response_mode_passed"])
self.assertTrue(conflict_result["evaluation"]["response_mode_passed"])
self.assertEqual(no_evidence_result["retrieval"]["doc_count"], 0)
self.assertIsNone(no_evidence_result["grounding"]["faithfulness"])
```

For negative coverage, give a no-evidence case one document and assert failures include `unexpected_evidence` and `response_mode_mismatch`.

- [ ] **Step 2: Run scorer tests and verify RED**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -k "response_mode or unexpected_evidence" -q
```

Expected: collection fails because `EvalObservation` and `score_eval_observation` do not exist.

- [ ] **Step 3: Implement `EvalObservation` and the shared scorer**

Add a frozen dataclass matching the test fixture. Implement:

```python
def score_eval_observation(
    case: EvalCase,
    observation: EvalObservation,
    *,
    top_k: int,
    generate: bool,
) -> dict[str, Any]:
```

The function must:

- compare strategy only when `expectation.strategy` is not `None`;
- derive recipe names and ranked names from `observation.documents`;
- require expected recipes and answer terms;
- require documents for `grounded_answer`;
- require zero documents, zero recipe names, and no citation marker for all abstention modes;
- add `unexpected_evidence`, `unexpected_recipe_names`, `unexpected_citation`, or `missing_evidence` before a final `response_mode_mismatch` marker;
- compute retrieval and grounding only for `grounded_answer`; use explicit `None` ranking/grounding metrics for abstention;
- retain result sections `evaluation`, `retrieval`, `grounding`, `cost`, `resilience`, `runtime`, and `contracts`;
- add case `id`, `dimensions`, expected/actual response-mode fields, and `response_mode_passed`.

Delete `_complex_answer_failed`; graph cases are now governed by explicit answer terms, evidence type, and grounding rather than category-specific hidden rules.

- [ ] **Step 4: Refactor runtime `evaluate_case` into normalization plus scoring**

Keep the current API call/route call, response-contract extraction, cost parsing, and resilience parsing. Replace all expectation comparisons in `evaluate_case` with construction of one `EvalObservation`, followed by:

```python
return score_eval_observation(case, observation, top_k=top_k, generate=generate)
```

Update `_FakeResponse`-based tests to build the new typed `EvalCase`. Do not add `expected_strategy`, `expected_recipe_names`, `expected_answer_terms`, or `expected_recipe_relevance` accessors.

- [ ] **Step 5: Run scorer and runtime tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -k "response_mode or evaluate_case" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit the shared scorer refactor**

```powershell
git add scripts/eval_queries.py tests/test_eval_queries.py
git commit -m "refactor: unify quality eval response scoring"
```

### Task 3: Replace Synthetic Offline Evidence and Add Outcome Metrics

**Files:**
- Modify: `scripts/eval_queries.py:470-950`
- Test: `tests/test_eval_queries.py`

- [ ] **Step 1: Add failing offline-fixture and metric tests**

Add tests proving the offline path uses the fixture instead of the expectation:

```python
def test_offline_no_evidence_case_preserves_empty_evidence(self) -> None:
    case = self._eval_case(
        response_mode=EvalResponseMode.NO_EVIDENCE,
        answer_terms=("证据不足",),
        fixture_answer="当前菜谱证据不足，无法给出可靠做法。",
        fixture_evidence=(),
    )

    item = evaluate_offline_quality_case(case, index=0, top_k=6, generate=True)

    self.assertTrue(item["passed"])
    self.assertEqual(item["retrieval"]["doc_count"], 0)
    self.assertEqual(item["retrieval"]["recipe_names"], [])
    self.assertEqual(item["evaluation"]["actual_response_mode"], "no_evidence")
```

Add a metrics test with one passing grounded result, three passing abstention results, and one failed grounded result. Assert:

```python
self.assertEqual(metrics["response_mode_accuracy"], 0.8)
self.assertEqual(metrics["abstention_accuracy"], 1.0)
self.assertEqual(
    metrics["response_mode_counts"],
    {"clarification": 1, "constraint_conflict": 1, "grounded_answer": 2, "no_evidence": 1},
)
self.assertEqual(metrics["dimension_counts"]["colloquial_zh"], 2)
```

Also assert abstention rows do not enter recall, faithfulness, or citation averages.

- [ ] **Step 2: Run offline/metric tests and verify RED**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -k "offline_no_evidence or outcome_metrics" -q
```

Expected: tests fail because offline evaluation still synthesizes a document and the new metrics are absent.

- [ ] **Step 3: Build offline observations only from `offline_fixture`**

Delete `_offline_quality_strategy`, `_offline_quality_recipe_names`, `_offline_quality_terms`, `_offline_quality_documents`, and `_offline_quality_answer`.

Implement `build_offline_eval_observation(case, index, generate)` so each evidence fixture maps to an `EvidenceDocument` with stable IDs `offline-quality-{case.case_id}-{rank}`, fixture content and score, source `offline_quality`, and graph evidence only when `evidence_type == "graph"`. Use the fixture answer only when `generate=True`. Set fallback and degradation false and cost to zero. Then reduce `evaluate_offline_quality_case` to observation construction plus `score_eval_observation`.

- [ ] **Step 4: Add response-mode and dimension aggregates**

In `calculate_eval_metrics`:

```python
response_mode_cases = [item for item in results if item.get("evaluation", {}).get("expected_response_mode")]
abstention_cases = [
    item
    for item in response_mode_cases
    if item["evaluation"]["expected_response_mode"] != EvalResponseMode.GROUNDED_ANSWER.value
]
response_mode_counts = Counter(
    item["evaluation"]["expected_response_mode"] for item in response_mode_cases
)
dimension_counts = Counter(
    dimension for item in results for dimension in item.get("dimensions", [])
)
```

Return sorted dictionaries plus:

```python
"response_mode_accuracy": sum(
    bool(item["evaluation"].get("response_mode_passed")) for item in response_mode_cases
) / len(response_mode_cases),
"abstention_accuracy": sum(
    bool(item["evaluation"].get("response_mode_passed")) for item in abstention_cases
) / len(abstention_cases),
"response_mode_counts": dict(sorted(response_mode_counts.items())),
"dimension_counts": dict(sorted(dimension_counts.items())),
```

Filter ranking and grounding aggregates to `grounded_answer` results only. Preserve `None` when an applicable list is empty.

- [ ] **Step 5: Run focused and complete evaluation tests**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -q
```

Expected: strict contract, runtime, offline, and metric tests pass except the default-corpus count test, which remains RED until Task 4.

- [ ] **Step 6: Commit offline observation and metric changes**

```powershell
git add scripts/eval_queries.py tests/test_eval_queries.py
git commit -m "refactor: evaluate offline quality fixtures"
```

### Task 4: Migrate and Expand the Curated Corpus to 18 Cases

**Files:**
- Replace: `tests/fixtures/curated_eval_corpus.json`
- Modify: `tests/test_eval_queries.py`

- [ ] **Step 1: Tighten the corpus contract test**

Replace the current `>= 9` assertions with:

```python
cases = load_eval_cases(DEFAULT_CORPUS_PATH)
self.assertEqual(len(cases), 18)
self.assertEqual(len({case.case_id for case in cases}), 18)
self.assertFalse(any("\ufffd" in case.query for case in cases))
dimension_counts = Counter(dimension for case in cases for dimension in case.dimensions)
for dimension in {
    "no_evidence",
    "ambiguity",
    "multi_hop",
    "constraint_conflict",
    "long_query",
    "colloquial_zh",
}:
    self.assertGreaterEqual(dimension_counts[dimension], 2)
self.assertEqual(
    Counter(case.expectation.response_mode.value for case in cases),
    {
        "grounded_answer": 12,
        "no_evidence": 2,
        "clarification": 2,
        "constraint_conflict": 2,
    },
)
```

- [ ] **Step 2: Run the corpus test and verify RED**

Run:

```powershell
python -m pytest tests/test_eval_queries.py::EvalQueriesTests::test_curated_eval_corpus_loads_from_fixture -q
```

Expected: FAIL because the checked-in corpus still uses legacy fields and has nine rows.

- [ ] **Step 3: Replace the fixture with the new 18-case corpus**

Migrate the original nine semantic cases and add nine new rows. Use these IDs, response modes, and dimensions exactly:

| ID | Response mode | Required dimensions | Expected recipe when applicable |
|---|---|---|---|
| `complex-relation-01` | grounded_answer | `complex_relation`, `multi_hop`, `long_query` | 水煮肉片 |
| `semantic-flavor-01` | grounded_answer | `semantic_flavor`, `multi_hop` | none |
| `single-recipe-01` | grounded_answer | `single_recipe` | 宫保鸡丁 |
| `single-recipe-02` | grounded_answer | `single_recipe` | 鱼香肉丝 |
| `constrained-recommendation-01` | grounded_answer | `constrained_recommendation` | none |
| `recommendation-01` | grounded_answer | `recommendation` | none |
| `single-recipe-03` | grounded_answer | `single_recipe` | 西红柿炒鸡蛋 |
| `constrained-recommendation-02` | grounded_answer | `constrained_recommendation` | none |
| `subgraph-01` | grounded_answer | `subgraph` | none |
| `no-evidence-01` | no_evidence | `no_evidence` | none |
| `no-evidence-02` | no_evidence | `no_evidence`, `long_query` | none |
| `ambiguity-01` | clarification | `ambiguity`, `colloquial_zh` | none |
| `ambiguity-02` | clarification | `ambiguity`, `colloquial_zh` | none |
| `multi-hop-01` | grounded_answer | `multi_hop` | 水煮肉片 |
| `constraint-conflict-01` | constraint_conflict | `constraint_conflict`, `long_query` | none |
| `constraint-conflict-02` | constraint_conflict | `constraint_conflict`, `colloquial_zh` | none |
| `long-query-01` | grounded_answer | `long_query`, `constrained_recommendation` | none |
| `colloquial-zh-01` | grounded_answer | `colloquial_zh`, `single_recipe` | 西红柿炒鸡蛋 |

Use the original nine queries unchanged. Use these new queries:

```text
有没有一道叫“月光炖彩虹”的传统川菜？请给我可靠做法。
请找一道同时属于明代宫廷菜、完全不使用任何食材、五分钟完成且名叫“云端凤凰”的菜，并给出出处和步骤。
那个鸡丁咋整来着？
来个不辣的、快点的，那个家常菜怎么弄？
从豆瓣酱和花椒出发，经过上浆、爆香和泼油这些步骤，怎样共同形成水煮肉片的麻辣风味？
推荐一道五分钟内完成、完全不用火、但必须慢炖两小时的牛肉菜。
我不要花生但又必须保留花生，整一道正宗宫保鸡丁，还一个条件都不能改。
家里只有一口锅，我是新手，希望三十分钟内做好两人份、少油、不辣、不要豆腐和花生、步骤不超过六步的热菜，请说明为什么符合每个条件。
冰箱里就俩西红柿和几个蛋，咋整一盘下饭的？
```

Grounded fixtures must contain at least one evidence row whose content supports every expected answer term. Every grounded answer must contain `依据菜谱证据 #1`. Abstention fixtures must have `evidence: []`, no citation marker, and answers containing their curated terms: `证据不足`, `请说明具体`, or both `冲突` and `放宽` as appropriate.

- [ ] **Step 4: Run the corpus and offline quality tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -q
```

Expected: all evaluation tests pass; offline metrics report 18 cases, response-mode accuracy 1.0, abstention accuracy 1.0, and no failures.

- [ ] **Step 5: Commit the migrated corpus**

```powershell
git add tests/fixtures/curated_eval_corpus.json tests/test_eval_queries.py
git commit -m "test: expand curated quality eval corpus"
```

### Task 5: Enforce Quality Dimensions and New Metrics in the Release Gate

**Files:**
- Modify: `eval/release_gate.json`
- Modify: `scripts/release_gate.py:525-655`
- Modify: `tests/test_release_gate.py`
- Modify: `docs/offline_evaluation_release_gate.md`

- [ ] **Step 1: Update test report builders and write failing gate tests**

Change `_quality_metrics()` and `_quality_suite_report()` to 18 cases, add accuracy values, and include:

```python
"response_mode_accuracy": 1.0,
"abstention_accuracy": 1.0,
"dimension_counts": {
    "ambiguity": 2,
    "colloquial_zh": 4,
    "constraint_conflict": 2,
    "long_query": 4,
    "multi_hop": 3,
    "no_evidence": 2,
},
```

Update passing total assertions from 48 to 57. Add:

```python
def test_gate_fails_when_quality_dimension_coverage_regresses(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    reports = _passing_reports_for_policy(policy)
    reports["quality_eval"]["metrics"]["dimension_counts"]["no_evidence"] = 1

    report = evaluate_gate(policy, reports)

    self.assertFalse(report["passed"])
    failed = {item["name"]: item for item in report["failed_checks"]}
    self.assertEqual(failed["quality_dimension:no_evidence"]["expected"], ">=2")
    self.assertEqual(failed["quality_dimension:no_evidence"]["actual"], 1)
```

Extend the default-policy test to require 18 quality cases, 57 total cases, each dimension minimum of 2, and both accuracy metric thresholds at 1.0.

- [ ] **Step 2: Run release-gate tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py -q
```

Expected: failures show old counts and no `quality_dimension:no_evidence` check.

- [ ] **Step 3: Update policy JSON and add dimension checks**

In `eval/release_gate.json` set:

```json
"minimum_total_cases": 57,
"suite_minimum_cases": {
  "quality_eval": 18
},
"quality_dimension_minimum_cases": {
  "no_evidence": 2,
  "ambiguity": 2,
  "multi_hop": 2,
  "constraint_conflict": 2,
  "long_query": 2,
  "colloquial_zh": 2
}
```

Preserve the other suite counts. Add metric thresholds:

```json
"quality_eval.metrics.response_mode_accuracy": {"minimum": 1.0},
"quality_eval.metrics.abstention_accuracy": {"minimum": 1.0}
```

In `evaluate_gate`, read `quality_eval.metrics.dimension_counts` as a dictionary and append one `_check` per configured dimension named `quality_dimension:<dimension>`. Missing or non-numeric counts have actual value `None` and fail as `suite-regression`. Reject boolean and negative dimension counts. Keep this separate from generic numeric metric thresholds because it evaluates a keyed coverage map.

- [ ] **Step 4: Run focused release-gate tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_gate.py -q
```

Expected: all release-gate tests pass with 57 total passing cases in fixtures.

- [ ] **Step 5: Update release documentation**

Update `docs/offline_evaluation_release_gate.md` to state:

- 57 total cases and 18 quality cases;
- strict nested `expectation` and `offline_fixture` schema;
- four response modes and six dimensions;
- abstention cases have no evidence and are not fallbacks;
- grounded-only applicability for retrieval/grounding metrics;
- 1.0 response-mode and abstention accuracy gates;
- two-case minimum for every required quality dimension.

- [ ] **Step 6: Run focused verification**

Run:

```powershell
python -m pytest tests/test_eval_queries.py tests/test_release_gate.py -q
```

Expected: both test files pass.

- [ ] **Step 7: Commit release policy and documentation**

```powershell
git add eval/release_gate.json scripts/release_gate.py tests/test_release_gate.py docs/offline_evaluation_release_gate.md
git commit -m "ci: gate quality eval scenario coverage"
```

### Task 6: Repository-wide Verification

**Files:**
- Verify only; apply fixes only to files already in this plan when a check exposes a task-related issue.

- [ ] **Step 1: Run Ruff on touched Python files**

```powershell
python -m ruff check scripts/eval_queries.py scripts/release_gate.py tests/test_eval_queries.py tests/test_release_gate.py
python -m ruff format --check scripts/eval_queries.py scripts/release_gate.py tests/test_eval_queries.py tests/test_release_gate.py
```

Expected: both commands exit 0.

- [ ] **Step 2: Run the complete test suite**

```powershell
python -m pytest -q
```

Expected: all tests pass with no warnings promoted to errors.

- [ ] **Step 3: Run repository hooks**

```powershell
pre-commit run --all-files
```

Expected: all hooks pass. If Ruff changes files, inspect the diff and rerun focused tests.

- [ ] **Step 4: Run the offline release gate**

```powershell
python scripts/release_gate.py
```

Expected: exit 0; the report shows 57 total cases, 18 `quality_eval` cases, both new accuracy metrics at 1.0, and all six quality dimensions satisfying their minimums.

- [ ] **Step 5: Inspect the final diff**

```powershell
git status --short
git diff --check
git diff --stat
```

Expected: only the files listed in this plan are changed, there are no whitespace errors, and generated files under `eval/reports/` remain untracked/ignored.

## Plan Self-review

- Spec coverage: Tasks 1-3 cover the strict contract, shared observation/scorer, offline fixtures, response modes, and metric applicability. Task 4 covers all 18 cases and six dimensions. Task 5 covers release policy and documentation. Task 6 covers required verification.
- Scope: one evaluation/release-policy subsystem; no production RAG behavior or dependencies change.
- Compatibility: no legacy corpus reader, alias properties, optional old fields, or expectation-driven evidence synthesis remains.
- Type consistency: `EvalResponseMode`, `EvalExpectation`, `OfflineEvidenceFixture`, `OfflineEvalFixture`, `EvalCase`, `EvalObservation`, and `score_eval_observation` names are used consistently across all tasks.
