# Contract Kernel Dependency Break Design

## Goal

Break the runtime, retrieval, and query-understanding dependency cycle by introducing a
canonical contract kernel and moving shared DTOs/settings out of feature aggregation packages.

## Decision

Use `rag_modules.contracts` as the only canonical home for cross-subsystem contracts:

- Query contracts: `QueryPlan`, `QuerySemanticProfile`, `QuerySemanticScoreBreakdown`
- Retrieval contracts: `EvidenceDocument`, `RetrievalRequest`
- Query runtime settings: `QueryPlannerRuntimeSettings`, `QuerySemanticRuntimeSettings`
- LangChain compatibility helpers that convert contract documents at the edge

Do not keep compatibility re-export modules for the old contract ownership. Existing internal
imports must move to `rag_modules.contracts`.

## Architecture

The allowed dependency direction is:

`app / routing / graph / generation / retrieval / query_understanding / runtime -> contracts`

The contract kernel may depend only on standard library, external DTO libraries already used by
the contracts, and stable domain primitives such as `rag_modules.domain.shared`.

The kernel must not import feature packages:

- `rag_modules.retrieval`
- `rag_modules.query_understanding`
- `rag_modules.runtime`
- `rag_modules.routing`
- `rag_modules.graph`
- `rag_modules.generation`
- `rag_modules.app`

## Behavioral Notes

`QueryPlan` remains a data contract with `from_dict()` and `to_dict()` support, but feature policy
such as semantic inference belongs in query-understanding planner services. Kernel code should
coerce supplied payloads and preserve serialization shape without calling query-understanding
inference helpers.

`RetrievalRequest` keeps its planner-derived convenience properties, but imports `QueryPlan` from
the kernel. Retrieval no longer owns the request contract.

## Tests

Add boundary tests that fail on the current dependency graph:

- Runtime modules must not import `rag_modules.retrieval` or `rag_modules.query_understanding`.
- Query-understanding modules must not import `rag_modules.retrieval`.
- `rag_modules.contracts` must not import runtime or feature packages.
- The repository must not import `rag_modules.retrieval.contracts`.
- The repository must not import `QueryPlan` or `QuerySemanticProfile` from
  `rag_modules.query_understanding`.

Run focused contract/runtime/query tests first, then expand to public surface and route/retrieval
tests touched by the migration.
