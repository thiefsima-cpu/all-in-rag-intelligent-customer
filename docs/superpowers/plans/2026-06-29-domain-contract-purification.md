# Domain Contract Purification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `RecipeConstraintMatcher` and all LangChain `Document` constraint-matching behavior out of `domain/shared` and into the retrieval evidence layer without compatibility aliases.

**Architecture:** `domain/shared` keeps pure constraint DTO and parsing logic. `retrieval/evidence` owns `RecipeConstraintMatcher`, including LangChain document scoring, ranking, and metadata enrichment. Retrieval services import the matcher from retrieval; boundary tests prevent LangChain and matcher logic from returning to domain/shared.

**Tech Stack:** Python 3.11, `unittest`, `pytest`, LangChain `Document`, existing `rag_modules.contracts` evidence adapters, Ruff import sorting.

---

## File Structure

- Create: `rag_modules/retrieval/evidence/__init__.py`
  - Exports retrieval-owned evidence helpers for retrieval internals.
- Create: `rag_modules/retrieval/evidence/constraint_matcher.py`
  - Owns `RecipeConstraintMatcher` and all LangChain `Document` matching behavior.
- Create: `tests/test_recipe_constraint_matcher.py`
  - Focused behavior tests for constraint matching after the ownership move.
- Modify: `rag_modules/domain/shared/query_constraints.py`
  - Remove LangChain import and `RecipeConstraintMatcher`; keep pure constraints and parsing.
- Modify: `rag_modules/domain/shared/__init__.py`
  - Remove `RecipeConstraintMatcher` from imports and `__all__`.
- Modify: `rag_modules/retrieval/adapters/constraint_retriever.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `rag_modules/retrieval/hybrid_index_service.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `rag_modules/retrieval/hybrid_runtime_state.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `rag_modules/retrieval/hybrid_runtime.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `rag_modules/retrieval/hybrid_executor.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `rag_modules/retrieval/hybrid_service.py`
  - Import matcher from `rag_modules.retrieval.evidence`.
- Modify: `tests/test_public_surface_boundaries.py`
  - Add domain/shared boundary tests for LangChain imports, matcher exports, and old matcher imports.

---

### Task 1: Add Failing Boundary Tests

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Write the failing boundary tests**

Add these test methods inside `PublicSurfaceBoundaryTests`, near the existing dependency-boundary
tests:

```python
    def test_domain_shared_does_not_import_langchain(self) -> None:
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "domain" / "shared").rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if module_name == "langchain_core" or module_name.startswith("langchain_core."):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Domain shared modules must stay free of LangChain dependencies:\n"
            + "\n".join(violations),
        )

    def test_domain_shared_does_not_export_recipe_constraint_matcher(self) -> None:
        domain_shared = importlib.import_module("rag_modules.domain.shared")

        self.assertFalse(hasattr(domain_shared, "RecipeConstraintMatcher"))
        self.assertNotIn("RecipeConstraintMatcher", getattr(domain_shared, "__all__", ()))

    def test_recipe_constraint_matcher_is_not_imported_from_domain_shared(self) -> None:
        violations: list[str] = []
        old_matcher_import = "rag_modules.domain.shared.query_constraints.RecipeConstraintMatcher"

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                if "__pycache__" in rel.parts:
                    continue
                if path == ROOT / "tests" / "test_public_surface_boundaries.py":
                    continue
                for lineno, line, _module_name, imported_name in self._iter_resolved_imports(path):
                    if imported_name == old_matcher_import:
                        violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "RecipeConstraintMatcher must be imported from rag_modules.retrieval.evidence:\n"
            + "\n".join(violations),
        )
```

- [ ] **Step 2: Run boundary tests to verify they fail for the current code**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: FAIL. The output should report at least:

- `rag_modules/domain/shared/query_constraints.py` importing `langchain_core.documents`;
- `rag_modules.domain.shared` exporting `RecipeConstraintMatcher`;
- retrieval modules importing `RecipeConstraintMatcher` from `domain.shared.query_constraints`.

- [ ] **Step 3: Commit only if this task is implemented separately**

If executing with per-task commits, do not commit this red state by itself. Continue to Task 2 and
commit once the first green implementation exists.

---

### Task 2: Add Failing Matcher Behavior Tests Under Retrieval Coverage

**Files:**
- Create: `tests/test_recipe_constraint_matcher.py`

- [ ] **Step 1: Write tests against the new retrieval evidence import path**

Create `tests/test_recipe_constraint_matcher.py`:

```python
from __future__ import annotations

import unittest

from langchain_core.documents import Document

from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.retrieval.evidence import RecipeConstraintMatcher


class RecipeConstraintMatcherTests(unittest.TestCase):
    def test_filter_and_rank_scores_matching_recipe_terms(self) -> None:
        docs = [
            Document(
                page_content="Mapo tofu with tofu and chili",
                metadata={
                    "recipe_name": "Mapo Tofu",
                    "category": "main",
                    "cuisine_type": "Sichuan",
                    "cook_time": "20 min",
                    "prep_time": "10 min",
                },
            ),
            Document(
                page_content="Plain rice",
                metadata={
                    "recipe_name": "Rice",
                    "category": "staple",
                    "cuisine_type": "Home",
                    "cook_time": "25 min",
                    "prep_time": "5 min",
                },
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                ingredients=["tofu"],
                cuisine_terms=["Sichuan"],
                include_terms=["chili"],
            ),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Mapo Tofu"])
        self.assertGreater(results[0].metadata["constraint_score"], 0)
        self.assertEqual(results[0].metadata["search_type"], "constraint_recipe")
        self.assertTrue(results[0].metadata["constraint_reasons"])
        self.assertEqual(results[0].page_content, "Mapo tofu with tofu and chili")

    def test_filter_and_rank_excludes_blocked_terms_and_cuisine(self) -> None:
        docs = [
            Document(
                page_content="Pork belly with garlic",
                metadata={"recipe_name": "Pork Belly", "cuisine_type": "Sichuan"},
            ),
            Document(
                page_content="Light tofu soup",
                metadata={"recipe_name": "Tofu Soup", "cuisine_type": "Cantonese"},
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                include_terms=["tofu"],
                exclude_terms=["pork"],
                excluded_cuisine_terms=["Sichuan"],
            ),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Tofu Soup"])

    def test_filter_and_rank_applies_time_limits(self) -> None:
        docs = [
            Document(
                page_content="Quick tofu",
                metadata={
                    "recipe_name": "Quick Tofu",
                    "prep_time": "5 min",
                    "cook_time": "10 min",
                },
            ),
            Document(
                page_content="Slow stew tofu",
                metadata={
                    "recipe_name": "Slow Tofu",
                    "prep_time": "20 min",
                    "cook_time": "60 min",
                },
            ),
        ]
        matcher = RecipeConstraintMatcher(docs)

        results = matcher.filter_and_rank(
            QueryConstraints(
                include_terms=["tofu"],
                max_total_minutes=30,
                max_prep_minutes=10,
                max_cook_minutes=20,
            ),
            limit=5,
        )

        self.assertEqual([doc.metadata["recipe_name"] for doc in results], ["Quick Tofu"])
        self.assertIn("constraint_score", results[0].metadata)
        self.assertIn("constraint_reasons", results[0].metadata)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run matcher tests to verify the new import path fails**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py -q
```

Expected: FAIL with an import error because `rag_modules.retrieval.evidence` does not exist yet.

---

### Task 3: Create Retrieval Evidence Matcher

**Files:**
- Create: `rag_modules/retrieval/evidence/__init__.py`
- Create: `rag_modules/retrieval/evidence/constraint_matcher.py`

- [ ] **Step 1: Create retrieval evidence package export**

Create `rag_modules/retrieval/evidence/__init__.py`:

```python
"""Retrieval-owned evidence helpers."""

from .constraint_matcher import RecipeConstraintMatcher

__all__ = ["RecipeConstraintMatcher"]
```

- [ ] **Step 2: Move matcher implementation into retrieval evidence**

Create `rag_modules/retrieval/evidence/constraint_matcher.py`. The Unicode escape sequences below
preserve the existing Chinese reason strings while keeping the plan ASCII-safe:

```python
"""Constraint matching over retrieval evidence documents."""

from __future__ import annotations

from typing import List, Optional, Tuple

from langchain_core.documents import Document

from ...domain.shared.query_constraints import QueryConstraints, parse_minutes


class RecipeConstraintMatcher:
    def __init__(self, documents: List[Document]):
        self.documents = documents

    @staticmethod
    def _haystack(doc: Document) -> str:
        metadata = doc.metadata or {}
        pieces = [
            doc.page_content or "",
            str(metadata.get("recipe_name", "")),
            str(metadata.get("category", "")),
            str(metadata.get("cuisine_type", "")),
            str(metadata.get("prep_time", "")),
            str(metadata.get("cook_time", "")),
            str(metadata.get("servings", "")),
            " ".join(metadata.get("flavor_tags") or []),
            " ".join(metadata.get("technique_tags") or []),
            " ".join(metadata.get("diet_tags") or []),
            " ".join(metadata.get("health_tags") or []),
            " ".join(metadata.get("cuisine_style_tags") or []),
            " ".join(metadata.get("ingredient_category_tags") or []),
            " ".join(metadata.get("time_profile_tags") or []),
            " ".join(metadata.get("difficulty_level_tags") or []),
            str(metadata.get("semantic_relations", "")),
        ]
        return "\n".join(pieces)

    @staticmethod
    def _contains_any(haystack: str, terms: List[str]) -> bool:
        return any(term and term in haystack for term in terms)

    @staticmethod
    def _contains_all(haystack: str, terms: List[str]) -> bool:
        return all(term in haystack for term in terms if term)

    @staticmethod
    def _recipe_minutes(
        doc: Document,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]]:
        metadata = doc.metadata or {}
        prep = parse_minutes(metadata.get("prep_time"))
        cook = parse_minutes(metadata.get("cook_time"))
        total = None
        if prep is not None and cook is not None:
            total = prep + cook
        return prep, cook, total

    def score(
        self,
        doc: Document,
        constraints: QueryConstraints,
    ) -> Tuple[bool, float, List[str]]:
        if not constraints or not constraints.has_constraints():
            return True, 0.0, []

        text = self._haystack(doc)
        metadata = doc.metadata or {}
        cuisine = str(metadata.get("cuisine_type", ""))
        category = str(metadata.get("category", ""))
        prep, cook, total = self._recipe_minutes(doc)

        if self._contains_any(
            text,
            constraints.exclude_terms + constraints.excluded_ingredients,
        ):
            return False, 0.0, ["\u547d\u4e2d\u6392\u9664\u8bcd"]
        if constraints.excluded_cuisine_terms and self._contains_any(
            cuisine,
            constraints.excluded_cuisine_terms,
        ):
            return False, 0.0, ["\u547d\u4e2d\u6392\u9664\u83dc\u7cfb"]
        if (
            constraints.max_prep_minutes is not None
            and prep is not None
            and prep > constraints.max_prep_minutes
        ):
            return False, 0.0, ["\u51c6\u5907\u65f6\u95f4\u8d85\u9650"]
        if (
            constraints.max_cook_minutes is not None
            and cook is not None
            and cook > constraints.max_cook_minutes
        ):
            return False, 0.0, ["\u70f9\u996a\u65f6\u95f4\u8d85\u9650"]
        if (
            constraints.max_total_minutes is not None
            and total is not None
            and total > constraints.max_total_minutes
        ):
            return False, 0.0, ["\u603b\u65f6\u95f4\u8d85\u9650"]

        score = 0.0
        reasons: List[str] = []
        weighted_terms = [
            (constraints.ingredients, 3.0, "\u98df\u6750\u5339\u914d"),
            (constraints.cuisine_terms, 2.5, "\u83dc\u7cfb\u5339\u914d"),
            (constraints.category_terms, 2.0, "\u7c7b\u522b\u5339\u914d"),
            (constraints.include_terms, 1.5, "\u4e3b\u9898\u5339\u914d"),
            (constraints.health_terms, 1.5, "\u5065\u5eb7\u504f\u597d\u5339\u914d"),
            (constraints.preference_terms, 1.0, "\u504f\u597d\u5339\u914d"),
        ]
        for terms, weight, label in weighted_terms:
            hits = [term for term in terms if term in text]
            if hits:
                score += weight * len(hits)
                reasons.append(f"{label}: {', '.join(hits[:4])}")

        if constraints.cuisine_terms and self._contains_any(
            cuisine,
            constraints.cuisine_terms,
        ):
            score += 1.0
        if constraints.category_terms and self._contains_any(
            category,
            constraints.category_terms,
        ):
            score += 1.0
        if constraints.max_total_minutes is not None:
            if total is not None:
                score += 2.0
                reasons.append(f"\u65f6\u95f4\u7ea6\u675f\u547d\u4e2d: {total}\u5206\u949f")
            else:
                score -= 0.5
                reasons.append("\u65f6\u95f4\u4fe1\u606f\u4e0d\u5b8c\u6574")

        return True, score, reasons

    def filter_and_rank(
        self,
        constraints: QueryConstraints,
        min_score: float = 0.0,
        limit: int = 20,
    ) -> List[Document]:
        scored = []
        for doc in self.documents:
            keep, score, reasons = self.score(doc, constraints)
            if not keep or score < min_score:
                continue
            metadata = dict(doc.metadata)
            metadata["constraint_score"] = score
            metadata["constraint_reasons"] = reasons
            metadata["search_type"] = metadata.get(
                "search_type",
                "constraint_recipe",
            )
            scored.append(Document(page_content=doc.page_content, metadata=metadata))

        scored.sort(
            key=lambda d: d.metadata.get("constraint_score", 0.0),
            reverse=True,
        )
        return scored[:limit]
```

- [ ] **Step 3: Run matcher tests to verify the new module behavior**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py -q
```

Expected: PASS for all matcher behavior tests.

---

### Task 4: Remove Matcher and LangChain From Domain Shared

**Files:**
- Modify: `rag_modules/domain/shared/query_constraints.py`
- Modify: `rag_modules/domain/shared/__init__.py`

- [ ] **Step 1: Remove domain/shared LangChain import and matcher class**

In `rag_modules/domain/shared/query_constraints.py`, change the module docstring and imports:

```python
"""
Generic query constraint extraction helpers.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional
```

Delete the full `RecipeConstraintMatcher` class from this file. The last class in the file should
be `QueryConstraintExtractor`.

- [ ] **Step 2: Remove matcher from domain package exports**

In `rag_modules/domain/shared/__init__.py`, use this query constraints import block:

```python
from .query_constraints import (
    QueryConstraintExtractor,
    QueryConstraints,
    parse_minutes,
)
```

Use this `__all__` fragment:

```python
__all__ = [
    "QueryConstraintExtractor",
    "QueryConstraints",
    "SEMANTIC_NODE_LABELS",
    "SEMANTIC_NODE_LABELS_SET",
    "SEMANTIC_RELATION_TYPES",
    "SEMANTIC_SCHEMA_VERSION",
    "infer_recipe_semantics",
    "parse_minutes",
]
```

- [ ] **Step 3: Run boundary tests to verify remaining failures are only old imports**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: FAIL only for production modules still importing `RecipeConstraintMatcher` from
`rag_modules.domain.shared.query_constraints`.

---

### Task 5: Move Retrieval Imports to the New Matcher Owner

**Files:**
- Modify: `rag_modules/retrieval/adapters/constraint_retriever.py`
- Modify: `rag_modules/retrieval/hybrid_index_service.py`
- Modify: `rag_modules/retrieval/hybrid_runtime_state.py`
- Modify: `rag_modules/retrieval/hybrid_runtime.py`
- Modify: `rag_modules/retrieval/hybrid_executor.py`
- Modify: `rag_modules/retrieval/hybrid_service.py`

- [ ] **Step 1: Update each retrieval import**

Replace:

```python
from ..domain.shared.query_constraints import RecipeConstraintMatcher
```

or:

```python
from ..domain.shared.query_constraints import QueryConstraints, RecipeConstraintMatcher
```

or:

```python
from ...domain.shared.query_constraints import RecipeConstraintMatcher
```

with the correct split imports for each file.

For `rag_modules/retrieval/adapters/constraint_retriever.py`:

```python
from ...contracts import EvidenceDocument, RetrievalRequest, from_langchain_documents
from ..evidence import RecipeConstraintMatcher
```

For `rag_modules/retrieval/hybrid_index_service.py`:

```python
from ..parent_doc_enricher import ParentDocumentEnricher
from ..retrieval_cache import RetrievalCacheStore
from ..safe_logging import log_failure
from .adapters import BM25Retriever
from .evidence import RecipeConstraintMatcher
```

For `rag_modules/retrieval/hybrid_runtime_state.py`:

```python
from ..runtime_contracts import Neo4jDriverPort
from .adapters import VectorRetriever
from .dual_level_retriever import DualLevelRetriever
from .evidence import RecipeConstraintMatcher
```

For `rag_modules/retrieval/hybrid_runtime.py`:

```python
from ..contracts import EvidenceDocument, RetrievalRequest
from ..graph_index import GraphIndexingModule
from ..parent_doc_enricher import ParentDocumentEnricher
from ..runtime_contracts import Neo4jDriverPort, Neo4jManagerPort, VectorIndexModulePort
from .adapters import BM25Retriever, GraphKVRetriever, VectorRetriever
from .dual_level_retriever import DualLevelRetriever
from .evidence import RecipeConstraintMatcher
```

For `rag_modules/retrieval/hybrid_executor.py`:

```python
from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ..domain.shared.query_constraints import QueryConstraints
from .evidence import RecipeConstraintMatcher
```

For `rag_modules/retrieval/hybrid_service.py`:

```python
from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest, to_langchain_documents
from ..domain.shared.query_constraints import QueryConstraints
from .evidence import RecipeConstraintMatcher
```

- [ ] **Step 2: Search for old matcher imports**

Run:

```powershell
rg -n "RecipeConstraintMatcher" rag_modules tests
```

Expected: results include the new retrieval evidence module, retrieval imports from
`rag_modules.retrieval.evidence`, behavior tests, and boundary tests. There should be no production
import of `RecipeConstraintMatcher` from `rag_modules.domain.shared.query_constraints`.

- [ ] **Step 3: Run boundary tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: PASS.

---

### Task 6: Run Focused Retrieval Verification

**Files:**
- No new edits expected.

- [ ] **Step 1: Run matcher and retrieval runtime tests**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py tests/test_hybrid_retrieval_runtime.py tests/test_hybrid_retrieval_executor.py -q
```

Expected: PASS.

- [ ] **Step 2: Run retrieval candidate and search tests touched by imports**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_retrieval_service_factories.py -q
```

Expected: PASS.

- [ ] **Step 3: Run import grep for forbidden old owner**

Run:

```powershell
rg -n "from .*domain\\.shared\\.query_constraints import .*RecipeConstraintMatcher|langchain_core" rag_modules\\domain\\shared rag_modules\\retrieval tests
```

Expected: no `RecipeConstraintMatcher` import from `domain.shared.query_constraints`. `langchain_core`
matches are allowed in retrieval and tests, but not under `rag_modules/domain/shared`.

---

### Task 7: Format, Final Boundary Verification, and Commit

**Files:**
- Modified and created files from Tasks 1-5.

- [ ] **Step 1: Run Ruff on touched Python files**

Run:

```powershell
python -m ruff check rag_modules/domain/shared/query_constraints.py rag_modules/domain/shared/__init__.py rag_modules/retrieval/evidence rag_modules/retrieval/adapters/constraint_retriever.py rag_modules/retrieval/hybrid_index_service.py rag_modules/retrieval/hybrid_runtime_state.py rag_modules/retrieval/hybrid_runtime.py rag_modules/retrieval/hybrid_executor.py rag_modules/retrieval/hybrid_service.py tests/test_public_surface_boundaries.py tests/test_recipe_constraint_matcher.py
```

Expected: PASS or auto-fix suggestions. If Ruff reports import sorting issues, run the suggested
Ruff fix command and re-run this step.

- [ ] **Step 2: Run public-surface boundary tests again**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

Expected: PASS.

- [ ] **Step 3: Run focused retrieval tests again**

Run:

```powershell
python -m pytest tests/test_recipe_constraint_matcher.py tests/test_hybrid_retrieval_runtime.py tests/test_hybrid_retrieval_executor.py tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_retrieval_service_factories.py -q
```

Expected: PASS.

- [ ] **Step 4: Review diff**

Run:

```powershell
git diff --stat
git diff -- rag_modules/domain/shared/query_constraints.py rag_modules/retrieval/evidence/constraint_matcher.py tests/test_recipe_constraint_matcher.py tests/test_public_surface_boundaries.py
```

Expected: diff shows matcher relocation, domain cleanup, import updates, and tests only.

- [ ] **Step 5: Commit implementation**

Run:

```powershell
git add rag_modules/domain/shared/query_constraints.py rag_modules/domain/shared/__init__.py rag_modules/retrieval/evidence/__init__.py rag_modules/retrieval/evidence/constraint_matcher.py rag_modules/retrieval/adapters/constraint_retriever.py rag_modules/retrieval/hybrid_index_service.py rag_modules/retrieval/hybrid_runtime_state.py rag_modules/retrieval/hybrid_runtime.py rag_modules/retrieval/hybrid_executor.py rag_modules/retrieval/hybrid_service.py tests/test_public_surface_boundaries.py tests/test_recipe_constraint_matcher.py
git commit -m "refactor: move constraint matcher to retrieval evidence"
```

Expected: commit succeeds. If hooks modify files, inspect `git diff`, re-run verification commands,
stage hook changes, and amend or create the commit only after verification is fresh.
