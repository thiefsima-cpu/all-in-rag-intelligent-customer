# Domain Contract Purification Design

## Context

`rag_modules.domain.shared.query_constraints` currently mixes two responsibilities:

- pure query constraint parsing and DTO behavior;
- recipe evidence filtering over LangChain `Document` objects.

That second responsibility pulls `langchain_core.documents.Document` into the domain layer and
exports `RecipeConstraintMatcher` from `rag_modules.domain.shared`. The retrieval package is already
the only runtime owner of constraint matching, so keeping the matcher in domain/shared blurs the
contract boundary and makes future evidence-layer work harder to reason about.

This slice makes the boundary explicit and removes the compatibility path instead of adding a shim.

## Decision

Move `RecipeConstraintMatcher` out of `rag_modules.domain.shared` and into the retrieval evidence
layer. The new owner should be a retrieval module such as
`rag_modules.retrieval.evidence.constraint_matcher`.

`rag_modules.domain.shared` remains the canonical home for pure constraint primitives only:

- `QueryConstraints`
- `QueryConstraintExtractor`
- `loads_json_object`
- `parse_minutes`

There is no deprecated alias, no re-export, and no temporary import bridge for
`RecipeConstraintMatcher`.

## Architecture

The allowed dependency direction for this slice is:

`retrieval -> domain.shared`

`domain.shared` must not import retrieval, contracts, LangChain, or other evidence/runtime
implementations. It may keep standard-library parsing and the existing query-understanding call used
by `QueryConstraintExtractor`.

The retrieval evidence layer owns all LangChain `Document` behavior for constraint matching:

- constructing haystacks from `page_content` and metadata;
- parsing recipe prep/cook/total times from document metadata;
- scoring constraints against documents;
- returning ranked LangChain documents with `constraint_score`, `constraint_reasons`, and
  `constraint_recipe` metadata.

`ConstraintRetriever` remains the adapter from the matcher into `EvidenceDocument` retrieval
contracts. It should import the matcher from retrieval, not domain.

## Implementation Shape

Create `rag_modules/retrieval/evidence/constraint_matcher.py` with the existing matcher behavior.
Add `rag_modules/retrieval/evidence/__init__.py` only if a package export is useful for retrieval
internals.

Update retrieval consumers to import the matcher from the new module:

- `rag_modules.retrieval.hybrid_index_service`
- `rag_modules.retrieval.hybrid_runtime_state`
- `rag_modules.retrieval.hybrid_runtime`
- `rag_modules.retrieval.hybrid_executor`
- `rag_modules.retrieval.hybrid_service`
- `rag_modules.retrieval.adapters.constraint_retriever`

Remove `RecipeConstraintMatcher` from:

- `rag_modules.domain.shared.query_constraints`
- `rag_modules.domain.shared.__init__.__all__`

Do not add a root facade, compatibility re-export, or fallback import.

## Testing Strategy

Use TDD with a boundary test first:

- `rag_modules.domain.shared` and its modules must not import `langchain_core`.
- `rag_modules.domain.shared` must not export `RecipeConstraintMatcher`.
- production code must not import `RecipeConstraintMatcher` from
  `rag_modules.domain.shared.query_constraints`.

Then add or move focused matcher behavior tests under retrieval coverage:

- include-term and ingredient matches produce ranked documents;
- excluded terms and excluded cuisine terms filter documents out;
- prep/cook/total time limits preserve the current behavior;
- returned documents keep original content and add constraint metadata.

Run the narrow tests first:

- matcher/boundary tests;
- `tests/test_hybrid_retrieval_runtime.py`;
- `tests/test_hybrid_retrieval_executor.py`;
- retrieval candidate/search tests touched by imports.

Before completion, run the public-surface boundary tests. If the change stays import-only plus
matcher relocation, full release gate is optional unless narrower verification exposes a broader
contract issue.

## Acceptance Criteria

- `rag_modules.domain.shared.query_constraints` has no LangChain import.
- `RecipeConstraintMatcher` lives only under `rag_modules.retrieval`.
- No compatibility alias or deprecated export exists for the old matcher path.
- Existing constraint retrieval behavior remains stable.
- Boundary tests fail if LangChain or matcher logic returns to domain/shared.
- Relevant retrieval/runtime tests pass.

## Risks

Removing the old export is intentionally breaking for any untracked internal or external consumer.
That is acceptable for this priority because the goal is a clean domain/contract boundary, not a
compatibility window.

The matcher still operates on LangChain `Document` objects after the move. That is acceptable because
the evidence/retrieval layer is the current owner of LangChain compatibility in this repository.
