# API Security Policy Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make docs, OpenAPI, and metrics exposure configurable with enterprise-safe production defaults and explicit development opt-in.

**Architecture:** Add explicit API and observability configuration fields, then have the FastAPI app factories register docs/OpenAPI routes based on those fields. The security middleware will derive public management paths from settings instead of a fixed public-path constant.

**Tech Stack:** Python 3.11, dataclasses, FastAPI, pytest/unittest, TOML profiles.

---

## File Structure

- Modify `rag_modules/configuration/models.py`
  - Add `ApiSettings.docs_enabled`, `openapi_enabled`, `docs_public`,
    `openapi_public`.
  - Add `ObservabilitySettings.prometheus_public`.
- Modify `rag_modules/configuration/sections/api.py`
  - Load `API_DOCS_ENABLED`, `API_OPENAPI_ENABLED`, `API_DOCS_PUBLIC`,
    `API_OPENAPI_PUBLIC`.
- Modify `rag_modules/configuration/sections/observability.py`
  - Load `PROMETHEUS_METRICS_PUBLIC`.
- Modify `rag_modules/interfaces/api/security.py`
  - Replace fixed management public paths with a computed policy.
  - Make OpenAPI operation-level security clearing use the computed public paths.
- Modify `rag_modules/interfaces/api/app.py`
  - Resolve API settings before creating `FastAPI`.
  - Disable docs/OpenAPI routes when configured off.
  - Pass observability settings to the security middleware.
- Modify `profiles/base.toml`
  - Keep production-safe defaults explicit.
- Modify `profiles/dev.toml`
  - Opt into local docs/OpenAPI and public metrics.
- Modify `.env.example`
  - Document the new environment toggles.
- Modify `docs/observability.md`
  - Document metrics registration versus public access.
- Modify `tests/test_configuration_section_loaders.py`
  - Cover new env-backed configuration fields.
- Modify `tests/test_api_app.py`
  - Cover docs/OpenAPI disabled, protected, public, and metrics protected/public/disabled behavior.

---

### Task 1: Configuration Fields

**Files:**
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/sections/api.py`
- Modify: `rag_modules/configuration/sections/observability.py`

- [x] **Step 1: Write the failing configuration loader test**

Add assertions to `ConfigurationSectionLoaderTests.test_api_settings_respect_environment_overrides`:

```python
"API_DOCS_ENABLED": "true",
"API_OPENAPI_ENABLED": "true",
"API_DOCS_PUBLIC": "true",
"API_OPENAPI_PUBLIC": "true",
```

and:

```python
self.assertTrue(config.api.docs_enabled)
self.assertTrue(config.api.openapi_enabled)
self.assertTrue(config.api.docs_public)
self.assertTrue(config.api.openapi_public)
```

Add `"PROMETHEUS_METRICS_PUBLIC": "true"` to
`test_observability_settings_respect_environment_overrides` and assert:

```python
self.assertTrue(config.observability.prometheus_public)
```

- [x] **Step 2: Run the failing configuration test**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because `ApiSettings` and `ObservabilitySettings` do not expose the new fields.

- [x] **Step 3: Implement configuration model and loader fields**

Update `ApiSettings`:

```python
docs_enabled: bool = False
openapi_enabled: bool = False
docs_public: bool = False
openapi_public: bool = False
```

Update `ObservabilitySettings`:

```python
prometheus_public: bool = False
```

Update `load_api_settings(...)` to read:

```python
docs_enabled=source.get_bool(
    "API_DOCS_ENABLED",
    bool(api_defaults.get("docs_enabled", False)),
),
openapi_enabled=source.get_bool(
    "API_OPENAPI_ENABLED",
    bool(api_defaults.get("openapi_enabled", False)),
),
docs_public=source.get_bool(
    "API_DOCS_PUBLIC",
    bool(api_defaults.get("docs_public", False)),
),
openapi_public=source.get_bool(
    "API_OPENAPI_PUBLIC",
    bool(api_defaults.get("openapi_public", False)),
),
```

Update `load_observability_settings(...)` to read:

```python
prometheus_public=source.get_bool(
    "PROMETHEUS_METRICS_PUBLIC",
    bool(observability_defaults.get("prometheus_public", False)),
),
```

- [x] **Step 4: Run the configuration test again**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

---

### Task 2: Docs And OpenAPI Registration Policy

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Modify: `rag_modules/interfaces/api/security.py`

- [x] **Step 1: Write failing API docs/OpenAPI tests**

Add focused tests to `ApiAppTests`:

```python
def test_docs_and_openapi_are_disabled_by_default(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        redoc_response = client.get("/redoc")
        openapi_response = client.get("/openapi.json")

    self.assertEqual(docs_response.status_code, 404)
    self.assertEqual(redoc_response.status_code, 404)
    self.assertEqual(openapi_response.status_code, 404)
```

```python
def test_enabled_docs_and_openapi_require_credentials_by_default(self) -> None:
    config = build_test_config(
        {
            "api": {
                "access_token": _API_TOKEN,
                "docs_enabled": True,
                "openapi_enabled": True,
            }
        }
    )
    app = create_serving_api_app(system=_FakeApiSystem(), config=config)

    with TestClient(app) as anonymous:
        docs_unauthorized = anonymous.get("/docs")
        openapi_unauthorized = anonymous.get("/openapi.json")
    with _client(app) as authenticated:
        docs_authorized = authenticated.get("/docs")
        openapi_authorized = authenticated.get("/openapi.json")

    self.assertEqual(docs_unauthorized.status_code, 401)
    self.assertEqual(openapi_unauthorized.status_code, 401)
    self.assertEqual(docs_authorized.status_code, 200)
    self.assertEqual(openapi_authorized.status_code, 200)
```

```python
def test_docs_and_openapi_can_be_made_public(self) -> None:
    config = build_test_config(
        {
            "api": {
                "access_token": _API_TOKEN,
                "docs_enabled": True,
                "openapi_enabled": True,
                "docs_public": True,
                "openapi_public": True,
            }
        }
    )
    app = create_serving_api_app(system=_FakeApiSystem(), config=config)

    with TestClient(app) as client:
        docs_response = client.get("/docs")
        openapi_response = client.get("/openapi.json")

    self.assertEqual(docs_response.status_code, 200)
    self.assertEqual(openapi_response.status_code, 200)
```

- [x] **Step 2: Run the failing API docs/OpenAPI tests**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: FAIL because docs and OpenAPI are currently registered and public.

- [x] **Step 3: Implement docs/OpenAPI registration settings**

Change `_resolve_api_settings(...)` usage so settings are available before
constructing each `FastAPI` app. Pass:

```python
docs_url="/docs" if api_settings.docs_enabled else None
redoc_url="/redoc" if api_settings.docs_enabled else None
openapi_url="/openapi.json" if api_settings.openapi_enabled else None
```

to both app factories.

Add a public-path helper in `security.py`:

```python
_BASE_PUBLIC_PATHS = frozenset({"/", "/health", "/health/live", "/health/ready"})
_DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc"})


def public_paths_for_settings(*, api_settings: ApiSettings, observability_settings=None):
    paths = set(_BASE_PUBLIC_PATHS)
    if api_settings.docs_public:
        paths.update(_DOCS_PATHS)
    if api_settings.openapi_public:
        paths.add("/openapi.json")
    if bool(getattr(observability_settings, "prometheus_public", False)):
        paths.add("/metrics")
    return frozenset(paths)
```

Use this helper in `ApiSecurityMiddleware.__init__` and in
`configure_openapi_security(...)`.

- [x] **Step 4: Run the API docs/OpenAPI tests again**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: docs/OpenAPI tests pass. Existing OpenAPI schema tests may need their
test config updated to enable OpenAPI explicitly.

---

### Task 3: Metrics Access Policy

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `rag_modules/interfaces/api/app.py`
- Modify: `rag_modules/interfaces/api/security.py`

- [x] **Step 1: Write failing metrics policy tests**

Replace `test_prometheus_metrics_endpoint_is_public` with:

```python
def test_prometheus_metrics_endpoint_requires_credentials_by_default(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

    with TestClient(app) as anonymous:
        unauthorized = anonymous.get("/metrics")
    with _client(app) as authenticated:
        authorized = authenticated.get("/metrics")

    self.assertEqual(unauthorized.status_code, 401)
    self.assertEqual(authorized.status_code, 200)
    self.assertIn("graphrag_queries_total", authorized.text)
    self.assertTrue(authorized.headers["content-type"].startswith("text/plain"))
```

Add:

```python
def test_prometheus_metrics_endpoint_can_be_made_public(self) -> None:
    config = build_test_config(
        {
            "api": {"access_token": _API_TOKEN},
            "observability": {"prometheus_public": True},
        }
    )
    app = create_serving_api_app(system=_FakeApiSystem(), config=config)

    with TestClient(app) as client:
        response = client.get("/metrics")

    self.assertEqual(response.status_code, 200)
    self.assertIn("graphrag_queries_total", response.text)
```

Add:

```python
def test_prometheus_metrics_endpoint_can_be_disabled(self) -> None:
    config = build_test_config(
        {
            "api": {"access_token": _API_TOKEN},
            "observability": {"enable_prometheus": False},
        }
    )
    app = create_serving_api_app(system=_FakeApiSystem(), config=config)

    with _client(app) as client:
        response = client.get("/metrics")

    self.assertEqual(response.status_code, 404)
```

- [x] **Step 2: Run the failing metrics tests**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: FAIL because `/metrics` is currently always public when registered.

- [x] **Step 3: Wire observability settings into the middleware**

Resolve observability settings in each app factory and pass them to
`ApiSecurityMiddleware`:

```python
observability_settings = getattr(resolved_config, "observability", None)
app.add_middleware(
    ApiSecurityMiddleware,
    settings=api_settings,
    observability_settings=observability_settings,
)
```

Keep `_register_metrics_endpoint(...)` controlled by
`observability.enable_prometheus`.

- [x] **Step 4: Run the API test file again**

Run:

```powershell
python -m pytest tests/test_api_app.py -q
```

Expected: PASS.

---

### Task 4: Profiles And Docs

**Files:**
- Modify: `profiles/base.toml`
- Modify: `profiles/dev.toml`
- Modify: `.env.example`
- Modify: `docs/observability.md`

- [x] **Step 1: Write profile/default assertions**

Add a focused assertion to `tests/test_configuration_profiles.py`:

```python
def test_dev_profile_opts_into_public_management_surfaces(self) -> None:
    config = load_config(source=EnvConfigSource(environ={}), profile="dev")

    self.assertTrue(config.api.docs_enabled)
    self.assertTrue(config.api.openapi_enabled)
    self.assertTrue(config.api.docs_public)
    self.assertTrue(config.api.openapi_public)
    self.assertTrue(config.observability.prometheus_public)
```

Add a focused assertion to `tests/test_configuration_defaults.py`:

```python
def test_default_management_surfaces_are_production_safe(self) -> None:
    config = load_config(source=EnvConfigSource(environ={}))

    self.assertFalse(config.api.docs_enabled)
    self.assertFalse(config.api.openapi_enabled)
    self.assertFalse(config.api.docs_public)
    self.assertFalse(config.api.openapi_public)
    self.assertFalse(config.observability.prometheus_public)
```

- [x] **Step 2: Run the failing profile/default tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py -q
```

Expected: FAIL until `profiles/dev.toml` opts into the new fields.

- [x] **Step 3: Update profiles and docs**

In `profiles/base.toml`, add:

```toml
[api]
docs_enabled = false
openapi_enabled = false
docs_public = false
openapi_public = false
```

without removing existing `[api]` fields.

In `profiles/dev.toml`, add:

```toml
[api]
docs_enabled = true
openapi_enabled = true
docs_public = true
openapi_public = true

[observability]
prometheus_public = true
```

without removing existing profile settings.

In `.env.example`, document:

```text
API_DOCS_ENABLED=false
API_OPENAPI_ENABLED=false
API_DOCS_PUBLIC=false
API_OPENAPI_PUBLIC=false
PROMETHEUS_METRICS_PUBLIC=false
```

In `docs/observability.md`, replace the statement that `/metrics` is
intentionally public with the new credential-protected default and the public
opt-in flag.

- [x] **Step 4: Run profile/default tests again**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py -q
```

Expected: PASS.

---

### Task 5: Final Verification

**Files:**
- No production edits unless verification exposes a defect.

- [x] **Step 1: Run narrow verification**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_api_app.py -q
```

Expected: PASS.

- [x] **Step 2: Run formatting/static checks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect the diff and rerun the narrow
pytest command.

- [x] **Step 3: Inspect diff**

Run:

```powershell
git diff --check
git status --short
```

Expected: no whitespace errors, only intended files changed.

- [x] **Step 4: Commit implementation**

Run:

```powershell
git add rag_modules/configuration/models.py rag_modules/configuration/sections/api.py rag_modules/configuration/sections/observability.py rag_modules/interfaces/api/app.py rag_modules/interfaces/api/security.py tests/test_configuration_section_loaders.py tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_api_app.py profiles/base.toml profiles/dev.toml .env.example docs/observability.md docs/superpowers/plans/2026-06-23-api-security-policy-config.md
git commit -m "feat: configure API management surface security"
```

Expected: focused implementation commit.

---

## Self-Review

- Spec coverage: The plan covers production-safe defaults, dev opt-in, docs and
  OpenAPI registration, metrics protected/public/disabled states, OpenAPI
  security metadata, and documentation.
- Placeholder scan: The plan contains no TODO/TBD placeholders.
- Type consistency: Field names match the spec and are used consistently:
  `docs_enabled`, `openapi_enabled`, `docs_public`, `openapi_public`,
  `prometheus_public`.
