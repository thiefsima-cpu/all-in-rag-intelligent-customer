# API Contract Governance V1 Debug Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add canonical `/v1` API routes, keep complete traces behind explicit `/v1/debug/*` answer routes, and make public `/v1` answer responses omit full traces by default.

**Architecture:** Keep runtime and application DTOs unchanged. Add public answer DTOs at the FastAPI boundary, route public versioned endpoints through those DTOs, and keep existing full answer DTOs for compatibility and debug routes. Register `/v1` aliases at the route layer and share API version constants between serving and build app factories.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, pytest, existing GraphRAG API service and DTO modules.

---

## File Structure

- Modify `rag_modules/interfaces/api/answer_models.py`
  - Add public answer payload and response models that reuse existing strict submodels and omit `traces`.
  - Allow SSE result events to carry either public or debug answer payloads.
- Modify `rag_modules/interfaces/api/response_builder.py`
  - Add `build_public_answer_response()` that wraps a full answer payload as the public response model.
- Create `rag_modules/interfaces/api/versioning.py`
  - Define `API_PREFIX = "/v1"` and `API_VERSION = "1.0.0"`.
- Modify `rag_modules/interfaces/api/app.py`
  - Use shared `API_VERSION`.
- Modify `rag_modules/interfaces/api/security.py`
  - Treat versioned health paths as public and clear their OpenAPI security metadata.
- Modify `rag_modules/interfaces/api/routes.py`
  - Register `/v1` serving and build aliases.
  - Register public `/v1/answers` and `/v1/answers/stream`.
  - Register debug `/v1/debug/answers` and `/v1/debug/answers/stream`.
  - Preserve existing unversioned compatibility route behavior.
- Modify `rag_modules/interfaces/api/services/serving.py`
  - Add an `include_traces` switch to SSE result construction only.
- Modify `README.md`
  - Document `/v1` as preferred, public responses as trace-free by default, and debug answer routes as the full trace surface.
- Modify `tests/test_api_app.py`
  - Add failing API tests for public/debug versioned routes, version metadata, OpenAPI security, and build aliases.
- Modify `tests/test_answer_response_mapping.py`
  - Add model-level tests for public payload mapping without `to_dict()`.

---

### Task 1: Add Failing Model Tests For Public Answer DTOs

**Files:**
- Modify: `tests/test_answer_response_mapping.py`
- Later modify: `rag_modules/interfaces/api/answer_models.py`

- [ ] **Step 1: Write the failing test**

Add imports:

```python
from rag_modules.interfaces.api.answer_models import AnswerPayloadModel, PublicAnswerPayloadModel
```

Update the existing import if it already imports `AnswerPayloadModel`.

Add tests:

```python
def test_public_answer_payload_maps_typed_response_without_traces() -> None:
    response = _complete_result().to_response()

    payload = PublicAnswerPayloadModel.from_dto(response)

    assert payload.summary.answer == "grounded answer"
    assert payload.grounding.retrieval_outcome.strategy == "combined"
    assert payload.diagnostics.diagnostics.overall_bucket == "healthy"
    assert "traces" not in payload.model_dump()


def test_public_answer_payload_can_be_derived_from_debug_payload() -> None:
    response = _complete_result().to_response()
    debug_payload = AnswerPayloadModel.from_dto(response)

    payload = PublicAnswerPayloadModel.from_debug_payload(debug_payload)

    assert payload.model_dump() == {
        "summary": debug_payload.summary.model_dump(),
        "grounding": debug_payload.grounding.model_dump(),
        "diagnostics": debug_payload.diagnostics.model_dump(),
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py::test_public_answer_payload_maps_typed_response_without_traces tests/test_answer_response_mapping.py::test_public_answer_payload_can_be_derived_from_debug_payload -q
```

Expected: FAIL because `PublicAnswerPayloadModel` is not defined.

- [ ] **Step 3: Implement minimal public DTOs**

In `rag_modules/interfaces/api/answer_models.py`, add after `AnswerTracesModel`:

```python
class PublicAnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: AnswerGroundingModel
    diagnostics: AnswerDiagnosticsModel

    @classmethod
    def from_debug_payload(cls, payload: "AnswerPayloadModel") -> "PublicAnswerPayloadModel":
        return cls(
            summary=payload.summary,
            grounding=payload.grounding,
            diagnostics=payload.diagnostics,
        )

    @classmethod
    def from_dto(cls, response: QuestionAnswerResponse) -> "PublicAnswerPayloadModel":
        return cls(
            summary=AnswerSummaryModel.from_dto(response.summary),
            grounding=AnswerGroundingModel.from_dto(response.grounding),
            diagnostics=AnswerDiagnosticsModel.from_dto(response.diagnostics),
        )
```

Add after `AnswerResponseModel`:

```python
class PublicAnswerResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: PublicAnswerPayloadModel
```

Update `AnswerStreamResultDataModel`:

```python
class AnswerStreamResultDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AnswerPayloadModel | PublicAnswerPayloadModel
```

Update `AnswerStreamEventModel.result()`:

```python
    def result(
        cls,
        response: AnswerPayloadModel | PublicAnswerPayloadModel,
    ) -> "AnswerStreamEventModel":
```

Add `PublicAnswerPayloadModel` and `PublicAnswerResponseModel` to `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py::test_public_answer_payload_maps_typed_response_without_traces tests/test_answer_response_mapping.py::test_public_answer_payload_can_be_derived_from_debug_payload -q
```

Expected: PASS.

---

### Task 2: Add Failing Tests For Public And Debug `/v1` Answer Routes

**Files:**
- Modify: `tests/test_api_app.py`
- Later modify: `rag_modules/interfaces/api/response_builder.py`
- Later modify: `rag_modules/interfaces/api/routes.py`
- Later modify: `rag_modules/interfaces/api/services/serving.py`

- [ ] **Step 1: Write the failing tests**

Add helper near existing SSE parsing code if there is no reusable helper:

```python
def _parse_sse_events(body: str) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for block in body.strip().split("\n\n"):
        lines = [line for line in block.splitlines() if line]
        event_name = ""
        data = None
        for line in lines:
            if line.startswith("event: "):
                event_name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if event_name:
            events.setdefault(event_name, []).append(data)
    return events
```

Add tests:

```python
def test_v1_answer_omits_traces_by_default(self) -> None:
    system = _FakeApiSystem()
    system.system_ready = True
    app = create_serving_api_app(system=system)

    with _client(app) as client:
        response = client.post("/v1/answers", json={"question": "Can I cook tofu?"})

    self.assertEqual(response.status_code, 200)
    payload = response.json()["response"]
    self.assertEqual(payload["summary"]["answer"], "answer:Can I cook tofu?")
    self.assertNotIn("traces", payload)


def test_v1_debug_answer_includes_traces(self) -> None:
    system = _FakeApiSystem()
    system.system_ready = True
    app = create_serving_api_app(system=system)

    with _client(app) as client:
        response = client.post("/v1/debug/answers", json={"question": "Can I cook tofu?"})

    self.assertEqual(response.status_code, 200)
    payload = response.json()["response"]
    self.assertEqual(
        payload["traces"]["generation_trace"]["token_usage_source"],
        "test",
    )
```

Add SSE tests:

```python
def test_v1_answer_stream_result_omits_traces_by_default(self) -> None:
    system = _FakeApiSystem()
    system.system_ready = True
    app = create_serving_api_app(system=system)

    with _client(app) as client:
        with client.stream(
            "POST",
            "/v1/answers/stream",
            json={"question": "Can I cook tofu?"},
        ) as response:
            body = "".join(response.iter_text())

    self.assertEqual(response.status_code, 200)
    result_payload = _parse_sse_events(body)["result"][0]["response"]
    self.assertEqual(result_payload["summary"]["answer"], "answer:Can I cook tofu?")
    self.assertNotIn("traces", result_payload)


def test_v1_debug_answer_stream_result_includes_traces(self) -> None:
    system = _FakeApiSystem()
    system.system_ready = True
    app = create_serving_api_app(system=system)

    with _client(app) as client:
        with client.stream(
            "POST",
            "/v1/debug/answers/stream",
            json={"question": "Can I cook tofu?"},
        ) as response:
            body = "".join(response.iter_text())

    self.assertEqual(response.status_code, 200)
    result_payload = _parse_sse_events(body)["result"][0]["response"]
    self.assertEqual(
        result_payload["traces"]["generation_trace"]["token_usage_source"],
        "test",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_v1_answer_omits_traces_by_default tests/test_api_app.py::GraphRAGApiAppTests::test_v1_debug_answer_includes_traces tests/test_api_app.py::GraphRAGApiAppTests::test_v1_answer_stream_result_omits_traces_by_default tests/test_api_app.py::GraphRAGApiAppTests::test_v1_debug_answer_stream_result_includes_traces -q
```

Expected: FAIL with 404s for missing `/v1` routes.

- [ ] **Step 3: Implement public response builder**

In `rag_modules/interfaces/api/response_builder.py`, import `PublicAnswerResponseModel` and add:

```python
def build_public_answer_response(answer_payload: AnswerPayloadModel) -> PublicAnswerResponseModel:
    return PublicAnswerResponseModel(
        response=PublicAnswerPayloadModel.from_debug_payload(answer_payload)
    )
```

Add it to `__all__`.

- [ ] **Step 4: Implement SSE include-traces switch**

In `rag_modules/interfaces/api/services/serving.py`, import `PublicAnswerPayloadModel`.

Change `stream_answer_question_events()` and `_iter_stream_answer_question_events()` signatures:

```python
        include_traces: bool = True,
```

Pass the value through to `_iter_stream_answer_question_events()`.

Inside `runner()`, replace result emission with:

```python
                answer_payload = self._answer_payload(response)
                if not include_traces:
                    answer_payload = PublicAnswerPayloadModel.from_debug_payload(answer_payload)
                emit(AnswerStreamEventModel.result(answer_payload))
```

- [ ] **Step 5: Implement versioned answer routes**

In `rag_modules/interfaces/api/routes.py`, import `API_PREFIX`, `PublicAnswerResponseModel`, and
`build_public_answer_response`.

Add public route:

```python
    @app.post(
        f"{API_PREFIX}/answers",
        response_model=PublicAnswerResponseModel,
        summary="Get one public answer payload",
        responses={
            200: {"description": "Public answer payload or compatibility SSE stream."},
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def answer_question_v1(payload: AnswerRequestModel):
        payload_data = payload.model_dump()
        if payload_data.get("stream", False):
            return build_sse_streaming_response(
                api_service.stream_answer_question_events(
                    question=payload.question,
                    explain_routing=payload.explain_routing,
                    request_id=current_request_id(),
                    include_traces=False,
                )
            )
        return build_public_answer_response(
            api_service.answer_question(
                question=payload.question,
                stream=False,
                explain_routing=payload.explain_routing,
            )
        )
```

Add debug route:

```python
    @app.post(
        f"{API_PREFIX}/debug/answers",
        response_model=AnswerResponseModel,
        summary="Get one debug answer payload with traces",
        responses={
            200: {"description": "Debug answer payload with complete traces."},
            409: {"description": "Serving runtime is initialized but artifacts are not ready."},
        },
    )
    def debug_answer_question_v1(payload: AnswerRequestModel):
        payload_data = payload.model_dump()
        if payload_data.get("stream", False):
            return build_sse_streaming_response(
                api_service.stream_answer_question_events(
                    question=payload.question,
                    explain_routing=payload.explain_routing,
                    request_id=current_request_id(),
                    include_traces=True,
                )
            )
        return build_answer_response(
            api_service.answer_question(
                question=payload.question,
                stream=False,
                explain_routing=payload.explain_routing,
            )
        )
```

Add public stream route:

```python
    @app.post(
        f"{API_PREFIX}/answers/stream",
        summary="Stream public answer events over SSE",
        response_class=StreamingResponse,
        responses={200: {"description": "Server-Sent Events stream."}},
    )
    def stream_answer_question_v1(payload: AnswerStreamRequestModel):
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=current_request_id(),
                include_traces=False,
            )
        )
```

Add debug stream route:

```python
    @app.post(
        f"{API_PREFIX}/debug/answers/stream",
        summary="Stream debug answer events over SSE with traces",
        response_class=StreamingResponse,
        responses={200: {"description": "Debug Server-Sent Events stream."}},
    )
    def stream_debug_answer_question_v1(payload: AnswerStreamRequestModel):
        return build_sse_streaming_response(
            api_service.stream_answer_question_events(
                question=payload.question,
                explain_routing=payload.explain_routing,
                request_id=current_request_id(),
                include_traces=True,
            )
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_v1_answer_omits_traces_by_default tests/test_api_app.py::GraphRAGApiAppTests::test_v1_debug_answer_includes_traces tests/test_api_app.py::GraphRAGApiAppTests::test_v1_answer_stream_result_omits_traces_by_default tests/test_api_app.py::GraphRAGApiAppTests::test_v1_debug_answer_stream_result_includes_traces -q
```

Expected: PASS.

---

### Task 3: Add Failing Tests For Version Constants, Health, Security, And Build Aliases

**Files:**
- Modify: `tests/test_api_app.py`
- Later create: `rag_modules/interfaces/api/versioning.py`
- Later modify: `rag_modules/interfaces/api/app.py`
- Later modify: `rag_modules/interfaces/api/security.py`
- Later modify: `rag_modules/interfaces/api/routes.py`

- [ ] **Step 1: Write the failing tests**

Add imports:

```python
from rag_modules.interfaces.api.versioning import API_VERSION
```

Add tests:

```python
def test_serving_and_build_apps_share_api_version(self) -> None:
    serving_app = create_serving_api_app(system=_FakeApiSystem())
    build_app = create_build_api_app(system=_FakeApiSystem())

    self.assertEqual(serving_app.version, API_VERSION)
    self.assertEqual(build_app.version, API_VERSION)


def test_v1_health_paths_are_public_and_protected_paths_stay_protected(self) -> None:
    app = create_serving_api_app(system=_FakeApiSystem())

    with TestClient(app) as client:
        health = client.get("/v1/health")
        stats = client.get("/v1/stats")
        debug = client.post("/v1/debug/answers", json={"question": "tofu"})

    self.assertEqual(health.status_code, 200)
    _assert_error_response(stats, status_code=401, code="UNAUTHORIZED")
    _assert_error_response(debug, status_code=401, code="UNAUTHORIZED")


def test_v1_build_routes_match_unversioned_build_routes(self) -> None:
    system = _FakeApiSystem()
    app = create_build_api_app(system=system)

    with _client(app) as client:
        health = client.get("/v1/health")
        initialize = client.post("/v1/runtime/build/initialize")
        build_response = client.post("/v1/jobs/build")
        artifacts = client.get("/v1/artifacts")

    self.assertEqual(health.status_code, 200)
    self.assertEqual(initialize.status_code, 200)
    self.assertEqual(build_response.status_code, 202)
    self.assertIn(build_response.json()["job"]["job_id"], {job["job_id"] for job in client.get("/v1/jobs").json()["jobs"]})
    self.assertEqual(artifacts.status_code, 200)
```

Add OpenAPI security test:

```python
def test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected(self) -> None:
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

    self.assertEqual(schema["paths"]["/v1/health"]["get"]["security"], [])
    self.assertNotEqual(schema["paths"]["/v1/debug/answers"]["post"].get("security"), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_serving_and_build_apps_share_api_version tests/test_api_app.py::GraphRAGApiAppTests::test_v1_health_paths_are_public_and_protected_paths_stay_protected tests/test_api_app.py::GraphRAGApiAppTests::test_v1_build_routes_match_unversioned_build_routes tests/test_api_app.py::GraphRAGApiAppTests::test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected -q
```

Expected: FAIL because the constants module and `/v1` operational routes do not exist yet.

- [ ] **Step 3: Add version constants**

Create `rag_modules/interfaces/api/versioning.py`:

```python
"""Shared API version constants."""

from __future__ import annotations

API_PREFIX = "/v1"
API_VERSION = "1.0.0"

__all__ = ["API_PREFIX", "API_VERSION"]
```

Update `rag_modules/interfaces/api/app.py`:

```python
from .versioning import API_VERSION
```

Replace both `version="1.0.0"` arguments with `version=API_VERSION`.

- [ ] **Step 4: Register `/v1` health and operational route aliases**

In `rag_modules/interfaces/api/routes.py`, stack versioned decorators for routes whose response
model and behavior are unchanged:

```python
    @app.get(f"{API_PREFIX}/health", response_model=HealthResponseModel)
    @app.get("/health", response_model=HealthResponseModel)
    def read_health():
        return api_service.health()
```

Apply this pattern to:

- serving health, live, ready, stats, diagnostics, serving initialize, serving refresh.
- build health, live, ready, stats, diagnostics, build initialize, jobs, artifacts, job detail,
  jobs build, jobs rebuild, knowledge-base build, knowledge-base rebuild.

Keep `@app.get("/")` as an unversioned root health route only.

- [ ] **Step 5: Update security public paths**

In `rag_modules/interfaces/api/security.py`, import `API_PREFIX` and define:

```python
_BASE_PUBLIC_PATHS = frozenset(
    {
        "/",
        "/health",
        "/health/live",
        "/health/ready",
        f"{API_PREFIX}/health",
        f"{API_PREFIX}/health/live",
        f"{API_PREFIX}/health/ready",
    }
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_serving_and_build_apps_share_api_version tests/test_api_app.py::GraphRAGApiAppTests::test_v1_health_paths_are_public_and_protected_paths_stay_protected tests/test_api_app.py::GraphRAGApiAppTests::test_v1_build_routes_match_unversioned_build_routes tests/test_api_app.py::GraphRAGApiAppTests::test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected -q
```

Expected: PASS.

---

### Task 4: Add OpenAPI Schema And Documentation Tests

**Files:**
- Modify: `tests/test_api_app.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing OpenAPI schema test**

Add:

```python
def test_openapi_distinguishes_public_and_debug_answer_schemas(self) -> None:
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

    public_response_ref = schema["paths"]["/v1/answers"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    debug_response_ref = schema["paths"]["/v1/debug/answers"]["post"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]

    self.assertEqual(public_response_ref, "#/components/schemas/PublicAnswerResponseModel")
    self.assertEqual(debug_response_ref, "#/components/schemas/AnswerResponseModel")
    self.assertNotIn(
        "traces",
        schema["components"]["schemas"]["PublicAnswerPayloadModel"]["properties"],
    )
    self.assertIn("traces", schema["components"]["schemas"]["AnswerPayloadModel"]["properties"])
```

- [ ] **Step 2: Run test to verify it fails if schema registration is incomplete**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_openapi_distinguishes_public_and_debug_answer_schemas -q
```

Expected before implementation: FAIL if `/v1` answer routes or public schemas are not registered.

- [ ] **Step 3: Update README**

In `README.md`, update the Docker build API example to use `/v1/jobs/build` and `/v1/jobs/{id}`:

```powershell
$job = Invoke-RestMethod -Method Post http://localhost:8001/v1/jobs/build
Invoke-RestMethod http://localhost:8001/v1/jobs/$($job.job.job_id)
```

Update the answer readiness note:

```markdown
`/v1/answers` returns `409 Conflict` until the build API has produced a ready
artifact manifest, cached documents, and a Milvus vector collection.
```

Add under the error contract section:

```markdown
### Versioned API and debug traces

Use `/v1` for new API clients. The unversioned routes remain compatibility aliases.

Public answer routes (`/v1/answers` and `/v1/answers/stream`) return `summary`,
`grounding`, and `diagnostics` without the complete `traces` object. Full trace
payloads are available only through explicit debug routes:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/v1/debug/answers -Body (@{question="..."} | ConvertTo-Json) -ContentType application/json
```
```

- [ ] **Step 4: Run OpenAPI and documentation-adjacent tests**

Run:

```powershell
python -m pytest tests/test_api_app.py::GraphRAGApiAppTests::test_openapi_distinguishes_public_and_debug_answer_schemas tests/test_entrypoints.py tests/test_public_api_manifest.py -q
```

Expected: PASS.

---

### Task 5: Focused Regression Sweep

**Files:**
- All files touched by prior tasks.

- [ ] **Step 1: Run answer mapping and API tests**

Run:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_api_app.py -q
```

Expected: PASS.

- [ ] **Step 2: Fix any regressions using TDD**

For each regression, write or update the smallest failing test that captures the intended
behavior before changing production code. Keep unversioned compatibility route behavior intact
unless a test explicitly describes a versioned route.

- [ ] **Step 3: Run release-sensitive checks**

Run:

```powershell
python -m pytest tests/test_entrypoints.py tests/test_public_api_manifest.py -q
python scripts/release_gate.py
```

Expected: PASS.

- [ ] **Step 4: Run formatting/hooks**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS, or record any environment-specific failure and run the closest available Ruff or
pytest checks.

- [ ] **Step 5: Review git diff**

Run:

```powershell
git diff --check
git diff --stat
git status --short
```

Expected: no whitespace errors; only intended files changed.

---

## Self-Review

- The plan covers every requirement in the committed design spec.
- The public response contract is API-only and does not alter runtime DTOs.
- Debug routes are explicit URLs, not query or header switches.
- `/v1` is introduced for both serving and build applications.
- Existing unversioned routes remain compatibility aliases.
- No placeholders remain.
