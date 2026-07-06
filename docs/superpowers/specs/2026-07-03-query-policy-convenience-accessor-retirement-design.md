# Query Policy Convenience Accessor Retirement Design

## Goal

Retire the legacy `term_group()` and `regex_group()` convenience methods from both
`QueryPolicyBundle` and `_LazyPolicyBundle`. All callers must access lexical policy through the
owning typed section: `bundle.lexicon.term_group()` or `bundle.lexicon.regex_group()`.

This is a hard internal API retirement. It does not add aliases, forwarding methods, deprecation
warnings, feature flags, or compatibility branches.

## Scope

- Remove `QueryPolicyBundle.term_group()` and `QueryPolicyBundle.regex_group()`.
- Remove `_LazyPolicyBundle.term_group()` and `_LazyPolicyBundle.regex_group()`.
- Migrate every repository caller and test to the typed `lexicon` section.
- Add an AST-based regression test that rejects those methods on both bundle classes.
- Keep `LexiconPolicy.term_group()` and `LexiconPolicy.regex_group()` as the single supported API.

The policy resource schema, loader, runtime bundle selection, dependency injection, and public
FastAPI contracts are unchanged.

## Design

`LexiconPolicy` owns term sets and regular-expression groups, so it remains the only object that
provides lookup methods. `QueryPolicyBundle` is only a typed aggregate of policy sections.
`_LazyPolicyBundle` continues to expose lazy typed section properties for the existing registry
constant, but it no longer duplicates section behavior.

Data flow remains:

1. The loader builds a `QueryPolicyBundle` containing a `LexiconPolicy`.
2. Runtime composition injects that bundle into query-understanding consumers.
3. Consumers select the `lexicon` section explicitly.
4. The lexicon performs named term or regex lookup and preserves the current empty-tuple behavior
   for unknown names.

No fallback is needed because all production consumers already use the typed section path.

## Testing

Implementation follows test-driven development:

1. Add an AST contract test asserting that neither `QueryPolicyBundle` nor `_LazyPolicyBundle`
   defines `term_group()` or `regex_group()` and confirm that it fails against the current code.
2. Migrate existing tests from bundle-level convenience calls to `bundle.lexicon` calls.
3. Remove the four forwarding methods and run the focused query-policy tests.
4. Run the full test suite, Ruff checks, and the offline release gate.

The AST contract is structural rather than source-string based, so formatting or module-local text
cannot produce false positives. It also prevents future reintroduction of the retired API under the
same class names.

## Acceptance Criteria

- No `QueryPolicyBundle.term_group()` or `QueryPolicyBundle.regex_group()` method exists.
- No `_LazyPolicyBundle.term_group()` or `_LazyPolicyBundle.regex_group()` method exists.
- Repository code and tests use `.lexicon.term_group()` and `.lexicon.regex_group()` exclusively.
- No compatibility layer is introduced for the removed methods.
- Focused tests, full pytest, Ruff, and the release gate pass.
