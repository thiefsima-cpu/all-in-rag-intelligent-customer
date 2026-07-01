# Compatibility Layer Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make active compatibility layers declare, expose, test, and document their retirement versions without changing runtime behavior.

**Architecture:** Keep runtime routes and router delegation intact. Add machine-readable compatibility metadata beside existing versioning and adapter code, then patch OpenAPI generation so unversioned HTTP paths are deprecated aliases while `/v1` paths stay canonical. Documentation and boundary tests distinguish already-retired `0.2.0` import facades from active API aliases and the active `IntelligentQueryRouter` adapter.

**Tech Stack:** Python 3.11, FastAPI, unittest/pytest, existing public-surface boundary tests, README and docs policy files.

---

## File Structure

- Modify `rag_modules/interfaces/api/versioning.py`: API compatibility constants plus OpenAPI metadata helpers.
- Modify `rag_modules/interfaces/api/app.py`: install the OpenAPI compatibility metadata wrapper for serving and build apps.
- Modify `tests/test_api_app.py`: failing tests for unversioned API alias OpenAPI metadata.
- Modify `rag_modules/routing/intelligent_query_router.py`: router adapter removal-version constant and docstring.
- Modify `rag_modules/routing/__init__.py`: export the adapter removal-version constant from the routing package.
- Modify `tests/test_intelligent_query_router.py`: failing test for adapter retirement metadata.
- Modify `tests/test_public_surface_boundaries.py`: docs boundary coverage for active compatibility retirement policy.
- Modify `README.md`: API client guidance names the `2.0.0` unversioned route removal version.
- Modify `docs/public_surface_retirement_plan.md`: separate active compatibility policy from completed `0.2.0` facade retirement.

Do not touch unrelated local changes. The current workspace may contain unrelated edits; stage only files listed in each task.

---

### Task 1: Cover Unversioned API Alias OpenAPI Policy

**Files:**
- Modify: `tests/test_api_app.py`
- Later modify: `rag_modules/interfaces/api/versioning.py`
- Later modify: `rag_modules/interfaces/api/app.py`

- [ ] **Step 1: Write the failing API metadata tests**

In `tests/test_api_app.py`, replace the existing versioning import:

```python
from rag_modules.interfaces.api.versioning import API_VERSION
```

with:

```python
from rag_modules.interfaces.api.versioning import (
    API_VERSION,
    UNVERSIONED_API_ALIAS_REMOVAL_VERSION,
)
```

Add these tests after `test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected`:

```python
    def test_unversioned_serving_openapi_routes_are_deprecated_aliases(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        expectations = {
            ("/", "get"): "/v1/health",
            ("/health", "get"): "/v1/health",
            ("/health/live", "get"): "/v1/health/live",
            ("/health/ready", "get"): "/v1/health/ready",
            ("/stats", "get"): "/v1/stats",
            ("/diagnostics", "get"): "/v1/diagnostics",
            ("/runtime/serving/initialize", "post"): "/v1/runtime/serving/initialize",
            ("/runtime/serving/refresh", "post"): "/v1/runtime/serving/refresh",
            ("/answers", "post"): "/v1/answers",
            ("/answers/stream", "post"): "/v1/answers/stream",
        }

        for (path, method), canonical_path in expectations.items():
            operation = schema["paths"][path][method]
            self.assertTrue(operation.get("deprecated"), path)
            description = operation.get("description", "")
            self.assertIn(UNVERSIONED_API_ALIAS_REMOVAL_VERSION, description)
            self.assertIn(canonical_path, description)

        self.assertFalse(schema["paths"]["/v1/health"]["get"].get("deprecated", False))
        self.assertFalse(schema["paths"]["/v1/answers"]["post"].get("deprecated", False))
        self.assertFalse(
            schema["paths"]["/v1/answers/stream"]["post"].get("deprecated", False)
        )

    def test_unversioned_build_openapi_routes_are_deprecated_aliases(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_build_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        expectations = {
            ("/", "get"): "/v1/health",
            ("/health", "get"): "/v1/health",
            ("/health/live", "get"): "/v1/health/live",
            ("/health/ready", "get"): "/v1/health/ready",
            ("/stats", "get"): "/v1/stats",
            ("/diagnostics", "get"): "/v1/diagnostics",
            ("/runtime/build/initialize", "post"): "/v1/runtime/build/initialize",
            ("/jobs", "get"): "/v1/jobs",
            ("/jobs/{job_id}", "get"): "/v1/jobs/{job_id}",
            ("/jobs/build", "post"): "/v1/jobs/build",
            ("/jobs/rebuild", "post"): "/v1/jobs/rebuild",
            ("/artifacts", "get"): "/v1/artifacts",
            ("/knowledge-base/build", "post"): "/v1/jobs/build",
            ("/knowledge-base/rebuild", "post"): "/v1/jobs/rebuild",
        }

        for (path, method), canonical_path in expectations.items():
            operation = schema["paths"][path][method]
            self.assertTrue(operation.get("deprecated"), path)
            description = operation.get("description", "")
            self.assertIn(UNVERSIONED_API_ALIAS_REMOVAL_VERSION, description)
            self.assertIn(canonical_path, description)

        self.assertFalse(schema["paths"]["/v1/health"]["get"].get("deprecated", False))
        self.assertFalse(schema["paths"]["/v1/jobs"]["get"].get("deprecated", False))
        self.assertFalse(schema["paths"]["/v1/jobs/build"]["post"].get("deprecated", False))
        self.assertFalse(
            schema["paths"]["/v1/knowledge-base/build"]["post"].get("deprecated", False)
        )
```

- [ ] **Step 2: Run the new tests to verify RED**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_serving_openapi_routes_are_deprecated_aliases tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_build_openapi_routes_are_deprecated_aliases -q
```

Expected: FAIL because `UNVERSIONED_API_ALIAS_REMOVAL_VERSION` is not exported yet, or because unversioned OpenAPI operations are not marked deprecated.

- [ ] **Step 3: Add API compatibility metadata helpers**

Replace `rag_modules/interfaces/api/versioning.py` with:

```python
"""Shared API version constants and compatibility metadata."""

from __future__ import annotations

from typing import Any

API_PREFIX = "/v1"
API_VERSION = "1.0.0"
UNVERSIONED_API_ALIAS_REMOVAL_VERSION = "2.0.0"

UNVERSIONED_API_ALIAS_TARGETS: dict[str, str] = {
    "/": f"{API_PREFIX}/health",
    "/health": f"{API_PREFIX}/health",
    "/health/live": f"{API_PREFIX}/health/live",
    "/health/ready": f"{API_PREFIX}/health/ready",
    "/stats": f"{API_PREFIX}/stats",
    "/diagnostics": f"{API_PREFIX}/diagnostics",
    "/runtime/serving/initialize": f"{API_PREFIX}/runtime/serving/initialize",
    "/runtime/serving/refresh": f"{API_PREFIX}/runtime/serving/refresh",
    "/answers": f"{API_PREFIX}/answers",
    "/answers/stream": f"{API_PREFIX}/answers/stream",
    "/runtime/build/initialize": f"{API_PREFIX}/runtime/build/initialize",
    "/jobs": f"{API_PREFIX}/jobs",
    "/jobs/{job_id}": f"{API_PREFIX}/jobs/{{job_id}}",
    "/jobs/build": f"{API_PREFIX}/jobs/build",
    "/jobs/rebuild": f"{API_PREFIX}/jobs/rebuild",
    "/artifacts": f"{API_PREFIX}/artifacts",
    "/knowledge-base/build": f"{API_PREFIX}/jobs/build",
    "/knowledge-base/rebuild": f"{API_PREFIX}/jobs/rebuild",
}


def unversioned_api_alias_description(canonical_path: str) -> str:
    return (
        f"Deprecated compatibility alias for `{canonical_path}`. "
        f"Use `{canonical_path}` for new API clients. "
        "This unversioned alias will be removed in API version "
        f"{UNVERSIONED_API_ALIAS_REMOVAL_VERSION}."
    )


def apply_unversioned_api_alias_metadata(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return

    for path, canonical_path in UNVERSIONED_API_ALIAS_TARGETS.items():
        operations = paths.get(path)
        if not isinstance(operations, dict):
            continue
        alias_description = unversioned_api_alias_description(canonical_path)
        for method, operation in operations.items():
            if method == "parameters" or not isinstance(operation, dict):
                continue
            operation["deprecated"] = True
            existing_description = str(operation.get("description") or "").strip()
            if not existing_description:
                operation["description"] = alias_description
            elif alias_description not in existing_description:
                operation["description"] = f"{alias_description}\n\n{existing_description}"


def configure_unversioned_api_alias_metadata(app: Any) -> None:
    original_openapi = app.openapi

    def compatibility_openapi():
        schema = original_openapi()
        apply_unversioned_api_alias_metadata(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = compatibility_openapi


__all__ = [
    "API_PREFIX",
    "API_VERSION",
    "UNVERSIONED_API_ALIAS_REMOVAL_VERSION",
    "UNVERSIONED_API_ALIAS_TARGETS",
    "apply_unversioned_api_alias_metadata",
    "configure_unversioned_api_alias_metadata",
    "unversioned_api_alias_description",
]
```

- [ ] **Step 4: Install the OpenAPI metadata wrapper in app factories**

In `rag_modules/interfaces/api/app.py`, replace:

```python
from .versioning import API_VERSION
```

with:

```python
from .versioning import API_VERSION, configure_unversioned_api_alias_metadata
```

In `create_serving_api_app`, after `_register_metrics_endpoint(app, system=api_service.system, config=config)`, add:

```python
    configure_unversioned_api_alias_metadata(app)
```

In `create_build_api_app`, after `_register_metrics_endpoint(app, system=api_service.system, config=config)`, add:

```python
    configure_unversioned_api_alias_metadata(app)
```

- [ ] **Step 5: Run the API metadata tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_serving_openapi_routes_are_deprecated_aliases tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_build_openapi_routes_are_deprecated_aliases -q
```

Expected: PASS.

- [ ] **Step 6: Commit the API metadata change**

Run:

```powershell
git add rag_modules/interfaces/api/versioning.py rag_modules/interfaces/api/app.py tests/test_api_app.py
git commit -m "feat: mark unversioned API aliases deprecated"
```

---

### Task 2: Declare Router Adapter Retirement Metadata

**Files:**
- Modify: `tests/test_intelligent_query_router.py`
- Modify: `rag_modules/routing/intelligent_query_router.py`
- Modify: `rag_modules/routing/__init__.py`

- [ ] **Step 1: Write the failing adapter metadata test**

In `tests/test_intelligent_query_router.py`, replace:

```python
from rag_modules.routing import IntelligentQueryRouter
```

with:

```python
from rag_modules.routing import (
    INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION,
    IntelligentQueryRouter,
)
```

Add this test after `test_facade_delegates_to_workflow_service`:

```python
    def test_facade_declares_retirement_metadata(self) -> None:
        self.assertEqual(INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION, "0.3.0")
        docstring = IntelligentQueryRouter.__doc__ or ""
        self.assertIn("RoutingWorkflowService", docstring)
        self.assertIn(INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION, docstring)
```

- [ ] **Step 2: Run the adapter test to verify RED**

Run:

```powershell
python -m pytest tests/test_intelligent_query_router.py::IntelligentQueryRouterTests::test_facade_declares_retirement_metadata -q
```

Expected: FAIL because `INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION` is not exported yet.

- [ ] **Step 3: Add the adapter removal-version constant**

In `rag_modules/routing/intelligent_query_router.py`, add this constant after the `TYPE_CHECKING` block:

```python
INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION = "0.3.0"
```

Replace the class docstring:

```python
    """Legacy router-shaped adapter over RoutingWorkflowService."""
```

with:

```python
    """Legacy router-shaped adapter over RoutingWorkflowService.

    Deprecated compatibility adapter. Prefer RoutingWorkflowService for new code.
    Removed in package version 0.3.0.
    """
```

Replace the module export list:

```python
__all__ = ["IntelligentQueryRouter"]
```

with:

```python
__all__ = ["INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION", "IntelligentQueryRouter"]
```

- [ ] **Step 4: Export the constant from the routing package**

In `rag_modules/routing/__init__.py`, add the constant to `_EXPORTS`:

```python
    "INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION": ".intelligent_query_router",
```

The top of `_EXPORTS` should read:

```python
_EXPORTS = {
    "INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION": ".intelligent_query_router",
    "IntelligentQueryRouter": ".intelligent_query_router",
    "RouteExecutionRequest": ".search_orchestrator",
```

Add the constant to `__all__`:

```python
    "INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION",
```

The start of `__all__` should read:

```python
__all__ = [
    "INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION",
    "IntelligentQueryRouter",
    "RouteExecutionRequest",
```

- [ ] **Step 5: Run router tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_intelligent_query_router.py -q
```

Expected: PASS. The existing delegation test must still pass, proving no routing behavior changed.

- [ ] **Step 6: Commit the adapter metadata change**

Run:

```powershell
git add rag_modules/routing/intelligent_query_router.py rag_modules/routing/__init__.py tests/test_intelligent_query_router.py
git commit -m "feat: declare router adapter retirement"
```

---

### Task 3: Document Active Compatibility Retirement Policy

**Files:**
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `README.md`
- Modify: `docs/public_surface_retirement_plan.md`

- [ ] **Step 1: Write the failing documentation boundary test**

In `tests/test_public_surface_boundaries.py`, add these imports near the existing manifest import:

```python
from rag_modules.interfaces.api.versioning import UNVERSIONED_API_ALIAS_REMOVAL_VERSION
from rag_modules.routing import INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION
```

In `test_retirement_plan_document_states_current_policy`, add this heading to the `heading` tuple:

```python
            "## Active Compatibility Layers",
```

Add this test after `test_retirement_plan_document_states_current_policy`:

```python
    def test_active_compatibility_policy_documents_retirement_versions(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("Use `/v1` for new API clients", readme)
        self.assertIn(UNVERSIONED_API_ALIAS_REMOVAL_VERSION, readme)

        for expected in (
            "## Active Compatibility Layers",
            "unversioned HTTP API aliases",
            "rag_modules.routing.IntelligentQueryRouter",
            UNVERSIONED_API_ALIAS_REMOVAL_VERSION,
            INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION,
            "already-completed `0.2.0` import-facade retirement",
        ):
            self.assertIn(expected, policy)
```

- [ ] **Step 2: Run the docs test to verify RED**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_active_compatibility_policy_documents_retirement_versions tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_retirement_plan_document_states_current_policy -q
```

Expected: FAIL because README and the public-surface retirement policy do not yet mention the active compatibility retirement versions.

- [ ] **Step 3: Update README API compatibility guidance**

In `README.md`, replace:

```markdown
Use `/v1` for new API clients. The unversioned routes remain compatibility aliases.
```

with:

```markdown
Use `/v1` for new API clients. The unversioned routes remain compatibility
aliases during the migration window and will be removed in API version `2.0.0`.
```

- [ ] **Step 4: Add the active compatibility section to the retirement policy**

In `docs/public_surface_retirement_plan.md`, insert this section after the retired module table in `## Legacy Bridge Status` and before `## Scan Rules`:

```markdown
## Active Compatibility Layers

The already-completed `0.2.0` import-facade retirement does not remove every
compatibility layer. The following adapters remain active only for migration
windows and are not alternate architecture paths.

| Active layer | Canonical replacement | Status | Removal version |
| --- | --- | --- | --- |
| unversioned HTTP API aliases | `/v1` serving and build routes | deprecated compatibility aliases for existing HTTP clients | API version `2.0.0` |
| `rag_modules.routing.IntelligentQueryRouter` | `rag_modules.routing.RoutingWorkflowService` or the routing workflow protocol | thin service adapter for callers still using the router-shaped API | package version `0.3.0` |

New HTTP clients must use `/v1`. New Python routing code must use
`RoutingWorkflowService` or the routing workflow protocol. Compatibility tests
may import or call active adapters only to verify delegation, deprecation
metadata, and removal-version policy.
```

- [ ] **Step 5: Run the docs boundary tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_active_compatibility_policy_documents_retirement_versions tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_retirement_plan_document_states_current_policy -q
```

Expected: PASS.

- [ ] **Step 6: Commit the documentation policy change**

Run:

```powershell
git add README.md docs/public_surface_retirement_plan.md tests/test_public_surface_boundaries.py
git commit -m "docs: document active compatibility retirement"
```

---

### Task 4: Final Verification

**Files:**
- Verify all files modified in Tasks 1-3.

- [ ] **Step 1: Run focused compatibility tests**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_serving_openapi_routes_are_deprecated_aliases tests/test_api_app.py::GraphRAGApiAppTests::test_unversioned_build_openapi_routes_are_deprecated_aliases tests/test_intelligent_query_router.py tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_active_compatibility_policy_documents_retirement_versions tests/test_public_surface_boundaries.py::PublicSurfaceBoundaryTests::test_retirement_plan_document_states_current_policy -q
```

Expected: PASS.

- [ ] **Step 2: Run broader affected tests**

Run:

```powershell
python -m pytest tests/test_api_app.py tests/test_intelligent_query_router.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

- [ ] **Step 3: Run repository hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect the diff, rerun the focused tests from Step 1, and include the formatter changes in the final commit.

- [ ] **Step 4: Run release gate if the API metadata change is treated as release-sensitive**

Run:

```powershell
python scripts/release_gate.py
```

Expected: PASS. If this is skipped, state explicitly that the implementation changed OpenAPI metadata but not runtime behavior.

- [ ] **Step 5: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only files from this plan are modified or staged, aside from pre-existing unrelated workspace changes. Do not revert unrelated files.

- [ ] **Step 6: Commit final verification fixes if needed**

If Step 3 or Step 4 required formatter or small verification fixes, run:

```powershell
git add rag_modules/interfaces/api/versioning.py rag_modules/interfaces/api/app.py rag_modules/routing/intelligent_query_router.py rag_modules/routing/__init__.py tests/test_api_app.py tests/test_intelligent_query_router.py tests/test_public_surface_boundaries.py README.md docs/public_surface_retirement_plan.md
git commit -m "test: verify compatibility retirement policy"
```

Expected: commit succeeds. Skip this commit if there are no new changes after Tasks 1-3.

---

## Self-Review Checklist

- Spec coverage:
  - API alias removal version `2.0.0`: Task 1 and Task 3.
  - `IntelligentQueryRouter` removal version `0.3.0`: Task 2 and Task 3.
  - Current compatibility behavior preserved: Task 1 patches only OpenAPI metadata; Task 2 keeps delegation test green.
  - Docs separate completed `0.2.0` retirement from active compatibility: Task 3.
  - Verification commands: Task 4.
- Placeholder scan: no placeholder markers, "similar to", or unspecified test steps.
- Type consistency: constants are imported from `rag_modules.interfaces.api.versioning` and `rag_modules.routing`; tests use the same names that implementation exports.
