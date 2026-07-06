# Config Schema Validation Design

## Goal

Make configuration loading schema-first and fail-fast so profile, environment,
and explicit override errors point to the exact setting that needs attention.

The current dataclass plus loader structure works, but validation is split
across section loaders, ad hoc casts, dataclass constructors, and a few runtime
post-init checks. That makes errors inconsistent. Some invalid values raise
plain Python conversion errors, some unknown profile fields raise a generic
override error, and some malformed environment values, such as JSON mapping
overrides, can silently fall back to defaults.

This change replaces that scattered behavior with one authoritative Pydantic
schema and one configuration resolution pipeline.

## Scope

In scope:

- `rag_modules/configuration/` models, loaders, profile merge behavior, and
  environment parsing.
- Public configuration APIs such as `load_config`, `GraphRAGConfig`,
  section class names, `to_dict`, `to_domain_dict`, `with_overrides`, and
  `GraphRAGConfig.from_dict`.
- Focused configuration tests and any docs that describe configuration errors
  or runtime profile behavior.

Out of scope:

- Retrieval, graph, generation, API, and build runtime behavior except where
  they consume configuration objects.
- Adding `pydantic-settings` or any new runtime dependency. `pydantic` is
  already a runtime dependency and is enough for the desired behavior.
- Broad public API renames or mass downstream refactors.

## Recommended Approach

Use Pydantic models as the single source of truth for configuration shape,
types, defaults, and cross-field rules.

The runtime configuration classes should keep their existing public names:

- `GraphRAGConfig`
- `StorageSettings`
- `ModelSettings`
- `RetrievalSettings`
- `QueryUnderstandingSettings`
- `GenerationSettings`
- `GraphSettings`
- `ObservabilitySettings`
- `ApiSettings`

Those classes should become Pydantic `BaseModel` subclasses instead of
dataclasses. They should keep compatibility methods that real callers use,
especially `to_dict`, `to_domain_dict`, `with_overrides`, and
`GraphRAGConfig.from_dict`.

Set `extra="forbid"` on all configuration models so unknown profile and
override fields are rejected by the schema, not filtered or ignored.

## Resolution Pipeline

Build configuration in this order:

1. Start from schema defaults by constructing the default Pydantic config.
2. Load `profiles/base.toml` when present.
3. Load the selected named profile or explicit profile path.
4. Merge profile values into the default domain payload.
5. Convert environment variables into a nested override payload using an
   explicit mapping from env var name to config field path.
6. Merge environment overrides over profile values.
7. Merge explicit `overrides` over environment values.
8. Validate the final payload through `GraphRAGConfig`.

This keeps existing precedence:

- Defaults are lowest precedence.
- Profile values override defaults.
- Environment values override profiles.
- Explicit `overrides` passed to `load_config` or `with_overrides` override
  everything else.

## Environment Mapping

Environment parsing should be explicit and schema-aware. Each supported env var
maps to a dotted config field path, for example:

- `TOP_K` -> `retrieval.top_k`
- `API_MAX_REQUEST_BODY_BYTES` -> `api.max_request_body_bytes`
- `ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES` ->
  `graph.entity_linker_query_type_label_priorities`

The parser should convert raw strings according to the target field type:

- `int` and `float` values must parse successfully.
- `bool` values should accept the current true tokens and false tokens, but
  unknown tokens should fail instead of becoming `False`.
- JSON mapping fields must parse as JSON objects with the expected value shape.
- Empty env values should continue to mean "not set" so existing `.env`
  templates stay ergonomic.

Malformed env values should raise a configuration validation error that names
the env var and the target field path.

## Profile Validation

Profile TOML should validate against the same schema as environment and
explicit overrides.

Required behavior:

- Unknown section names fail.
- Unknown nested fields fail.
- Wrong scalar types fail.
- Nested tables where a scalar is expected fail.
- Scalars where a nested table is expected fail.
- Errors should include the profile file path when available and the dotted
  field path.

The existing base-plus-selected-profile merge behavior should remain, but the
result must be schema-validated before constructing runtime config.

## Error Model

Add a small configuration-specific exception type, for example
`ConfigurationError`, to present validation failures consistently. It should
wrap Pydantic validation errors and parser errors without forcing callers to
depend on Pydantic internals.

A useful error message should include:

- Source kind: `profile`, `environment`, or `overrides`.
- Source detail: profile path, env var name, or override call site context.
- Field path: `retrieval.top_k`, `models.embedding_dimension`, etc.
- Short reason: expected type, unknown field, invalid JSON, invalid boolean,
  or failed cross-field constraint.

The message can be plain text. Structured error details can be exposed later if
needed, but this design should leave room for them by storing a list of error
records on the exception.

## Cross-Field Rules

Move current root-level invariants into the Pydantic schema:

- `storage.milvus_dimension` must either be unset/zero-compatible or match
  `models.embedding_dimension`.
- Final `storage.milvus_dimension` should equal `models.embedding_dimension`.
- Default derived paths should still be filled:
  - `storage.artifact_manifest_path`
  - `storage.build_job_store_path`

Derived paths should remain deterministic when `storage.index_cache_dir` is
overridden by profile, env, or explicit overrides.

## Compatibility Boundary

This is not a compatibility patch, but the public configuration boundary should
stay stable unless there is a strong reason to break it.

Keep:

- Existing class names and import locations.
- Attribute access such as `config.retrieval.top_k`.
- Serialization masking for secrets in `to_dict`.
- `GraphRAGConfig.from_dict` ignoring ambient environment.
- `get_default_config` lazy loading behavior.
- Public profile helper exports.

Remove or replace:

- Ad hoc `EnvConfigSource.get_int`, `get_float`, and `get_json_dict` behavior
  that produces uncontextualized errors or silently falls back to defaults.
- Section loader casts that validate each field differently.
- Dataclass-only construction paths that bypass schema validation.

## Testing

Use TDD for the implementation. Start with focused failing tests before
changing production code.

Add or update tests for:

- Invalid env int reports env var and field path.
- Invalid env bool token reports env var and field path.
- Invalid env JSON mapping reports env var and field path.
- Profile unknown top-level section reports profile path and field path.
- Profile unknown nested field reports profile path and field path.
- Profile wrong scalar type reports profile path and field path.
- Profile scalar where nested table is expected reports profile path and field
  path.
- Environment overrides profile values.
- Explicit overrides preserve profile metadata.
- `GraphRAGConfig.from_dict` ignores ambient environment.
- Secret masking remains unchanged.
- `storage.milvus_dimension` and `models.embedding_dimension` mismatch reports
  both relevant fields.

Run the narrow configuration tests first:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py -q
```

Then expand to public surface and entrypoint tests because config classes are
imported broadly:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py tests/test_entrypoints.py -q
```

Before claiming completion, run the project hook or equivalent Ruff check. For
release-sensitive follow-up, run:

```powershell
python scripts/release_gate.py
```

## Acceptance Criteria

- All configuration values are validated by one Pydantic schema.
- Invalid profile values fail with precise source and dotted field paths.
- Invalid env values fail with precise env var names and dotted field paths.
- Malformed env JSON no longer silently falls back to defaults.
- Unknown profile and override fields fail through schema validation.
- Existing public configuration imports and common attribute access keep
  working.
- Existing profile precedence and metadata behavior keep working.
- Focused configuration tests pass, followed by the broader boundary tests
  listed above.
