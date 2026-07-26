# Configuration, Contract, and Kernel Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Converge configuration, shared contracts, and kernel primitives into responsibility-owned modules, remove three redundant protocols and every explicit `Any` in those packages, and hard-retire obsolete import and DTO surfaces.

**Architecture:** Configuration has one loader and two declarative owners (`models.py` and `environment_schema.py`). External documents normalize through `langchain_document_adapter.py`; contracts contain shared DTOs plus the two real build-job ports; kernel owns JSON coercion and artifact compatibility. Deleted paths and deprecated fields fail immediately, and structural tests ratchet the lower measured repository baseline.

**Tech Stack:** Python 3.11, Pydantic, FastAPI, dataclasses, mypy 2.1, Ruff, pytest/unittest, TOML, AST-based structural tests.

## Global Constraints

- Use Python `>=3.11,<3.12`; do not add dependencies or edit generated requirements lock files.
- Use a hard cutover: no forwarding module, alias, lazy export, `sys.modules` bridge, fallback import, deprecated-field warning, or dual DTO input path.
- Preserve configuration precedence: defaults, query-policy overlay, profile, environment, then explicit overrides.
- Preserve active configuration error paths, build-job transitions, kernel value semantics, HTTP routes, answer behavior, retrieval ranking, and graph algorithms.
- End with exactly eight `rag_modules.configuration` Python modules: `__init__.py`, `assembly.py`, `env.py`, `environment_schema.py`, `loader.py`, `models.py`, `profiles.py`, and `validation.py`.
- End with zero explicit `Any` name nodes in `rag_modules.configuration`, `rag_modules.contracts`, and `rag_modules.kernel`; do not substitute unbounded casts, dynamic `getattr`, ignored type errors, or another escape hatch.
- Retain only `BuildJobRepositoryPort` and `BuildJobRunnerPort` among protocols in the wave scope.
- Keep the post-wave repository at or below 380 production Python files, 152 protocols, 64 sub-60-line non-package modules, and 209 explicit `Any` name nodes.
- Add or update focused tests before each behavior change; run the narrowest relevant tests before broad gates.
- Keep historical approved specs and plans unchanged except for status/evidence appended to the design for this implementation.

---

## File Structure

### New Files

- `rag_modules/configuration/environment_schema.py`: all environment field declarations and `EnvFieldSpec`.
- `tests/configuration_test_helpers.py`: deterministic configuration construction used only by tests.

### Production Files Deleted

- `rag_modules/configuration/env_specs/__init__.py`
- `rag_modules/configuration/env_specs/api.py`
- `rag_modules/configuration/env_specs/base.py`
- `rag_modules/configuration/env_specs/generation.py`
- `rag_modules/configuration/env_specs/graph.py`
- `rag_modules/configuration/env_specs/models.py`
- `rag_modules/configuration/env_specs/observability.py`
- `rag_modules/configuration/env_specs/query_understanding.py`
- `rag_modules/configuration/env_specs/retrieval.py`
- `rag_modules/configuration/env_specs/storage.py`
- `rag_modules/configuration/model_sections/__init__.py`
- `rag_modules/configuration/model_sections/api.py`
- `rag_modules/configuration/model_sections/base.py`
- `rag_modules/configuration/model_sections/generation.py`
- `rag_modules/configuration/model_sections/graph.py`
- `rag_modules/configuration/model_sections/models.py`
- `rag_modules/configuration/model_sections/observability.py`
- `rag_modules/configuration/model_sections/query_understanding.py`
- `rag_modules/configuration/model_sections/retrieval.py`
- `rag_modules/configuration/model_sections/storage.py`
- `rag_modules/configuration/sections/__init__.py`
- `rag_modules/configuration/sections/api.py`
- `rag_modules/configuration/sections/common.py`
- `rag_modules/configuration/sections/generation.py`
- `rag_modules/configuration/sections/graph.py`
- `rag_modules/configuration/sections/models.py`
- `rag_modules/configuration/sections/observability.py`
- `rag_modules/configuration/sections/retrieval.py`
- `rag_modules/configuration/sections/storage.py`
- `rag_modules/configuration/errors.py`
- `rag_modules/configuration/testing.py`
- `rag_modules/contracts/_common.py`
- `rag_modules/contracts/query.py`
- `rag_modules/contracts/query_utils.py`
- `rag_modules/contracts/retrieval.py`
- `rag_modules/contracts/langchain_compat.py`
- `rag_modules/contracts/runtime/snapshot_utils.py`
- `rag_modules/contracts/build_jobs/executor.py`
- `rag_modules/kernel/artifact_validation.py`

### Canonical Owners Modified

- `rag_modules/configuration/{__init__,assembly,env,loader,models,profiles,validation}.py`
- `rag_modules/kernel/{artifacts,documents,json_types,time_parsing}.py`
- `rag_modules/contracts/{__init__,query_constraints,query_plan,query_semantics,query_settings,query_types,request_control,retrieval_documents,retrieval_request}.py`
- `rag_modules/contracts/build_jobs/{__init__,events,models}.py`
- `rag_modules/contracts/runtime/{analysis,generation,graph,retrieval,routing}.py`
- `rag_modules/langchain_document_adapter.py`
- `rag_modules/app/build_jobs/service.py`

### Downstream Migration Areas

- `rag_modules/evidence_processing/`
- `rag_modules/generation/context_factory.py`
- `rag_modules/observability/{retrieval_snapshots,tracing_event_builder}.py`
- `rag_modules/retrieval/`, especially adapters, candidate generation, fusion, parent-document enrichment, and hybrid search
- `rag_modules/graph/{path_ranker,retrieval_postprocess}.py`
- `rag_modules/routing/`
- `rag_modules/app/composition/serving_runtime_preparer.py`
- `rag_modules/build_pipeline/vector_reuse.py`
- `scripts/` and `tests/` imports of retired configuration/document helpers

---

### Task 1: Converge Configuration Models and Environment Schema

**Files:**

- Create: `rag_modules/configuration/environment_schema.py`
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/env.py`
- Test: `tests/test_configuration_defaults.py`
- Test: `tests/test_configuration_profiles.py`
- Test: `tests/test_query_understanding_config.py`
- Delete: every file under `rag_modules/configuration/env_specs/`
- Delete: every file under `rag_modules/configuration/model_sections/`

**Interfaces:**

- Produces: `EnvValueKind`, `EnvFieldSpec`, `ENV_FIELD_SPECS` from `rag_modules.configuration.environment_schema`.
- Produces: every settings class with `__module__ == "rag_modules.configuration.models"`.
- Consumes: existing environment names and Pydantic field definitions without changing defaults or validation rules.

- [ ] **Step 1: Write failing ownership tests**

Add these assertions to `tests/test_configuration_defaults.py`:

```python
from rag_modules.configuration.environment_schema import ENV_FIELD_SPECS, EnvFieldSpec
from rag_modules.configuration.models import (
    ApiSettings,
    GenerationSettings,
    GraphSettings,
    ModelSettings,
    ObservabilitySettings,
    QueryUnderstandingSettings,
    RetrievalSettings,
    StorageSettings,
)


def test_configuration_declarations_have_canonical_owners() -> None:
    section_types = (
        ApiSettings,
        GenerationSettings,
        GraphSettings,
        ModelSettings,
        ObservabilitySettings,
        QueryUnderstandingSettings,
        RetrievalSettings,
        StorageSettings,
    )
    assert {section_type.__module__ for section_type in section_types} == {
        "rag_modules.configuration.models"
    }
    assert EnvFieldSpec.__module__ == "rag_modules.configuration.environment_schema"
    assert ENV_FIELD_SPECS["TOP_K"].path == ("retrieval", "top_k")
```

- [ ] **Step 2: Run the ownership test and verify it fails**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py::test_configuration_declarations_have_canonical_owners -q
```

Expected: FAIL because `environment_schema.py` does not exist and settings classes are still owned by `model_sections`.

- [ ] **Step 3: Make `models.py` the sole settings owner**

Move definitions into `models.py` in this dependency order, preserving each current field, default, validator, and method exactly before converting types in Task 4:

```text
model_sections.base.ConfigSection
model_sections.api.ApiSettings
model_sections.generation.GenerationSettings
model_sections.graph.GraphSettings
model_sections.models.ModelSettings
model_sections.observability.ObservabilitySettings
model_sections.query_understanding.*
model_sections.retrieval.RetrievalSettings
model_sections.storage.StorageSettings
existing DomainSettings and GraphRAGConfig definitions from models.py
```

Remove `from .model_sections import ...`; define `CONFIG_SECTION_TYPES` directly from the local classes. Preserve the existing `__all__` names, then delete the ten `model_sections` files.

- [ ] **Step 4: Build the single environment schema**

Create `environment_schema.py` with the existing `EnvValueKind`, `EnvFieldSpec`, and `spec()` definitions followed by every declaration currently in the section files, in this deterministic group order:

```python
ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    *API_ENV_FIELD_SPECS,
    *GENERATION_ENV_FIELD_SPECS,
    *GRAPH_ENV_FIELD_SPECS,
    *MODEL_ENV_FIELD_SPECS,
    *OBSERVABILITY_ENV_FIELD_SPECS,
    *QUERY_UNDERSTANDING_ENV_FIELD_SPECS,
    *RETRIEVAL_ENV_FIELD_SPECS,
    *STORAGE_ENV_FIELD_SPECS,
)

__all__ = ["ENV_FIELD_SPECS", "EnvFieldSpec", "EnvValueKind"]
```

Use the existing tuples unchanged as private constants in the new module. In `env.py`, replace both `env_specs` imports with:

```python
from .environment_schema import ENV_FIELD_SPECS as _ENV_FIELD_SPEC_GROUPS
from .environment_schema import EnvFieldSpec, EnvValueKind
```

Delete the ten `env_specs` files.

- [ ] **Step 5: Run focused configuration tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_query_understanding_config.py tests/test_domain_packs.py -q
```

Expected: PASS with unchanged default, profile, environment, and domain behavior.

- [ ] **Step 6: Commit the declaration convergence**

```powershell
git add rag_modules/configuration tests/test_configuration_defaults.py
git commit -m "refactor: converge configuration declarations"
```

---

### Task 2: Retire the Parallel Configuration Surface and Production Test Helpers

**Files:**

- Create: `tests/configuration_test_helpers.py`
- Modify: `rag_modules/configuration/{__init__,env,loader,validation}.py`
- Modify: all tests importing `rag_modules.configuration.testing`
- Modify: `scripts/pressure/runner.py`
- Modify: `scripts/smoke_answer_pipeline.py`
- Modify: `scripts/smoke_answer_pipeline_real_route.py`
- Modify: `scripts/smoke_answer_pipeline_support.py`
- Modify: `scripts/smoke_route_queries.py`
- Modify: `tests/test_configuration_profiles.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `tests/public_surface_boundary_helpers.py`
- Delete: `rag_modules/configuration/sections/`
- Delete: `rag_modules/configuration/errors.py`
- Delete: `rag_modules/configuration/testing.py`

**Interfaces:**

- Produces: `ConfigurationError` and `ConfigErrorDetail` directly from `configuration.validation`, re-exported only by `configuration.__init__`.
- Produces: test-only `build_test_config()` in `tests.configuration_test_helpers`.
- Retires: section loaders, `CONFIG_PROFILE*`, `GRAPH_RAG_API_TOKEN`, and all exact deleted module paths.

- [ ] **Step 1: Write failing hard-retirement tests**

Replace the section-loader export test in `tests/test_module_boundary_facades.py` with:

```python
def test_configuration_fragment_packages_are_retired(self) -> None:
    retired = (
        "rag_modules.configuration.env_specs",
        "rag_modules.configuration.model_sections",
        "rag_modules.configuration.sections",
        "rag_modules.configuration.errors",
        "rag_modules.configuration.testing",
    )
    for module_name in retired:
        parent_name, attr_name = module_name.rsplit(".", 1)
        parent = importlib.import_module(parent_name)
        sys.modules.pop(module_name, None)
        if hasattr(parent, attr_name):
            delattr(parent, attr_name)
        with self.subTest(module=module_name):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)
```

Add to `tests/test_configuration_profiles.py`:

```python
def test_legacy_profile_environment_names_are_ignored() -> None:
    config = load_config(
        source=EnvConfigSource(
            environ={
                "CONFIG_PROFILE": "quality",
                "CONFIG_PROFILE_PATH": "missing.toml",
                "CONFIG_PROFILES_DIR": "missing-profiles",
            }
        )
    )
    assert config.profile_name == "base"


def test_undocumented_api_token_alias_is_ignored() -> None:
    config = load_config(source=EnvConfigSource(environ={"GRAPH_RAG_API_TOKEN": "legacy-token"}))
    assert config.api.access_token == ""
```

- [ ] **Step 2: Run the retirement tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py::ModuleBoundaryFacadeTests::test_configuration_fragment_packages_are_retired tests/test_configuration_profiles.py::test_legacy_profile_environment_names_are_ignored tests/test_configuration_profiles.py::test_undocumented_api_token_alias_is_ignored -q
```

Expected: FAIL because the packages exist and legacy aliases still load.

- [ ] **Step 3: Move error ownership and delete section loaders**

Move `ConfigErrorDetail` and `ConfigurationError` unchanged above the formatting helpers in `validation.py`. Update `configuration.__init__` to import both from `.validation`, update internal imports, and delete `errors.py` and all nine `sections` files.

Change the profile selection in `loader.py` to canonical variables only:

```python
resolved_profile = load_profile(
    profile=profile or env_source.get_first("GRAPH_RAG_PROFILE"),
    profile_path=profile_path or env_source.get_first("GRAPH_RAG_PROFILE_PATH"),
    profiles_dir=profiles_dir or env_source.get_first("GRAPH_RAG_PROFILES_DIR"),
)
```

Remove `GRAPH_RAG_API_TOKEN` from the API access-token `EnvFieldSpec`. Delete unused `get_int_alias()` and `get_float_alias()` methods from `EnvConfigSource`.

- [ ] **Step 4: Move deterministic config construction out of production**

Create `tests/configuration_test_helpers.py` with this interface:

```python
from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
from rag_modules.configuration.models import GraphRAGConfig
from rag_modules.kernel.json_types import JsonObject, coerce_json_object

_EMPTY_ENV_SOURCE = EnvConfigSource(environ={})


def build_test_config(overrides: Mapping[str, object] | None = None) -> GraphRAGConfig:
    store = Path(tempfile.gettempdir()) / f"graph-rag-c9-build-jobs-{uuid4().hex}" / "jobs.json"
    payload: JsonObject = {"storage": {"build_job_store_path": str(store)}}
    for section, values in coerce_json_object(overrides).items():
        if isinstance(values, dict) and isinstance(payload.get(section), dict):
            payload[section].update(values)
        else:
            payload[section] = values
    return load_config(overrides=payload, source=_EMPTY_ENV_SOURCE)


__all__ = ["build_test_config"]
```

Update tests to import `build_test_config` from this test helper. Replace `planner_runtime_settings(config)` and `semantic_runtime_settings(config)` calls with `QueryPlannerRuntimeSettings.from_config(config)` and `QuerySemanticRuntimeSettings.from_config(config)`.

Operational scripts must call `load_config(source=EnvConfigSource(environ={}), overrides=...)` directly. The answer smoke scripts may share a private `build_smoke_config()` inside the existing `smoke_answer_pipeline_support.py`; do not add a production or new one-function support module.

Delete `configuration/testing.py`.

- [ ] **Step 5: Update retired-path registries and run configuration tests**

Add every retired configuration path to `RETIRED_INTERNAL_COMPAT_SHELLS` in `tests/public_surface_boundary_helpers.py`. Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_query_understanding_config.py tests/test_module_boundary_facades.py tests/test_public_surface_boundaries.py -q
```

Expected: PASS, with exact old imports failing.

- [ ] **Step 6: Commit the single configuration path**

```powershell
git add rag_modules/configuration scripts tests
git commit -m "refactor: retire parallel configuration surfaces"
```

---

### Task 3: Make Kernel the Typed Primitive and Artifact Owner

**Files:**

- Modify: `rag_modules/kernel/json_types.py`
- Modify: `rag_modules/kernel/artifacts.py`
- Modify: `rag_modules/kernel/documents.py`
- Modify: `rag_modules/kernel/time_parsing.py`
- Modify: `rag_modules/build_pipeline/vector_reuse.py`
- Modify: `rag_modules/app/composition/serving_runtime_preparer.py`
- Modify: `tests/test_kernel_contracts.py`
- Modify: artifact manifest/vector reuse tests
- Delete: `rag_modules/kernel/artifact_validation.py`
- Delete: `rag_modules/contracts/_common.py`
- Delete: `rag_modules/contracts/query_utils.py`

**Interfaces:**

- Produces: JSON aliases and all primitive coercion helpers from `kernel.json_types`.
- Produces: `vector_artifact_mismatch_reason()` and `vector_artifacts_compatible()` from `kernel.artifacts`.
- Produces: `ArtifactManifest.evolve(**changes: Unpack[ArtifactManifestUpdate])` with a typed update map.

- [ ] **Step 1: Write failing kernel ownership tests**

Add to `tests/test_kernel_contracts.py`:

```python
from rag_modules.kernel.artifacts import vector_artifact_mismatch_reason
from rag_modules.kernel.json_types import as_string_list, clamp_float, coerce_str


def test_kernel_owns_shared_primitive_normalization() -> None:
    assert coerce_str(None) == ""
    assert as_string_list([" a ", "", 2]) == ["a", "2"]
    assert clamp_float("2.0") == 1.0
    assert vector_artifact_mismatch_reason.__module__ == "rag_modules.kernel.artifacts"
```

Add `rag_modules.kernel.artifact_validation` to the retired import test.

- [ ] **Step 2: Run the kernel test and verify it fails**

Run:

```powershell
python -m pytest tests/test_kernel_contracts.py -q
```

Expected: FAIL because normalization functions and artifact checks still have fragmented owners.

- [ ] **Step 3: Consolidate primitive coercion without dynamic lookup**

Move `coerce_str`, `coerce_float`, `coerce_int`, `bounded_float`, list normalization, integer/float clamping, and order-preserving dedupe into `kernel/json_types.py`. Use `object` ingress and narrow before numeric conversion:

```python
def coerce_float(value: object, default: float = 0.0) -> float:
    if not isinstance(value, (bool, int, float, str)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []
```

Remove the `getattr(value, "to_dict", None)` path from `coerce_json_value`; callers serialize typed DTOs before coercion. Update contract imports, then delete `_common.py` and `query_utils.py`.

- [ ] **Step 4: Merge artifact validation and type kernel DTOs**

Move both vector compatibility functions unchanged into `kernel/artifacts.py` and update imports in serving preparation and vector reuse.

Replace `ArtifactManifest.evolve(**changes: Any)` with a `TypedDict(total=False)` named `ArtifactManifestUpdate` and `Unpack[ArtifactManifestUpdate]`. Type manifest metadata and emitted payloads with `JsonObject`/`JsonValue`. In `documents.py`, type metadata as `JsonObject`, remove generic `copy_with`, and type `from_dict()` with `Mapping[str, object] | None`. Change `parse_minutes(value: Any)` to `parse_minutes(value: object)`.

Delete `artifact_validation.py`.

- [ ] **Step 5: Run kernel and artifact tests**

Run:

```powershell
python -m pytest tests/test_kernel_contracts.py tests/test_build_pipeline_manifest_lifecycle.py tests/test_artifact_registry_hot_refresh.py tests/test_serving_runtime_preparer_branches.py tests/test_milvus_blue_green.py -q
```

Expected: PASS with unchanged artifact compatibility decisions.

- [ ] **Step 6: Commit kernel convergence**

```powershell
git add rag_modules/kernel rag_modules/contracts rag_modules/build_pipeline/vector_reuse.py rag_modules/app/composition/serving_runtime_preparer.py tests
git commit -m "refactor: converge typed kernel primitives"
```

---

### Task 4: Remove Contract Facades and Explicit Any

**Files:**

- Modify: `rag_modules/contracts/__init__.py`
- Modify: `rag_modules/contracts/query_constraints.py`
- Modify: `rag_modules/contracts/query_plan.py`
- Modify: `rag_modules/contracts/query_semantics.py`
- Modify: `rag_modules/contracts/query_settings.py`
- Modify: `rag_modules/contracts/query_types.py`
- Modify: `rag_modules/contracts/request_control.py`
- Modify: `rag_modules/contracts/retrieval_request.py`
- Modify: `rag_modules/contracts/runtime/analysis.py`
- Modify: `rag_modules/contracts/build_jobs/{__init__,events,models}.py`
- Modify: `rag_modules/app/build_jobs/service.py`
- Modify: all callers of `RetrievalRequest.copy_with()`
- Delete: `rag_modules/contracts/query.py`
- Delete: `rag_modules/contracts/retrieval.py`
- Delete: `rag_modules/contracts/build_jobs/executor.py`
- Test: contract, query, request-control, build-job, and type-contract tests

**Interfaces:**

- Produces: package exports directly from owner modules.
- Produces: `_CancellationState` shared by parent/child `RequestControl` instances.
- Produces: build-job execution behavior from `app.build_jobs.service`, while `contracts.build_jobs` owns only events, models, errors, reducer logic, and ports.

- [ ] **Step 1: Write failing contract-boundary tests**

Add retired import assertions for `rag_modules.contracts.query`, `rag_modules.contracts.retrieval`, and `rag_modules.contracts.build_jobs.executor` to `tests/test_module_boundary_facades.py`.

Add to `tests/test_runtime_retrieval_models.py`:

```python
def test_request_control_shares_typed_cancellation_state() -> None:
    parent = RequestControl.for_timeout(5.0)
    child = parent.child(2.0, scope="child")
    parent.cancel("manual")
    assert child.cancelled is True
    assert child.reason == "manual"
    assert not hasattr(parent.cancel_event, "_request_control_reason")
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py tests/test_runtime_retrieval_models.py -q
```

Expected: FAIL because the facades/executor exist and cancellation reason is stored dynamically on the event.

- [ ] **Step 3: Retire query/retrieval facades and normalize JSON types**

Make `contracts.__init__` import directly from `query_plan`, `query_semantics`, `query_types`, `retrieval_documents`, and `retrieval_request`; delete `query.py` and `retrieval.py` and migrate the one direct `contracts.retrieval` caller.

Apply these exact typing rules across the listed contract files:

```text
unvalidated dictionaries accepted by from_dict -> Mapping[str, object] | None
open metadata/result/trace objects -> JsonObject
open nested values -> JsonValue
string-list coercion -> as_string_list(object)
enum coercion -> object ingress with isinstance narrowing
serialized return values -> JsonObject
```

Delete `RetrievalRequest.copy_with(**Any)` and update callers to use `dataclasses.replace(request, ...)`. Migrate every current keyword set: `control`, `metadata`, `entity_keywords`, `topic_keywords`, `constraints`, `candidate_k`, and `top_k/candidate_k/strategy`.

- [ ] **Step 4: Replace dynamic cancellation state**

Implement the shared state in `request_control.py`:

```python
@dataclass(slots=True)
class _CancellationState:
    event: threading.Event = field(default_factory=threading.Event)
    reason: str = ""


@dataclass(slots=True)
class RequestControl:
    deadline: float
    scope: str = "request"
    _state: _CancellationState = field(default_factory=_CancellationState, repr=False)
    _parent: RequestControl | None = field(default=None, repr=False)

    @property
    def cancel_event(self) -> threading.Event:
        return self._state.event
```

`child()` shares `_state`; `isolated_child()` creates a fresh state and points to `_parent`; `cancel()` assigns `_state.reason` and sets the event. Remove all `getattr`/`setattr` calls.

- [ ] **Step 5: Move build-job execution to the application owner**

Move `BuildJobExecutor`, `BuildJobRuntimeHooks`, progress formatting, and safe-stage mapping into `app/build_jobs/service.py`. Replace JSON-shaped hook results with `JsonObject`. Type the system collaborator with the existing app-owned application protocol instead of `Any`. Update composition and runner imports, make `contracts.build_jobs.__init__` stop exporting executor symbols, and delete `contracts/build_jobs/executor.py`.

Type build-job event/results as `JsonObject` and implement `_value_to_json(value: object) -> JsonValue` with explicit datetime, mapping, sequence, scalar, and enum branches.

- [ ] **Step 6: Run contract and build-job tests**

Run:

```powershell
python -m pytest tests/test_runtime_retrieval_models.py tests/test_query_semantics.py tests/test_query_policy_injection.py tests/test_build_job_domain.py tests/test_build_job_composition.py tests/test_build_job_persistence.py tests/test_build_job_external_worker.py -q
```

Expected: PASS with unchanged request cancellation and build-job behavior.

- [ ] **Step 7: Commit contract ownership and typing**

```powershell
git add rag_modules/contracts rag_modules/app/build_jobs rag_modules/routing rag_modules/retrieval tests
git commit -m "refactor: converge contract ownership and types"
```

---

### Task 5: Normalize Documents and Retire Recipe Compatibility

**Files:**

- Modify: `rag_modules/langchain_document_adapter.py`
- Modify: `rag_modules/contracts/{__init__,retrieval_documents}.py`
- Modify: `rag_modules/evidence_processing/`
- Modify: `rag_modules/generation/context_factory.py`
- Modify: `rag_modules/observability/{retrieval_snapshots,tracing_event_builder}.py`
- Modify: relevant graph, retrieval, routing, script, evaluation, and test callers
- Modify: `tests/test_langchain_document_boundary.py`
- Modify: `tests/test_domain_packs.py`
- Delete: `rag_modules/contracts/langchain_compat.py`

**Interfaces:**

- Produces: `evidence_document_from_text_document(TextDocument) -> EvidenceDocument` in `contracts.retrieval_documents`.
- Produces: LangChain conversions only from `rag_modules.langchain_document_adapter`.
- Retires: both `PageDocumentLike` protocols, `ensure_evidence_documents`, `evidence_document_from_page_like`, generic `EvidenceDocument.copy_with`, and deprecated recipe aliases.

- [ ] **Step 1: Write failing document-boundary tests**

Change `tests/test_langchain_document_boundary.py` to:

```python
ALLOWED_IMPORTERS = {Path("rag_modules/langchain_document_adapter.py")}


def test_page_document_protocols_are_retired() -> None:
    import rag_modules.contracts as contracts
    import rag_modules.evidence_processing as evidence_processing

    assert not hasattr(contracts, "PageDocumentLike")
    assert not hasattr(evidence_processing, "PageDocumentLike")
```

Replace the recipe compatibility test in `tests/test_domain_packs.py` with:

```python
def test_evidence_contract_rejects_deprecated_recipe_aliases() -> None:
    with pytest.raises(TypeError):
        EvidenceDocument(content="legacy", recipe_id="r1", recipe_name="Mapo tofu")

    evidence = EvidenceDocument(
        content="canonical",
        entity_id="r1",
        entity_name="Mapo tofu",
        domain_graph_evidence={"kind": "recipe"},
    )
    assert "recipe_id" not in evidence.to_dict()
    assert "recipe_name" not in evidence.to_dict()
    assert "recipe_graph_evidence" not in evidence.to_dict()
```

- [ ] **Step 2: Run document tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_langchain_document_boundary.py tests/test_domain_packs.py -q
```

Expected: FAIL because both protocols and deprecated aliases remain.

- [ ] **Step 3: Make document conversions concrete**

In `retrieval_documents.py`, replace page-like conversion with this complete canonical mapping:

```python
def evidence_document_from_text_document(document: TextDocument) -> EvidenceDocument:
    metadata = coerce_json_object(document.metadata)
    raw_evidence_units = metadata.get("evidence_units")
    return EvidenceDocument(
        content=document.content,
        entity_id=coerce_str(
            metadata.get("entity_id")
            or metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        entity_name=coerce_str(
            metadata.get("entity_name") or metadata.get("recipe_name") or metadata.get("name")
        ),
        entity_type=coerce_str(metadata.get("entity_type") or metadata.get("node_type")),
        node_id=coerce_str(
            metadata.get("node_id")
            or metadata.get("entity_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        node_type=coerce_str(metadata.get("node_type") or metadata.get("entity_type")),
        score=coerce_float(
            metadata.get("final_score")
            or metadata.get("relevance_score")
            or metadata.get("constraint_score")
            or metadata.get("score")
            or metadata.get("bm25_score")
        ),
        search_type=coerce_str(metadata.get("search_type")),
        search_method=coerce_str(
            metadata.get("search_method") or metadata.get("search_source")
        ),
        retrieval_level=coerce_str(metadata.get("retrieval_level")),
        doc_id=coerce_str(metadata.get("doc_id")),
        source=coerce_str(
            metadata.get("source")
            or metadata.get("search_source")
            or metadata.get("search_method")
            or metadata.get("search_type")
            or "unknown"
        ),
        evidence_type=coerce_str(
            metadata.get("evidence_type")
            or metadata.get("search_type")
            or ("recipe" if metadata.get("recipe_name") else "text")
        ),
        matched_terms=matched_terms_from_metadata(metadata),
        graph_evidence=coerce_json_object(metadata.get("graph_evidence")),
        domain_graph_evidence=coerce_json_object(metadata.get("domain_graph_evidence")),
        constraint_evidence=coerce_json_object(metadata.get("constraint_evidence")),
        evidence_units=[
            coerce_json_object(item)
            for item in (
                raw_evidence_units if isinstance(raw_evidence_units, list) else []
            )
            if isinstance(item, Mapping)
        ],
        route_strategy=coerce_str(metadata.get("route_strategy")),
        metadata=metadata,
    )
```

Update `langchain_document_adapter` so `Document` first converts to `TextDocument`, then to `EvidenceDocument` when required.

Delete both protocols and make evidence-processing/generation APIs accept `Sequence[EvidenceDocument]`. Explicit adapter/retriever boundaries convert `TextDocument` before calling them.

- [ ] **Step 4: Remove deprecated recipe fields and generic copying**

Remove recipe constructor parameters, properties, `_legacy_recipe_compat`, and conditional legacy keys from `EvidenceDocument`. Migrate production and tests as follows:

```text
EvidenceDocument.recipe_id -> entity_id
EvidenceDocument.recipe_name -> entity_name
EvidenceDocument.recipe_graph_evidence -> domain_graph_evidence
```

Do not rename domain-owned evaluation/API fields whose real schema is `recipe_name`.

Delete `EvidenceDocument.copy_with(**Any)`. Replace callers with `dataclasses.replace(document, ...)`, using canonical fields; change parent-document and dual-level code from `recipe_name`/`recipe_id` keyword updates to `entity_name`/`entity_id`.

- [ ] **Step 5: Delete the LangChain compatibility module and run the migration slice**

Run:

```powershell
python -m pytest tests/test_langchain_document_boundary.py tests/test_domain_packs.py tests/test_answer_evidence_builder.py tests/test_generation_context_factory.py tests/test_graph_path_ranker.py tests/test_graph_retrieval_adapters.py tests/test_dual_level_retriever.py tests/test_parent_doc_enricher.py tests/test_hybrid_search_service.py tests/test_eval_queries.py -q
```

Expected: PASS with canonical entity fields and a single LangChain import boundary.

- [ ] **Step 6: Commit document normalization**

```powershell
git add rag_modules scripts tests
git commit -m "refactor: normalize document boundaries"
```

---

### Task 6: Move Snapshot Copying to DTOs and Remove Candidate View Protocol

**Files:**

- Modify: `rag_modules/contracts/runtime/{generation,graph,retrieval,routing}.py`
- Modify: `rag_modules/application/answering/{answer_trace_assembler,trace_adapters}.py`
- Modify: `rag_modules/observability/tracing_event_builder.py`
- Modify: `rag_modules/retrieval/hybrid_search_service.py`
- Modify: `tests/test_contract_snapshot_utils.py`
- Modify: `tests/typecheck/type_contracts.py`
- Delete: `rag_modules/contracts/runtime/snapshot_utils.py`

**Interfaces:**

- Produces: `RouteSnapshot.copy(semantic_settings=...)`, `GraphRetrievalSnapshot.copy(semantic_settings=...)`, and `GenerationSnapshot.copy()`.
- Retires: arbitrary-value snapshot clone helpers and `_CandidateSetView`.
- Produces: direct `HybridRetrievalOutcome(...)` construction from documents, counts, degraded details, and metadata.

- [ ] **Step 1: Rewrite snapshot tests against DTO ownership**

Change `tests/test_contract_snapshot_utils.py` to import only concrete DTOs and assert:

```python
def test_route_snapshot_copy_returns_detached_instance(self) -> None:
    original = RouteSnapshot(query="q", strategy="combined")
    copied = original.copy(semantic_settings=self.semantic_settings)
    self.assertEqual(copied, original)
    self.assertIsNot(copied, original)


def test_graph_mapping_deserializes_at_boundary(self) -> None:
    snapshot = GraphRetrievalSnapshot.from_dict(
        {"query": "q", "doc_count": 2, "path_count": 1},
        semantic_settings=self.semantic_settings,
    )
    self.assertEqual(snapshot.doc_count, 2)


def test_generation_snapshot_copy_returns_detached_instance(self) -> None:
    original = GenerationSnapshot(mode="direct", total_evidence_items=2)
    copied = original.copy()
    self.assertEqual(copied, original)
    self.assertIsNot(copied, original)
```

- [ ] **Step 2: Run snapshot and hybrid tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_contract_snapshot_utils.py tests/test_hybrid_search_service.py tests/test_runtime_retrieval_models.py -q
```

Expected: FAIL because DTO copy methods do not exist and candidate construction still requires `_CandidateSetView`.

- [ ] **Step 3: Add typed DTO copy methods and migrate callers**

Implement copies through existing serialization contracts:

```python
def copy(self, *, semantic_settings: QuerySemanticRuntimeSettings) -> Self:
    return type(self).from_dict(self.to_dict(), semantic_settings=semantic_settings)
```

Use the same form for route and graph snapshots; generation uses `return type(self).from_dict(self.to_dict())`. Callers that receive mappings invoke `from_dict()` at their input boundary; callers with a concrete snapshot invoke `.copy()`. Delete `snapshot_utils.py` and its imports.

- [ ] **Step 4: Remove candidate object protocol**

Delete `_CandidateSetView` and `HybridRetrievalOutcome.from_candidate_set()`. In `hybrid_search_service.py`, construct the DTO directly:

```python
return HybridRetrievalOutcome(
    documents=list(documents),
    candidate_counts=dict(candidates.stats),
    degraded_candidates=[coerce_json_object(item) for item in candidates.degraded_details],
    metadata=coerce_json_object(metadata),
)
```

Update `tests/typecheck/type_contracts.py` to construct the DTO with `candidate_counts` and `degraded_candidates`; remove its fake candidate view.

- [ ] **Step 5: Run snapshot, answer, tracing, and retrieval tests**

Run:

```powershell
python -m pytest tests/test_contract_snapshot_utils.py tests/test_answer_workflow.py tests/test_answer_response_mapping.py tests/test_query_tracer.py tests/test_route_trace_recorder.py tests/test_hybrid_search_service.py tests/test_runtime_retrieval_models.py -q
```

Expected: PASS with detached snapshots and unchanged degradation metadata.

- [ ] **Step 6: Commit DTO-owned copying and candidate data flow**

```powershell
git add rag_modules tests
git commit -m "refactor: move runtime normalization to DTO owners"
```

---

### Task 7: Enforce Package-Wide Type and Abstraction Ratchets

**Files:**

- Modify: `tests/test_abstraction_ratchets.py`
- Modify: `tests/test_type_contract_ratchets.py`
- Modify: `tests/public_surface_boundary_helpers.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `pyproject.toml`
- Modify: `docs/architecture.md`
- Modify: `docs/public_surface_retirement_plan.md`

**Interfaces:**

- Produces: exact protocol rationale and short-module responsibility registries.
- Produces: package-wide no-`Any` and strict-mypy coverage for configuration, contracts, and kernel.
- Produces: final AST ceilings at or below the approved acceptance values.

- [ ] **Step 1: Add failing final structural assertions**

In `test_type_contract_ratchets.py`, add configuration, contracts, and kernel to `NO_EXPLICIT_ANY_PACKAGE_TARGETS` and `STRICT_PACKAGE_TARGETS`:

```python
NO_EXPLICIT_ANY_PACKAGE_TARGETS = (
    *NO_EXPLICIT_ANY_PACKAGE_TARGETS,
    ROOT / "rag_modules" / "configuration",
    ROOT / "rag_modules" / "contracts",
    ROOT / "rag_modules" / "kernel",
)
```

Refactor the constant rather than self-reference in actual code: define a single tuple containing all prior entries plus these three.

In `test_abstraction_ratchets.py`, set ceilings no higher than:

```python
MAX_PRODUCTION_PROTOCOLS = 152
MAX_PRODUCTION_MODULES_UNDER_60_LINES = 64
MAX_PRODUCTION_ANY_NAME_NODES = 209
MAX_PRODUCTION_PYTHON_FILES = 380
```

Add an exact scoped protocol registry:

```python
APPROVED_FOUNDATION_PROTOCOLS = {
    Path("rag_modules/contracts/build_jobs/ports.py"): frozenset(
        {"BuildJobRepositoryPort", "BuildJobRunnerPort"}
    )
}
```

Add a scoped short-module responsibility map for `contracts/graph.py`,
`contracts/build_jobs/errors.py`, `contracts/runtime/policy.py`, and the four retained short kernel
modules. Assert that actual scoped short modules exactly match the map.

- [ ] **Step 2: Run structural tests and verify remaining violations**

Run:

```powershell
python -m pytest tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py tests/test_module_boundary_facades.py tests/test_public_surface_boundaries.py -q
```

Expected before final cleanup: FAIL and print any surviving `Any`, protocol, short module, retired import, or metric overage. Treat each printed item as migration work; do not raise a ceiling.

- [ ] **Step 3: Close every printed structural violation**

For each explicit `Any` remaining in the three packages, apply the design mapping (`object` ingress, `JsonObject` output, concrete DTO for known shape). For each pure forwarding function, move callers to its target and delete it. For each unexpected short module, merge it into its responsibility owner or document why it belongs in one of the already approved retained modules; do not add a new exception in this wave.

- [ ] **Step 4: Normalize mypy configuration**

Ensure the strict override contains exactly these package patterns in addition to existing unrelated targets:

```toml
"rag_modules.configuration",
"rag_modules.configuration.*",
"rag_modules.contracts",
"rag_modules.contracts.*",
"rag_modules.kernel",
"rag_modules.kernel.*",
```

Remove redundant leaf entries covered by these wildcards. Keep `disallow_untyped_defs = true` and `ignore_missing_imports = false`; do not weaken global flags.

- [ ] **Step 5: Update architecture and retirement documentation**

Record the eight-module configuration layout, single loader flow, retired module paths, LangChain normalization boundary, removed recipe aliases, and the two retained build-job ports. State that exact old imports fail.

- [ ] **Step 6: Run structural, mypy, and formatting gates**

Run:

```powershell
python -m pytest tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py tests/test_module_boundary_facades.py tests/test_public_surface_boundaries.py tests/test_import_dag.py -q
python -m mypy --config-file pyproject.toml
python -m ruff check rag_modules scripts tests
python -m ruff format --check rag_modules scripts tests
```

Expected: all commands exit 0.

- [ ] **Step 7: Commit ratchets and documentation**

```powershell
git add pyproject.toml rag_modules scripts tests docs/architecture.md docs/public_surface_retirement_plan.md
git commit -m "test: ratchet foundational abstraction convergence"
```

---

### Task 8: Run Full Release Verification and Record Evidence

**Files:**

- Modify: `tests/test_abstraction_ratchets.py` only if fresh measured values are lower than the approved ceilings
- Modify: `docs/superpowers/specs/2026-07-22-configuration-contract-kernel-convergence-design.md`

**Interfaces:**

- Produces: fresh before/after metrics and a final retained-abstraction list.
- Consumes: the complete implementation from Tasks 1–7.

- [ ] **Step 1: Measure the final repository with the ratchet's AST functions**

Run:

```powershell
python -m pytest tests/test_abstraction_ratchets.py -q
python -m pytest tests/test_type_contract_ratchets.py -q
```

Use the exact emitted/measured values to lower every ceiling below its design maximum. Do not leave unused headroom.

- [ ] **Step 2: Run the API slice required by AGENTS.md**

```powershell
python -m pytest tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q
```

Expected: PASS.

- [ ] **Step 3: Run complete static and test gates**

```powershell
python -m mypy --config-file pyproject.toml
python -m ruff check rag_modules scripts tests
python -m ruff format --check rag_modules scripts tests
python -m pytest -q
```

Expected: all commands exit 0 with zero failures.

- [ ] **Step 4: Run release-sensitive verification**

```powershell
python scripts/release_gate.py
git diff --check
```

Expected: release gate passes and diff check emits no errors.

- [ ] **Step 5: Record implementation evidence**

Append an `Implementation Evidence` section to the approved design containing:

```text
implementation commit(s)
production Python files before and after
Protocol declarations before and after
sub-60-line modules before and after
Any name nodes before and after
retained protocols with rationale
retained scoped short modules with responsibility
every verification command and result
```

Set the design status to `implemented` only after all commands in Steps 2–4 exit 0.

- [ ] **Step 6: Commit final evidence and tightened baselines**

```powershell
git add tests/test_abstraction_ratchets.py docs/superpowers/specs/2026-07-22-configuration-contract-kernel-convergence-design.md
git commit -m "docs: record foundational convergence evidence"
```

---

## Plan Self-Review Checklist

- Every design requirement maps to at least one task.
- Every retired production module is named in the file structure and a task.
- Configuration model/schema convergence precedes loader-surface deletion.
- Kernel coercion ownership precedes package-wide contract typing.
- Document normalization precedes protocol and compatibility alias deletion.
- Snapshot and candidate migrations remove their protocols before final protocol ratchets.
- Final metrics use fresh AST output and can only move downward.
- No task creates a compatibility alias, forwarding replacement, dynamic type escape hatch, or new production dependency.
