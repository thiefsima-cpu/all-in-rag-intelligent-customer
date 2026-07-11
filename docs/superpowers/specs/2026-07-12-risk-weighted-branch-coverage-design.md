# Risk-Weighted Branch Coverage Design

## Context

The repository enables branch measurement for `rag_modules` and `scripts`, but the only enforced
full-suite threshold is the combined coverage value in `pyproject.toml`. The measured baseline is:

- combined coverage: 80.45%;
- `rag_modules` statement coverage: 84.36%;
- `rag_modules` branch coverage: 57.36%;
- configured combined threshold: 70%.

This gap matters because high statement coverage can hide untested decisions. The largest missing
areas are production paths such as parent-document enrichment, Milvus writes, graph path ranking,
vector retrieval, graph evidence orchestration, and Neo4j fallback behavior. Adding tests for DTOs,
protocol declarations, or trivial models would improve the headline number without reducing the
same operational risk.

A locally generated coverage snapshot showed 2,645 covered branch exits out of 4,636 in
`rag_modules`, or approximately 57.05%. Reaching 70% requires at least 3,246 covered exits, a net
increase of 601. The implementation target is therefore approximately 620 additional covered
branch exits, leaving a small margin above the threshold.

## Goals

- Raise full-suite `rag_modules` branch coverage to at least 70%, targeting at least 70.3% at
  delivery.
- Raise the combined coverage threshold in `pyproject.toml` from 70% to 75%.
- Add a separate, automatically failing `rag_modules` branch-coverage gate at 70%.
- Cover high-risk success, boundary, partial-failure, cancellation, timeout, and fallback behavior.
- Keep all new tests deterministic and independent of live Milvus, Neo4j, model providers, and
  Docker services.
- Preserve existing production behavior unless a new regression test exposes a real defect.

## Non-Goals

- Reaching 70% by testing DTO construction, protocol declarations, or trivial configuration
  accessors.
- Changing coverage omit or exclude rules to reduce the denominator.
- Requiring every individual file to reach 70% branch coverage.
- Raising the combined threshold directly to 80% in this change.
- Broad production refactoring or new production dependencies.
- Starting or mutating external Milvus, Neo4j, or model-provider state.

## Coverage Policy

The repository will enforce two complementary thresholds:

1. `tool.coverage.report.fail_under = 75` protects combined statement and branch coverage.
2. `tool.graph_rag.coverage.rag_modules_branch_fail_under = 70` protects branch coverage for
   production package files only.

The two thresholds are intentionally independent. Combined coverage is weighted by the much larger
statement count and can remain high while decision coverage regresses. The separate branch gate
prevents straight-line tests from masking missing error, fallback, and boundary paths.

No per-file threshold will be added. Per-file enforcement would create noise around small modules,
defensive paths, and protocol-heavy files. Critical-file quality remains governed by the risk list,
behavioral assertions, and review.

## Risk-Weighted Scope

### First Ring: Named Critical Paths

The first ring is always implemented:

- `rag_modules/retrieval/parent_doc_enricher.py`
- `rag_modules/infra/milvus/writer.py`
- `rag_modules/graph/path_ranker.py`
- `rag_modules/retrieval/adapters/vector_retriever.py`
- `rag_modules/graph/evidence_orchestrator.py`
- `rag_modules/graph/evidence_builder.py`
- `rag_modules/retrieval/adapters/neo4j_fallback_retriever.py`

Together these files account for 246 branch exits in the observed baseline, with only 30 covered.
They cannot take global branch coverage to 70% by themselves, so the second ring is required.

### Second Ring: Adjacent High-Risk Runtime Paths

The second ring is selected incrementally from these modules according to current missing-branch
count and behavioral risk:

- `rag_modules/infra/semantic_graph_writer.py`
- `rag_modules/graph/reasoning_strategy.py`
- `rag_modules/graph/entity_linker.py`
- `rag_modules/retrieval/adapters/graph_kv_retriever.py`
- `rag_modules/retrieval/hybrid_executor.py`
- `rag_modules/retrieval/hybrid_index_service.py`
- `rag_modules/retrieval/hybrid_runtime.py`
- `rag_modules/graph/retrieval_postprocess.py`
- `rag_modules/graph/query_executor.py`
- `rag_modules/graph/query_resolution.py`
- `rag_modules/infra/milvus/search.py`
- `rag_modules/infra/milvus/blue_green.py`

Implementation stops adding second-ring tests once the full-suite package result has a stable margin
of at least 70.3%, subject to completing coherent test scenarios already in progress.

### Third Ring: Conditional Reserve

If the first two rings do not reach the target, the implementation may extend to these runtime
paths:

- `rag_modules/build_pipeline/graph_preparation/document_builder.py`
- `rag_modules/runtime/artifact_adapters.py`
- `rag_modules/generation/clients/adapter.py`
- other production modules selected from the fresh missing-branch report.

A third-ring module must have meaningful failure or boundary behavior and a material missing-branch
count. Protocol-only, DTO-only, and simple-model modules are not eligible.

## Test Design

Tests use real domain objects and narrow fake ports. Fake clients, sessions, drivers, and services
must implement the relevant context-manager, iteration, and result interfaces rather than returning
loosely structured values that bypass production behavior. Assertions cover returned values,
metadata, and material side effects; call-count-only tests are insufficient.

### Parent-Document Enrichment

Cover empty parent maps, `top_n` boundaries, missing parent records, supported identifier precedence,
content truncation, graph-context append and de-duplication, metadata inheritance, and evidence
defaults. Verify unchanged documents are preserved where attachment is not applicable.

### Milvus Writes

Cover empty input, explicit and default target collection selection, collection-creation failure,
index-creation failure, field truncation, batching, flushing, loading, incremental-write preconditions,
and embedding or client failures. Replace the fixed wait with a patched clock in tests.

### Graph Ranking And Evidence Construction

Cover direct semantic-relationship scoring and count fallback, relationship and evidence-unit
weights, recipe-presence weight, empty and overlapping queries, all de-duplication key paths, content
and graph-evidence merging, empty paths, missing relationship endpoints, relationship de-duplication,
and relationship limits.

### Vector Retrieval And Neo4j Fallback

Cover cancellation before and after vector retrieval, vector-provider failure, empty results,
malformed metadata, score conversion, candidate limits, neighbor enrichment with and without a
driver, timeout propagation, and neighbor-query failure. Cover fallback input guards, partial Neo4j
records, invalid scores and list values, entity and topic result construction, neighbor filtering,
and exception degradation.

### Graph Evidence Orchestration

Cover path-finding, entity-relation, and multi-hop dispatch; unparseable records; disconnected
Neo4j; empty and multiple subgraphs; merge, reasoning, and post-processing failures; cancellation and
budget exceptions that must propagate; path, subgraph, and unsupported query types; final `top_k`
truncation; evidence-unit counts; and trace events.

### Second-Ring Graph Paths

Cover semantic write-row normalization and transaction counts; entity-link candidate ranking,
de-duplication, contextual label priority, and driver failure; graph key/value match strength,
richness, degree, de-duplication, and result limits; causal, compositional, comparative, and
connectivity reasoning; graph query parameters and target filters; malformed Neo4j post-processing,
subgraph merging, and evidence de-duplication.

### Second-Ring Retrieval And Storage Paths

Cover Milvus filter-expression and hit formatting behavior, search failures, blue/green alias
publication, rollback, and candidate discard. Cover hybrid cache absence, corruption, signature
mismatch, source partial failure, lazy service construction, and parent attachment where fresh
coverage reports show those paths remain material.

## Test Organization

The first ring uses focused files:

- `tests/test_parent_doc_enricher.py`
- `tests/test_milvus_writer.py`
- `tests/test_graph_path_ranker.py`
- `tests/test_vector_retriever.py`
- `tests/test_neo4j_fallback_retriever.py`
- `tests/test_graph_evidence_orchestrator.py`

Existing graph reasoning, semantic writer, hybrid retrieval, graph retrieval, and Milvus blue/green
test files are extended when their fixtures and responsibility already match the scenario. A new
focused file is preferred when adding tests to an existing file would mix unrelated responsibilities.

Parameterization is limited to input variants of one behavior. Distinct branches with different
business meaning remain separate tests.

## Branch Coverage Gate

Add `scripts/check_branch_coverage.py`. It reads coverage.py JSON output, normalizes Windows and
POSIX path separators, selects `rag_modules/**`, and aggregates `covered_branches` and
`num_branches` from each matching file summary.

The command reads the default threshold from:

```toml
[tool.graph_rag.coverage]
rag_modules_branch_fail_under = 70
```

The command reports the actual percentage, covered exits, total exits, and configured threshold.
Its exit codes are:

- `0`: threshold met;
- `1`: valid report below the threshold;
- `2`: missing file, invalid JSON or schema, invalid configuration, no matching package files, or
  no branch data.

Unit tests cover exact-threshold success, below-threshold failure, malformed reports, empty reports,
zero-branch reports, invalid configuration, and both path separator styles.

## CI And Local Gate Integration

The CI pytest step continues generating terminal and XML coverage and additionally generates
`coverage.json`. Immediately after it, CI runs:

```text
python scripts/check_branch_coverage.py
```

The existing PR-only `diff-cover --fail-under=80` remains unchanged.

The local gate becomes:

1. `pre_commit`
2. `encoding_audit`
3. full pytest with terminal and JSON coverage output
4. `branch_coverage`
5. `release_gate`

The pytest step enforces combined coverage through coverage.py. The separate branch step gives a
distinct failure name and diagnostic. `README.md`, `docs/release_process.md`, local-gate tests, and
CI governance tests are updated with the new workflow.

Coverage database and report files remain generated artifacts and are ignored by Git.

## Implementation And Measurement Loop

For each focused module or coherent risk cluster:

1. Run the narrow existing test slice and record the target file's missing branches.
2. Add behavioral tests for a selected set of missing branches.
3. Run the focused tests.
4. Generate focused coverage JSON and verify the intended branch exits changed from missing to
   covered.
5. Run the adjacent subsystem tests.
6. After each ring, run full-suite coverage and recalculate the global package result.

Coverage-only tests may pass on their first execution because they document existing behavior. The
coverage delta is the evidence that they exercise a previously untested decision. If a test exposes
incorrect production behavior, retain the failing regression test, apply the smallest production
fix, and verify the red-green cycle before continuing.

## Failure Handling

- Request cancellation and budget exceptions must continue to propagate where their contracts say
  they are control flow, not ordinary degradation.
- External provider failures use existing safe logging and degradation behavior; tests must not
  assert or expose secrets.
- If an external-service branch cannot be exercised directly, use a faithful port fake. Do not
  start a live service solely for coverage.
- If a second-ring module produces little meaningful branch gain, stop expanding it and select the
  next high-risk module from the fresh report.
- If the second ring ends below 70%, activate eligible third-ring modules. Do not lower either
  threshold or change exclusions.
- Environment-only full-suite failures are rerun with an isolated temporary directory and reported
  separately from code failures.

## Verification

Completion requires fresh evidence for all of the following:

- focused tests for every changed test cluster pass;
- adjacent graph, retrieval, Milvus, build, generation, or runtime slices pass as applicable;
- full pytest completes with zero failures and zero errors;
- combined coverage is at least 75%;
- `rag_modules` branch coverage is at least 70%, targeting at least 70.3%;
- branch-gate tests, local-gate tests, and CI governance tests pass;
- Ruff or the repository pre-commit suite passes after any auto-fixes are inspected;
- `python scripts/release_gate.py` passes;
- the final diff contains no `.coverage`, `coverage.json`, caches, or generated reports.

The implementation stops once these requirements are satisfied. It does not add low-value tests to
maximize coverage beyond the approved margin.
