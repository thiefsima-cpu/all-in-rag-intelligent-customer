# LangChain Document Boundary Design

## Context

The project already has internal document contracts:

- `TextDocument` for build/runtime text chunks.
- `EvidenceDocument` for retrieval and answer grounding.
- runtime DTOs for route, retrieval, answer, and trace state.

Despite that, `langchain_core.documents.Document` still appears in runtime, app, and retrieval
core modules. That makes LangChain a transitive internal data model instead of an external
adapter detail.

## Decision

Remove direct LangChain `Document` imports from all `rag_modules` files except explicit
adapter/compat modules.

Allowed production import locations:

- `rag_modules/contracts/langchain_compat.py`
- `rag_modules/langchain_document_adapter.py`

Everything else uses `TextDocument` or `EvidenceDocument`.

This is a hard boundary change, not a compatibility patch. Runtime and app DTOs do not expose
legacy LangChain `documents` properties. `EvidenceDocument` does not carry `from_langchain()` or
`to_langchain()` methods. Top-level `rag_modules.contracts` does not re-export LangChain conversion
helpers.

## Architecture

`TextDocument` becomes the canonical representation for build/runtime chunks, parent documents,
BM25 corpora, hybrid cache signatures, and constraint matching source documents.

`EvidenceDocument` remains the canonical retrieval result representation. Route strategies,
post-processing, answer models, and tracing pass evidence DTOs directly.

LangChain conversion is explicit and opt-in:

- `contracts.langchain_compat` adapts `EvidenceDocument` to/from LangChain when external callers
  need that shape.
- `langchain_document_adapter` adapts `TextDocument` to/from LangChain for external libraries.

## Implementation Shape

Add a boundary test that scans `rag_modules` for `langchain_core.documents` imports and fails unless
the file is one of the allowed adapter/compat modules.

Refactor runtime/app DTOs:

- remove `documents_input` from `RetrievalOutcome`;
- stop deserializing legacy `documents` payloads;
- remove LangChain `documents` properties from retrieval, answer context, and answer result models.

Refactor retrieval internals:

- BM25 stores and caches `TextDocument`;
- hybrid runtime state and index artifacts use `TextDocument`;
- parent document enrichment uses `TextDocument`;
- constraint matcher scores `TextDocument` and returns `TextDocument`;
- constraint retriever maps matcher results into `EvidenceDocument` without LangChain conversion;
- post processor only exposes evidence-native processing.

Refactor serving composition to initialize traditional retrieval with `TextDocument` chunks.

## Testing Strategy

Use TDD:

1. Add the import-boundary test and run it to see the current violation list.
2. Add or update focused DTO/retrieval tests for the new internal contracts.
3. Implement the smallest production changes that make the focused tests pass.
4. Run targeted runtime/retrieval/routing tests.
5. Run boundary/public-surface tests.

## Acceptance Criteria

- No non-adapter/compat `rag_modules` file imports `langchain_core.documents.Document`.
- Internal runtime/app/retrieval code does not expose legacy LangChain document properties.
- Hybrid retrieval initializes and searches using `TextDocument` internally.
- Constraint matching and BM25 behavior remain stable through internal DTOs.
- Relevant tests pass, and skipped/unavailable checks are reported.
