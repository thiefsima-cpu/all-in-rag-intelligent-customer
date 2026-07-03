# Query Policy Convenience Accessor Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove bundle-level lexical lookup conveniences so `LexiconPolicy` is the only owner of `term_group()` and `regex_group()`.

**Architecture:** Add a structural AST contract that rejects the retired methods on both bundle classes, then delete all four forwarding methods. Keep policy loading, lazy section access, and `LexiconPolicy` lookup behavior unchanged; no compatibility aliases or deprecation path are permitted.

**Tech Stack:** Python 3.11, dataclasses, `ast`, unittest/pytest, Ruff, mypy, pre-commit

---

## File Structure

- `tests/test_query_policy.py`: owns the AST contract preventing reintroduction of bundle-level lexical lookup methods.
- `rag_modules/query_policy/models.py`: keeps `QueryPolicyBundle` as a typed aggregate and `LexiconPolicy` as the lexical lookup owner.
- `rag_modules/query_understanding/registry.py`: keeps lazy typed section access without forwarding section methods.
- `docs/superpowers/plans/2026-07-03-query-policy-convenience-accessor-retirement.md`: records this executable plan.

### Task 1: Add The Retired-Method Contract

**Files:**
- Modify: `tests/test_query_policy.py`
- Test: `tests/test_query_policy.py`

- [ ] **Step 1: Add exact model paths and an AST class-method helper**

Add these constants beside the existing package constants:

```python
QUERY_POLICY_MODELS = Path("rag_modules/query_policy/models.py")
QUERY_UNDERSTANDING_REGISTRY = Path("rag_modules/query_understanding/registry.py")
```

Add this helper after `_node_location()`:

```python
def _class_method_names(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one {class_name} in {path}, found {len(matches)}")
    return {
        node.name
        for node in matches[0].body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
```

- [ ] **Step 2: Write the failing structural test**

Add this test to `QueryPolicyTests`:

```python
def test_bundle_types_do_not_expose_lexicon_convenience_methods(self) -> None:
    retired_methods = {"term_group", "regex_group"}

    self.assertTrue(
        retired_methods.isdisjoint(
            _class_method_names(QUERY_POLICY_MODELS, "QueryPolicyBundle")
        )
    )
    self.assertTrue(
        retired_methods.isdisjoint(
            _class_method_names(QUERY_UNDERSTANDING_REGISTRY, "_LazyPolicyBundle")
        )
    )
```

- [ ] **Step 3: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_query_policy.py::QueryPolicyTests::test_bundle_types_do_not_expose_lexicon_convenience_methods -q
```

Expected: FAIL because both classes still define `term_group` and `regex_group`.

### Task 2: Remove The Bundle-Level Methods

**Files:**
- Modify: `rag_modules/query_policy/models.py:315`
- Modify: `rag_modules/query_understanding/registry.py:256`
- Test: `tests/test_query_policy.py`

- [ ] **Step 1: Remove the methods from `QueryPolicyBundle`**

Delete exactly this block from `QueryPolicyBundle`:

```python
def term_group(self, name: str) -> tuple[str, ...]:
    return self.lexicon.term_group(name)

def regex_group(self, name: str) -> tuple[str, ...]:
    return self.lexicon.regex_group(name)
```

Do not replace it with aliases, warnings, dynamic attribute lookup, or forwarding helpers.

- [ ] **Step 2: Remove the methods from `_LazyPolicyBundle`**

Delete exactly this block from `_LazyPolicyBundle`:

```python
def term_group(self, name: str) -> tuple[str, ...]:
    return default_query_registry().policy.term_group(name)

def regex_group(self, name: str) -> tuple[str, ...]:
    return default_query_registry().policy.regex_group(name)
```

Keep the lazy `lexicon` property so callers resolve lexical access as
`POLICY.lexicon.term_group(...)` or `POLICY.lexicon.regex_group(...)`.

- [ ] **Step 3: Run the structural test and verify GREEN**

Run:

```powershell
python -m pytest tests/test_query_policy.py::QueryPolicyTests::test_bundle_types_do_not_expose_lexicon_convenience_methods -q
```

Expected: PASS.

- [ ] **Step 4: Run focused query-policy tests**

Run:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_policy_injection.py -q
```

Expected: all tests pass. Existing lookup tests continue to call the supported
`get_query_policy().lexicon.term_group(...)` path.

### Task 3: Verify The Hard Retirement

**Files:**
- Verify: `rag_modules/query_policy/models.py`
- Verify: `rag_modules/query_understanding/registry.py`
- Verify: `tests/test_query_policy.py`

- [ ] **Step 1: Scan for stale bundle-level calls**

Run:

```powershell
rg -n "\.(term_group|regex_group)\(" rag_modules tests --glob '*.py'
```

Expected: every call resolves through `.lexicon` or a local variable already bound to
`get_query_policy().lexicon`; there are no calls on `POLICY`, `QueryPolicyBundle`, or
`default_query_registry().policy`.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run repository quality hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: Ruff check, Ruff format, and mypy pass. If Ruff modifies a file, inspect the diff and
rerun the hooks until they pass without modifications.

- [ ] **Step 4: Run the release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: the offline release gate passes.

- [ ] **Step 5: Review and commit the implementation**

Run:

```powershell
git diff --check
git diff -- rag_modules/query_policy/models.py rag_modules/query_understanding/registry.py tests/test_query_policy.py docs/superpowers/plans/2026-07-03-query-policy-convenience-accessor-retirement.md
git add rag_modules/query_policy/models.py rag_modules/query_understanding/registry.py tests/test_query_policy.py docs/superpowers/plans/2026-07-03-query-policy-convenience-accessor-retirement.md
git commit -m "refactor: retire query policy convenience accessors"
```

Expected: one focused implementation commit with no unrelated files.
