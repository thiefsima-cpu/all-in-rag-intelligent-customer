# Over-Abstraction and File-Fragmentation Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove fourteen forwarding or ceremony-only production modules, eliminate four bootstrap-only protocols and three invocation adapters, and replace redundant mypy leaf configuration with package-level ratchets without changing runtime behavior.

**Architecture:** `rag_modules.application` remains the sole owner of answer and knowledge-base use cases and consumer-owned ports; `rag_modules.app` retains composition, lifecycle, diagnostics, and system facades. Old imports fail immediately, public bootstrappers call already-resolved typed collaborators directly, and scoped AST ratchets prevent forwarding modules and explicit adapter-to-protocol inheritance from returning.

**Tech Stack:** Python 3.11, FastAPI, Pydantic/dataclasses, mypy 2.1, Ruff, pytest/unittest, TOML, AST-based structural tests.

## Global Constraints

- Use Python `>=3.11,<3.12`; do not change dependencies or generated lock files.
- Keep `rag_modules.application` free of imports from configuration, build pipeline, retrieval, routing, generation, infrastructure, query policy, and app composition.
- Use a hard cutover: no forwarding file, alias, lazy export, `sys.modules` bridge, package `__getattr__`, or fallback import for retired paths.
- Preserve HTTP routes, response schemas, answer behavior, build behavior, runtime lifecycle behavior, and existing exception propagation.
- Preserve provider protocols and real cross-subsystem consumer-owned ports; remove only the approved bootstrap invocation protocols.
- Keep `rag_modules.app.diagnostics` as the single approved diagnostics facade.
- Add or update focused tests before implementation changes; run the narrowest relevant slice before broad gates.
- Treat public-surface policy, architecture docs, strict-type ratchets, and structural tests as required deliverables.
- Do not edit historical plan documents to rewrite the paths that existed when those plans were executed.

---

## File Structure

**Canonical owners modified:**

- `rag_modules/application/ports.py`: owns `AnswerWorkflowCopy` with the other application-consumed ports.
- `rag_modules/application/answering/answer_pipeline.py`: imports `AnswerWorkflowCopy` from application ports.
- `rag_modules/application/answering/answer_result_factory.py`: imports `AnswerWorkflowCopy` from application ports.
- `rag_modules/app/bootstrap.py`: owns the small component-binding helper and delegates directly to resolved collaborators.
- `rag_modules/app/diagnostics.py`: imports diagnostics DTOs directly from artifact, runtime, and stats owner modules.
- `rag_modules/app/services/__init__.py`: exports only runtime diagnostics and shutdown services.

**Production modules deleted:**

- `rag_modules/app/services/answer_copy.py`
- `rag_modules/app/services/answer_models.py`
- `rag_modules/app/services/answer_pipeline.py`
- `rag_modules/app/services/answer_result_factory.py`
- `rag_modules/app/services/answer_trace_assembler.py`
- `rag_modules/app/services/answer_workflow.py`
- `rag_modules/app/services/knowledge_base_service.py`
- `rag_modules/app/services/trace_adapters.py`
- `rag_modules/application/answering/answer_copy.py`
- `rag_modules/runtime/snapshot_utils.py`
- `rag_modules/app/contracts.py`
- `rag_modules/app/diagnostics_models.py`
- `rag_modules/app/bootstrap_facade_contracts.py`
- `rag_modules/app/bootstrap_facade_support.py`

**Test structure:**

- `tests/test_module_boundary_facades.py`: proves every retired import fails.
- `tests/test_abstraction_ratchets.py`: owns scoped forwarding-module, protocol-location, and adapter-inheritance ratchets.
- `tests/test_public_surface_runtime_boundaries.py`: proves bootstrappers call resolved collaborators without constructing them.
- `tests/test_type_contract_ratchets.py`: proves strict package patterns are complete and non-redundant.
- `tests/test_contract_snapshot_utils.py`: canonical contract-kernel snapshot-helper behavior test, renamed from `tests/test_runtime_snapshot_utils.py`.

### Task 1: Make Application Ports Canonical and Retire App-Service Use-Case Facades

**Files:**

- Modify: `rag_modules/application/ports.py`
- Modify: `rag_modules/application/answering/answer_pipeline.py`
- Modify: `rag_modules/application/answering/answer_result_factory.py`
- Modify: `rag_modules/app/providers/services.py`
- Modify: `rag_modules/app/services/__init__.py`
- Modify: `scripts/pressure_api_service.py`
- Modify: `tests/test_application_use_cases.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `tests/test_public_api_manifest.py`
- Delete: `rag_modules/application/answering/answer_copy.py`
- Delete: `rag_modules/app/services/answer_copy.py`
- Delete: `rag_modules/app/services/answer_models.py`
- Delete: `rag_modules/app/services/answer_pipeline.py`
- Delete: `rag_modules/app/services/answer_result_factory.py`
- Delete: `rag_modules/app/services/answer_trace_assembler.py`
- Delete: `rag_modules/app/services/answer_workflow.py`
- Delete: `rag_modules/app/services/knowledge_base_service.py`
- Delete: `rag_modules/app/services/trace_adapters.py`

**Interfaces:**

- Consumes: `AnswerWorkflowCopyPolicy` from `rag_modules.query_policy.models`, structurally satisfying the consumer-owned port.
- Produces: `rag_modules.application.ports.AnswerWorkflowCopy`; canonical imports for `AnswerPipelineService`, `QuestionAnswerResultFactory`, `AnswerTraceAssembler`, `AnswerWorkflow`, `KnowledgeBaseService`, `QuestionAnswerResponse`, and `QuestionAnswerSummary`.

- [ ] **Step 1: Add failing canonical-port and retired-import tests**

In `tests/test_application_use_cases.py`, add the import and ownership test:

```python
from rag_modules.application.ports import AnswerWorkflowCopy


def test_answer_workflow_copy_is_owned_by_application_ports() -> None:
    assert AnswerWorkflowCopy.__module__ == "rag_modules.application.ports"
```

In `tests/test_module_boundary_facades.py`, add this method to `ModuleBoundaryFacadeTests`:

```python
def test_application_use_case_compatibility_modules_are_retired(self) -> None:
    module_names = (
        "rag_modules.app.services.answer_copy",
        "rag_modules.app.services.answer_models",
        "rag_modules.app.services.answer_pipeline",
        "rag_modules.app.services.answer_result_factory",
        "rag_modules.app.services.answer_trace_assembler",
        "rag_modules.app.services.answer_workflow",
        "rag_modules.app.services.knowledge_base_service",
        "rag_modules.app.services.trace_adapters",
        "rag_modules.application.answering.answer_copy",
    )
    for module_name in module_names:
        parent_name, attr_name = module_name.rsplit(".", 1)
        parent = importlib.import_module(parent_name)
        sys.modules.pop(module_name, None)
        if hasattr(parent, attr_name):
            delattr(parent, attr_name)
        with self.subTest(module=module_name):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)
```

In `tests/test_public_api_manifest.py`, add this method to `PublicApiManifestTests`:

```python
def test_app_services_exports_only_real_lifecycle_services(self) -> None:
    import rag_modules.app.services as app_services

    self.assertEqual(
        {"RuntimeDiagnosticsService", "RuntimeShutdownService"},
        set(app_services.__all__),
    )
    self.assertFalse(hasattr(app_services, "AnswerWorkflow"))
    self.assertFalse(hasattr(app_services, "KnowledgeBaseService"))
```

- [ ] **Step 2: Run the tests and verify the intended failures**

Run:

```powershell
python -m pytest tests/test_application_use_cases.py tests/test_module_boundary_facades.py tests/test_public_api_manifest.py -q
```

Expected: collection fails because `AnswerWorkflowCopy` is not yet exported by `application.ports`, and the compatibility-module/export assertions fail while the old modules remain.

- [ ] **Step 3: Move `AnswerWorkflowCopy` into the application port module**

Insert this complete protocol before `CloseablePort` in `rag_modules/application/ports.py`:

```python
class AnswerWorkflowCopy(Protocol):
    """Product-copy fields consumed by the answer use case."""

    no_evidence_answer: str
    answer_failed: str
    user_question_template: str
    query_routing_started: str
    answer_generation_started: str
    streaming_interrupted_fallback: str
    answer_complete_template: str
    strategy_summary_template: str
    strategy_icon_hybrid_traditional: str
    strategy_icon_graph_rag: str
    strategy_icon_combined: str
    strategy_icon_default: str
    document_summary_template: str
    document_summary_total_template: str
    unknown_recipe_name: str
    unknown_search_type: str
```

Add `"AnswerWorkflowCopy"` to `application.ports.__all__` immediately after
`"AnswerTelemetryPort"`.

Replace the answer-copy imports with the canonical port import:

```python
# rag_modules/application/answering/answer_pipeline.py
from ..ports import AnswerTelemetryPort, AnswerWorkflowCopy

# rag_modules/application/answering/answer_result_factory.py
from ..ports import AnswerWorkflowCopy

# rag_modules/app/providers/services.py
from ...application.ports import (
    AnswerTelemetryPort,
    AnswerWorkflowCopy,
    AnswerWorkflowPort,
    KnowledgeBaseServicePort,
    QueryTracerPort,
)
```

Remove the three former imports from `.answer_copy` or
`...application.answering.answer_copy`.

- [ ] **Step 4: Cut callers over to canonical answer DTO modules**

Replace the pressure-script import with:

```python
from rag_modules.application.answering.answer_models import (
    QuestionAnswerResponse,
    QuestionAnswerSummary,
)
```

Replace `rag_modules/app/services/__init__.py` with:

```python
"""Runtime diagnostics and shutdown services owned by application composition."""

from .runtime_diagnostics_service import RuntimeDiagnosticsService
from .runtime_shutdown_service import RuntimeShutdownService

__all__ = ["RuntimeDiagnosticsService", "RuntimeShutdownService"]
```

- [ ] **Step 5: Delete the nine superseded use-case modules**

Delete exactly these files:

```text
rag_modules/application/answering/answer_copy.py
rag_modules/app/services/answer_copy.py
rag_modules/app/services/answer_models.py
rag_modules/app/services/answer_pipeline.py
rag_modules/app/services/answer_result_factory.py
rag_modules/app/services/answer_trace_assembler.py
rag_modules/app/services/answer_workflow.py
rag_modules/app/services/knowledge_base_service.py
rag_modules/app/services/trace_adapters.py
```

- [ ] **Step 6: Run the focused application and import-boundary slice**

Run:

```powershell
python -m pytest tests/test_application_use_cases.py tests/test_answer_workflow.py tests/test_module_boundary_facades.py tests/test_public_api_manifest.py tests/test_consumer_owned_ports.py -q
python -c "import scripts.pressure_api_service"
python -m ruff check rag_modules/application rag_modules/app/providers/services.py rag_modules/app/services scripts/pressure_api_service.py tests/test_application_use_cases.py tests/test_module_boundary_facades.py tests/test_public_api_manifest.py
```

Expected: all tests pass, the pressure script imports successfully, and Ruff reports no errors.

- [ ] **Step 7: Commit the application hard cutover**

```powershell
git add -A -- rag_modules/application rag_modules/app/services rag_modules/app/providers/services.py scripts/pressure_api_service.py tests/test_application_use_cases.py tests/test_module_boundary_facades.py tests/test_public_api_manifest.py
git commit -m "refactor: retire application compatibility facades"
```

### Task 2: Retire Contract, Diagnostics, and Snapshot Aggregation Facades

**Files:**

- Create: `tests/test_abstraction_ratchets.py`
- Modify: `rag_modules/app/assembly.py`
- Modify: `rag_modules/app/system.py`
- Modify: `rag_modules/app/__init__.py`
- Modify: `rag_modules/app/diagnostics.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `tests/test_module_split_facades.py`
- Rename: `tests/test_runtime_snapshot_utils.py` to `tests/test_contract_snapshot_utils.py`
- Delete: `rag_modules/app/contracts.py`
- Delete: `rag_modules/app/diagnostics_models.py`
- Delete: `rag_modules/runtime/snapshot_utils.py`

**Interfaces:**

- Consumes: `QuestionAnswerer` from `application.answering.answer_models`; system collaborator protocols from `app.composition.contracts`; `RuntimeComponentProvider` from `app.providers`; snapshot helpers from `contracts.runtime.snapshot_utils`.
- Produces: one approved `rag_modules.app.diagnostics` facade with direct imports from DTO owner modules; no intermediate contract, diagnostics, or snapshot forwarding modules.

- [ ] **Step 1: Add failing aggregate-retirement and pure-forwarder tests**

Add this method to `ModuleBoundaryFacadeTests` in `tests/test_module_boundary_facades.py`:

```python
def test_internal_aggregate_facades_are_retired(self) -> None:
    for module_name in (
        "rag_modules.app.contracts",
        "rag_modules.app.diagnostics_models",
        "rag_modules.runtime.snapshot_utils",
    ):
        parent_name, attr_name = module_name.rsplit(".", 1)
        parent = importlib.import_module(parent_name)
        sys.modules.pop(module_name, None)
        if hasattr(parent, attr_name):
            delattr(parent, attr_name)
        with self.subTest(module=module_name):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)
```

Create `tests/test_abstraction_ratchets.py` with:

```python
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCOPED_ROOTS = (
    ROOT / "rag_modules" / "app",
    ROOT / "rag_modules" / "application",
    ROOT / "rag_modules" / "runtime",
)
APPROVED_FORWARDING_MODULES = {
    ROOT / "rag_modules" / "app" / "diagnostics.py",
}


def _is_docstring(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_all_assignment(node: ast.stmt) -> bool:
    return isinstance(node, ast.Assign) and all(
        isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
    )


def _is_forwarding_module(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    body = list(tree.body)
    if body and _is_docstring(body[0]):
        body.pop(0)
    body = [
        node
        for node in body
        if not (
            isinstance(node, ast.ImportFrom)
            and node.module == "__future__"
        )
    ]
    imports = [node for node in body if isinstance(node, (ast.Import, ast.ImportFrom))]
    return bool(imports) and all(
        isinstance(node, (ast.Import, ast.ImportFrom)) or _is_all_assignment(node)
        for node in body
    )


def test_scoped_leaf_modules_are_not_pure_forwarders() -> None:
    violations = []
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            if path.name == "__init__.py" or path in APPROVED_FORWARDING_MODULES:
                continue
            if _is_forwarding_module(path):
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []
```

In `tests/test_module_split_facades.py`, add `from pathlib import Path` and replace the diagnostics
test with:

```python
def test_app_diagnostics_facade_reexports_split_models_and_formatter() -> None:
    facade = importlib.import_module("rag_modules.app.diagnostics")
    artifacts = importlib.import_module("rag_modules.app.diagnostics_artifact_models")
    formatter = importlib.import_module("rag_modules.app.diagnostics_formatters")
    runtime = importlib.import_module("rag_modules.app.diagnostics_runtime_models")
    stats = importlib.import_module("rag_modules.app.diagnostics_stats_models")

    for name, owner in (
        ("ArtifactManifestDiagnostics", artifacts),
        ("DataStatsDiagnostics", stats),
        ("StartupDiagnostics", runtime),
        ("SystemStatsDiagnostics", runtime),
        ("TraceStatsDiagnostics", stats),
    ):
        assert getattr(facade, name) is getattr(owner, name)
    assert facade.startup_diagnostics_lines is formatter.startup_diagnostics_lines

    source = (Path(__file__).resolve().parents[1] / "rag_modules/app/diagnostics.py").read_text(
        encoding="utf-8"
    )
    assert "from .diagnostics_models import" not in source
```

- [ ] **Step 2: Run the structural tests and verify they fail on the three aggregates**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py::ModuleBoundaryFacadeTests::test_internal_aggregate_facades_are_retired tests/test_abstraction_ratchets.py tests/test_module_split_facades.py::test_app_diagnostics_facade_reexports_split_models_and_formatter -q
```

Expected: failures name `rag_modules/app/contracts.py`, `rag_modules/app/diagnostics_models.py`, and `rag_modules/runtime/snapshot_utils.py`.

- [ ] **Step 3: Replace `app.contracts` imports with canonical owners**

Use these exact imports in both `rag_modules/app/assembly.py` and `rag_modules/app/system.py`:

```python
from ..application.answering.answer_models import QuestionAnswerer
from .composition.contracts import SystemFacadeSupportProtocol, SystemOperationsProtocol
from .providers import RuntimeComponentProvider
```

Keep the existing direct answer DTO imports in `system.py`. Remove its import block from
`.contracts`.

In `rag_modules/app/__init__.py`, replace:

```python
from .contracts import RuntimeComponentProvider
from .providers import create_default_runtime_provider
```

with:

```python
from .providers import RuntimeComponentProvider, create_default_runtime_provider
```

- [ ] **Step 4: Make `app.diagnostics` import DTO owners directly**

Replace the imports in `rag_modules/app/diagnostics.py` with:

```python
from .diagnostics_artifact_models import (
    ArtifactBuildMetadataDiagnostics,
    ArtifactManifestDiagnostics,
    ConfigProfileDiagnostics,
)
from .diagnostics_formatters import startup_diagnostics_lines
from .diagnostics_runtime_models import StartupDiagnostics, SystemStatsDiagnostics
from .diagnostics_stats_models import (
    DataStatsDiagnostics,
    IndexStatsDiagnostics,
    ModelDiagnostics,
    RetrievalRuntimeProfileDiagnostics,
    RouteStatsDiagnostics,
    RuntimeProfileSectionDiagnostics,
    TraceStatsDiagnostics,
)
```

Keep the existing `__all__` list unchanged.

- [ ] **Step 5: Move the snapshot behavior test to the contract kernel**

Rename `tests/test_runtime_snapshot_utils.py` to `tests/test_contract_snapshot_utils.py` and replace its snapshot-helper import with:

```python
from rag_modules.contracts.runtime.snapshot_utils import (
    clone_generation_snapshot,
    clone_graph_snapshot,
    clone_route_snapshot,
)
```

Keep every behavior assertion unchanged.

- [ ] **Step 6: Delete the three forwarding modules**

Delete:

```text
rag_modules/app/contracts.py
rag_modules/app/diagnostics_models.py
rag_modules/runtime/snapshot_utils.py
```

- [ ] **Step 7: Run the aggregate-retirement slice**

Run:

```powershell
python -m pytest tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_module_split_facades.py tests/test_contract_snapshot_utils.py tests/test_app_system_runtime.py -q
python -m ruff check rag_modules/app/assembly.py rag_modules/app/system.py rag_modules/app/__init__.py rag_modules/app/diagnostics.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_module_split_facades.py tests/test_contract_snapshot_utils.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 8: Commit aggregate-facade retirement**

```powershell
git add -A -- rag_modules/app rag_modules/runtime tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_module_split_facades.py tests/test_runtime_snapshot_utils.py tests/test_contract_snapshot_utils.py tests/test_app_system_runtime.py
git commit -m "refactor: retire internal aggregate facades"
```

### Task 3: Remove Bootstrap Invocation Protocols and Adapters

**Files:**

- Modify: `rag_modules/app/bootstrap.py`
- Modify: `tests/test_public_surface_runtime_boundaries.py`
- Modify: `tests/test_module_boundary_facades.py`
- Modify: `tests/test_abstraction_ratchets.py`
- Modify: `tests/test_type_contract_ratchets.py`
- Delete: `rag_modules/app/bootstrap_facade_contracts.py`
- Delete: `rag_modules/app/bootstrap_facade_support.py`
- Delete: `tests/test_bootstrap_facade_support.py`

**Interfaces:**

- Consumes: `BuildRuntimeFactory.build`, `BuildRuntimeExecutor.build_knowledge_base`, `BuildRuntimeExecutor.rebuild_knowledge_base`, `ServingRuntimeLifecycleServiceProtocol.build_ready`, `prepare`, `prepare_with_shared_runtime`, and `SystemRuntimeBootstrapService.build`.
- Produces: direct public-bootstrapper delegation and a local `_ComposedBootstrapperFacade` component-binding helper with no invocation type parameter.

- [ ] **Step 1: Reverse the obsolete direct-call prohibition test**

Replace `test_public_bootstrappers_do_not_call_runtime_collaborators_directly` in
`tests/test_public_surface_runtime_boundaries.py` with:

```python
def test_public_bootstrappers_call_resolved_runtime_collaborators_directly(self) -> None:
    path = RAG_MODULES_DIR / "app" / "bootstrap.py"
    source = path.read_text(encoding="utf-8-sig")

    for expected in (
        "self.factory.build(",
        "self.executor.build_knowledge_base(",
        "self.executor.rebuild_knowledge_base(",
        "self.lifecycle_service.build_ready(",
        "self.lifecycle_service.prepare(",
        "self.lifecycle_service.prepare_with_shared_runtime(",
        "self.bootstrap_service.build(",
    ):
        self.assertIn(expected, source)
    self.assertNotIn("_invocations", source)
    self.assertNotIn("InvocationAdapter", source)
    self.assertNotIn("getattr(", source)
```

Add this method to `ModuleBoundaryFacadeTests`:

```python
def test_bootstrap_invocation_layers_are_retired(self) -> None:
    for module_name in (
        "rag_modules.app.bootstrap_facade_contracts",
        "rag_modules.app.bootstrap_facade_support",
    ):
        parent_name, attr_name = module_name.rsplit(".", 1)
        parent = importlib.import_module(parent_name)
        sys.modules.pop(module_name, None)
        if hasattr(parent, attr_name):
            delattr(parent, attr_name)
        with self.subTest(module=module_name):
            with self.assertRaises(ModuleNotFoundError):
                importlib.import_module(module_name)
```

- [ ] **Step 2: Extend the abstraction ratchet for protocols and adapters**

Append these constants and helpers to `tests/test_abstraction_ratchets.py`:

```python
APPROVED_PROTOCOL_EXCEPTIONS = {
    Path("rag_modules/app/application_protocol.py"): frozenset({"GraphRAGApplication"}),
    Path("rag_modules/app/composition/build_jobs.py"): frozenset(
        {
            "_BuildJobStoreMigrator",
            "_BuildJobStoreMigratorFactory",
            "_ExternalBuildJobQueueRunnerFactory",
            "_ExternalBuildJobWorkerRunnerFactory",
            "_FileBuildJobRepositoryFactory",
            "_InProcessBuildJobRunnerFactory",
            "_RuntimeBuildJobsModule",
            "BuildJobWorkerRunnerPort",
        }
    ),
    Path("rag_modules/application/answering/answer_models.py"): frozenset(
        {"QuestionAnswerer"}
    ),
    Path("rag_modules/application/answering/trace_adapters.py"): frozenset(
        {
            "ExplainableQueryRouterProtocol",
            "GenerationServiceProtocol",
            "GenerationStreamTraceServiceProtocol",
            "GenerationTraceServiceProtocol",
            "QueryRouterProtocol",
            "QueryRouterWithTraceProtocol",
        }
    ),
    Path("rag_modules/runtime/artifact_adapters.py"): frozenset(
        {
            "_DiscardableVectorIndexPort",
            "_ManifestBoundVectorIndexPort",
            "_PreparedVectorIndexPort",
            "_PublishedVectorIndexPort",
            "_RollbackVectorIndexPort",
        }
    ),
}


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _protocol_definitions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(_base_name(base) == "Protocol" for base in node.bases)
    }
```

Append these tests:

```python
def test_protocols_outside_port_and_contract_modules_match_approved_baseline() -> None:
    actual: dict[Path, frozenset[str]] = {}
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            if path.name in {"ports.py", "contracts.py"}:
                continue
            names = _protocol_definitions(path)
            if names:
                actual[path.relative_to(ROOT)] = frozenset(names)

    assert actual == APPROVED_PROTOCOL_EXCEPTIONS


def test_concrete_adapters_do_not_explicitly_inherit_protocols() -> None:
    protocol_names: set[str] = set()
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            protocol_names.update(_protocol_definitions(path))

    violations: list[str] = []
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef) or not node.name.endswith("Adapter"):
                    continue
                inherited = sorted(
                    protocol_names.intersection(_base_name(base) for base in node.bases)
                )
                if inherited:
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: "
                        f"{node.name} inherits {', '.join(inherited)}"
                    )

    assert violations == []
```

- [ ] **Step 3: Run the bootstrap structural tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_public_surface_runtime_boundaries.py::PublicSurfaceRuntimeBoundaryTests::test_public_bootstrappers_call_resolved_runtime_collaborators_directly tests/test_module_boundary_facades.py::ModuleBoundaryFacadeTests::test_bootstrap_invocation_layers_are_retired tests/test_abstraction_ratchets.py -q
```

Expected: failures show `_invocations`, the two existing bootstrap support modules, the three explicit adapter/protocol inheritances, and the four unapproved bootstrap protocols.

- [ ] **Step 4: Move the component-binding helper into `app.bootstrap`**

Replace the support-module imports at the top of `rag_modules/app/bootstrap.py` with:

```python
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from typing import Any, Optional
```

Insert this helper before `BuildBootstrapper`:

```python
class _ComposedBootstrapperFacade:
    """Bind composer-resolved dataclass components onto a public facade."""

    def _compose_and_bind(
        self,
        *,
        compose: Callable[..., object],
        **compose_kwargs: object,
    ) -> None:
        components = compose(**compose_kwargs)
        if not is_dataclass(components):
            raise TypeError("Bootstrapper components must be dataclass instances.")
        for component_field in fields(components):
            setattr(self, component_field.name, getattr(components, component_field.name))
```

Change the class bases to:

```python
class BuildBootstrapper(_ComposedBootstrapperFacade):
class ServingBootstrapper(_ComposedBootstrapperFacade):
class GraphRAGBootstrapper(_ComposedBootstrapperFacade):
```

Remove all `super().__init__(invocations=...)` calls. In each constructor call `_compose_and_bind`
with the resolved compose method:

```python
self._compose_and_bind(
    compose=(bootstrapper_composer or BuildBootstrapperComposer()).compose,
    provider=provider,
    factory=factory,
    executor=executor,
    provider_resolver=provider_resolver,
)
```

Use these exact calls for serving and graph constructors:

```python
self._compose_and_bind(
    compose=(bootstrapper_composer or ServingBootstrapperComposer()).compose,
    provider=provider,
    factory=factory,
    preparer=preparer,
    lifecycle_service=lifecycle_service,
    provider_resolver=provider_resolver,
)

self._compose_and_bind(
    compose=(bootstrapper_composer or GraphRAGBootstrapperComposer()).compose,
    provider=provider,
    build_bootstrapper=build_bootstrapper,
    serving_bootstrapper=serving_bootstrapper,
    bootstrap_service=bootstrap_service,
    provider_resolver=provider_resolver,
)
```

- [ ] **Step 5: Replace every invocation-adapter call with the resolved collaborator**

Use these complete method bodies:

```python
# BuildBootstrapper.build
return self.factory.build(
    config,
    neo4j_manager=neo4j_manager,
    data_module=data_module,
    index_module=index_module,
    progress=progress,
)

# BuildBootstrapper.build_knowledge_base
return self.executor.build_knowledge_base(
    runtime,
    progress=progress,
    request_id=request_id,
    build_job_id=build_job_id,
)

# BuildBootstrapper.rebuild_knowledge_base
return self.executor.rebuild_knowledge_base(
    runtime,
    progress=progress,
    request_id=request_id,
    build_job_id=build_job_id,
)

# ServingBootstrapper.build
return self.lifecycle_service.build_ready(
    config,
    shared_runtime=shared_runtime,
    query_tracer=query_tracer,
    neo4j_manager=neo4j_manager,
    data_module=data_module,
    index_module=index_module,
    progress=progress,
)

# ServingBootstrapper.prepare
return self.lifecycle_service.prepare(
    runtime,
    chunks=chunks,
    artifact_manifest=artifact_manifest,
    progress=progress,
    force=force,
)

# ServingBootstrapper.prepare_with_shared_runtime
return self.lifecycle_service.prepare_with_shared_runtime(
    runtime,
    shared_runtime=shared_runtime,
    progress=progress,
    force=force,
)

# GraphRAGBootstrapper.build
return self.bootstrap_service.build(
    config,
    query_tracer=query_tracer,
    neo4j_manager=neo4j_manager,
    progress=progress,
)
```

- [ ] **Step 6: Delete bootstrap invocation files and their adapter-only test**

Delete:

```text
rag_modules/app/bootstrap_facade_contracts.py
rag_modules/app/bootstrap_facade_support.py
tests/test_bootstrap_facade_support.py
```

Remove both deleted paths from `NO_EXPLICIT_ANY_TARGETS` in
`tests/test_type_contract_ratchets.py`.

- [ ] **Step 7: Run bootstrap behavior, structure, and formatting tests**

Run:

```powershell
python -m pytest tests/test_build_runtime_factory.py tests/test_serving_runtime_factory.py tests/test_app_system_runtime.py tests/test_public_surface_runtime_boundaries.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py -q
python -m ruff check rag_modules/app/bootstrap.py tests/test_public_surface_runtime_boundaries.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py
python -m ruff format --check rag_modules/app/bootstrap.py tests/test_public_surface_runtime_boundaries.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py
```

Expected: all tests pass; existing bootstrap behavior remains green; Ruff check and format check pass.

- [ ] **Step 8: Commit bootstrap simplification**

```powershell
git add -A -- rag_modules/app/bootstrap.py rag_modules/app/bootstrap_facade_contracts.py rag_modules/app/bootstrap_facade_support.py tests/test_bootstrap_facade_support.py tests/test_public_surface_runtime_boundaries.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py
git commit -m "refactor: remove bootstrap invocation ceremony"
```

### Task 4: Normalize Mypy Strict-Island Package Rules

**Files:**

- Modify: `pyproject.toml`
- Modify: `tests/test_type_contract_ratchets.py`

**Interfaces:**

- Consumes: the existing strict override flags `disallow_untyped_defs = true` and `ignore_missing_imports = false`.
- Produces: 70 normalized module patterns; package-level strict coverage for application, contracts, providers, API, services, generation execution, kernel, runtime, parsers, graph preparation, and retrieval adapters.

- [ ] **Step 1: Add failing package-pattern normalization tests**

Replace `NO_EXPLICIT_ANY_PACKAGE_TARGETS` with:

```python
NO_EXPLICIT_ANY_PACKAGE_TARGETS = (
    ROOT / "rag_modules" / "app" / "providers",
    ROOT / "rag_modules" / "application",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation",
    ROOT / "rag_modules" / "generation" / "execution",
    ROOT / "rag_modules" / "query_policy" / "parsers",
)
```

Remove these individual paths from `NO_EXPLICIT_ANY_TARGETS`; package scanning now owns them:

```python
ROOT / "rag_modules" / "app" / "providers" / "__init__.py"
ROOT / "rag_modules" / "app" / "providers" / "build_pipeline.py"
ROOT / "rag_modules" / "app" / "providers" / "contracts.py"
ROOT / "rag_modules" / "app" / "providers" / "default.py"
ROOT / "rag_modules" / "app" / "providers" / "generation.py"
ROOT / "rag_modules" / "app" / "providers" / "infrastructure.py"
ROOT / "rag_modules" / "app" / "providers" / "retrieval_runtime.py"
ROOT / "rag_modules" / "app" / "providers" / "services.py"
ROOT / "rag_modules" / "application" / "answering" / "answer_models.py"
ROOT / "rag_modules" / "application" / "answering" / "answer_pipeline.py"
ROOT / "rag_modules" / "application" / "answering" / "answer_trace_assembler.py"
ROOT / "rag_modules" / "application" / "answering" / "answer_workflow.py"
ROOT / "rag_modules" / "application" / "knowledge_base.py"
ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "models.py"
ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "statistics.py"
ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "document_builder.py"
ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "loader.py"
ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "module.py"
ROOT / "rag_modules" / "generation" / "execution" / "contracts.py"
ROOT / "rag_modules" / "generation" / "execution" / "direct.py"
ROOT / "rag_modules" / "generation" / "execution" / "timeouts.py"
ROOT / "rag_modules" / "generation" / "execution" / "tracing.py"
ROOT / "rag_modules" / "generation" / "execution" / "two_stage.py"
```

Replace `STRICT_PACKAGE_TARGETS` with:

```python
STRICT_PACKAGE_TARGETS = (
    ROOT / "rag_modules" / "app" / "providers",
    ROOT / "rag_modules" / "app" / "services",
    ROOT / "rag_modules" / "application",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation",
    ROOT / "rag_modules" / "contracts",
    ROOT / "rag_modules" / "domain",
    ROOT / "rag_modules" / "generation" / "execution",
    ROOT / "rag_modules" / "interfaces" / "api",
    ROOT / "rag_modules" / "kernel",
    ROOT / "rag_modules" / "query_policy" / "parsers",
    ROOT / "rag_modules" / "retrieval" / "adapters",
    ROOT / "rag_modules" / "runtime",
)
```

Add these tests to `TypeContractRatchetTests`:

```python
def test_strict_packages_use_package_and_descendant_patterns(self) -> None:
    strict_patterns = set(_strict_mypy_modules())
    missing_patterns: list[str] = []

    for package_path in STRICT_PACKAGE_TARGETS:
        package_name = _module_name_for_target(package_path / "__init__.py")
        for expected in (package_name, f"{package_name}.*"):
            if expected not in strict_patterns:
                missing_patterns.append(expected)

    self.assertFalse(
        missing_patterns,
        "Strict packages must use package-level mypy patterns:\n"
        + "\n".join(missing_patterns),
    )

def test_strict_mypy_patterns_do_not_redeclare_wildcard_children(self) -> None:
    strict_patterns = _strict_mypy_modules()
    redundant: list[str] = []

    for wildcard in (pattern for pattern in strict_patterns if pattern.endswith(".*")):
        package_name = wildcard[:-2]
        redundant.extend(
            f"{pattern} is covered by {wildcard}"
            for pattern in strict_patterns
            if pattern not in {package_name, wildcard}
            and fnmatch.fnmatchcase(pattern, wildcard)
        )

    self.assertFalse(
        redundant,
        "Strict mypy package patterns contain redundant child entries:\n"
        + "\n".join(sorted(redundant)),
    )
```

- [ ] **Step 2: Run the ratchet tests and verify current redundancy fails**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py -q
```

Expected: failures list missing package patterns and redundant provider, runtime, contract-runtime,
generation-execution, graph-preparation, and retrieval-adapter child entries.

- [ ] **Step 3: Replace the mypy override list with the normalized 70-pattern list**

Use this exact `module` array in the strict override in `pyproject.toml`:

```toml
module = [
  "rag_modules.app.application_protocol",
  "rag_modules.app.bootstrap",
  "rag_modules.app.composition.build_jobs",
  "rag_modules.app.composition.contracts",
  "rag_modules.app.composition.serving_runtime_factory",
  "rag_modules.app.composition.system_composer",
  "rag_modules.app.diagnostics",
  "rag_modules.app.ports",
  "rag_modules.app.providers",
  "rag_modules.app.providers.*",
  "rag_modules.app.runtime_state",
  "rag_modules.app.runtime_view_builder",
  "rag_modules.app.runtime_views",
  "rag_modules.app.services",
  "rag_modules.app.services.*",
  "rag_modules.application",
  "rag_modules.application.*",
  "rag_modules.build_pipeline.graph_preparation",
  "rag_modules.build_pipeline.graph_preparation.*",
  "rag_modules.build_pipeline.ports",
  "rag_modules.contracts",
  "rag_modules.contracts.*",
  "rag_modules.domain",
  "rag_modules.domain.*",
  "rag_modules.generation.context_factory",
  "rag_modules.generation.decision",
  "rag_modules.generation.execution",
  "rag_modules.generation.execution.*",
  "rag_modules.generation.planner",
  "rag_modules.graph.cache_stats",
  "rag_modules.graph.evidence_builder",
  "rag_modules.graph.ports",
  "rag_modules.graph.query_executor",
  "rag_modules.graph.query_intent",
  "rag_modules.graph.query_resolution",
  "rag_modules.graph.rag_retrieval",
  "rag_modules.graph.reasoning_strategy",
  "rag_modules.graph.retrieval_components",
  "rag_modules.graph.retrieval_executor",
  "rag_modules.graph.retrieval_plan",
  "rag_modules.graph.retrieval_postprocess",
  "rag_modules.graph.retrieval_runtime",
  "rag_modules.graph.retrieval_types",
  "rag_modules.interfaces.api",
  "rag_modules.interfaces.api.*",
  "rag_modules.kernel",
  "rag_modules.kernel.*",
  "rag_modules.observability.tracing",
  "rag_modules.observability.tracing_event_builder",
  "rag_modules.query_policy.loader",
  "rag_modules.query_policy.models",
  "rag_modules.query_policy.parsers",
  "rag_modules.query_policy.parsers.*",
  "rag_modules.retrieval.adapters",
  "rag_modules.retrieval.adapters.*",
  "rag_modules.retrieval.candidate_sources",
  "rag_modules.retrieval.hybrid_components",
  "rag_modules.retrieval.hybrid_index_service",
  "rag_modules.retrieval.hybrid_runtime",
  "rag_modules.retrieval.hybrid_runtime_state",
  "rag_modules.retrieval.hybrid_service",
  "rag_modules.retrieval.ports",
  "rag_modules.retrieval.runtime_adapter_factory",
  "rag_modules.retrieval.runtime_profile.profile",
  "rag_modules.routing.contracts",
  "rag_modules.routing.execution_strategies",
  "rag_modules.routing.search_orchestrator",
  "rag_modules.runtime",
  "rag_modules.runtime.*",
  "tests.typecheck.type_contracts",
]
```

Keep the override flags unchanged:

```toml
disallow_untyped_defs = true
ignore_missing_imports = false
```

- [ ] **Step 4: Verify package rules and full mypy**

Run:

```powershell
python -m pytest tests/test_type_contract_ratchets.py tests/test_kernel_contracts.py -q
python -m mypy --config-file pyproject.toml
```

Expected: all ratchet tests pass and mypy prints `Success: no issues found`.

- [ ] **Step 5: Commit strict-island normalization**

```powershell
git add -- pyproject.toml tests/test_type_contract_ratchets.py
git commit -m "chore: normalize strict mypy package ratchets"
```

### Task 5: Align Public Manifest and Architecture Documentation

**Files:**

- Modify: `rag_modules/public_surface_manifest.py`
- Modify: `tests/test_public_api_manifest.py`
- Modify: `tests/test_public_surface_boundaries.py`
- Modify: `docs/architecture.md`
- Modify: `docs/app_composition_maintenance_guide.md`
- Modify: `docs/public_surface_retirement_plan.md`

**Interfaces:**

- Consumes: the canonical application, app-services, diagnostics, composition, provider, and contract paths produced by Tasks 1-4.
- Produces: one machine-readable public-surface description and three maintained documents that all state the hard-cutover policy.

- [ ] **Step 1: Add failing manifest and documentation assertions**

Add this test to `PublicApiManifestTests`:

```python
def test_app_services_manifest_describes_only_lifecycle_services(self) -> None:
    entry = canonical_surface_by_module()["rag_modules.app.services"]

    self.assertEqual("service_api", entry.kind)
    self.assertEqual("rag_modules.app.services", entry.canonical_module)
    self.assertIn("diagnostics", entry.notes.lower())
    self.assertIn("shutdown", entry.notes.lower())
    self.assertNotIn("compatibility", entry.notes.lower())
```

Extend `test_app_composition_maintenance_guide_documents_runtime_ownership` in
`tests/test_public_surface_boundaries.py` with:

```python
for expected in (
    "rag_modules.application",
    "rag_modules.app.services",
    "directly call resolved composition collaborators",
    "Do not add forwarding-only modules",
):
    self.assertIn(expected, guide)

for expected in (
    "rag_modules.application.*",
    "rag_modules.app.diagnostics",
    "rag_modules.app.services.answer_*",
    "rag_modules.runtime.snapshot_utils",
):
    self.assertIn(expected, policy)
```

- [ ] **Step 2: Run documentation contract tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py::PublicApiManifestTests::test_app_services_manifest_describes_only_lifecycle_services tests/test_public_surface_boundaries.py::PublicSurfaceLegacyBoundaryTests::test_app_composition_maintenance_guide_documents_runtime_ownership -q
```

Expected: failures show the current compatibility wording and missing hard-cutover policy text.

- [ ] **Step 3: Correct the public manifest**

Change the `rag_modules.app.services` entry notes in
`rag_modules/public_surface_manifest.py` to:

```python
"Runtime diagnostics and shutdown services owned by application composition."
```

Do not add entries for any deleted leaf module.

- [ ] **Step 4: Update maintained architecture documentation**

Add this ownership paragraph near the request lifecycle in `docs/architecture.md`:

```markdown
`rag_modules.application` is the canonical Python import surface for answer and
knowledge-base use cases. `rag_modules.app.services` contains only runtime
diagnostics and shutdown services; it does not forward application use cases or
DTOs. Public bootstrappers delegate directly to collaborators resolved by the
composition roots and do not insert invocation adapters.
```

Add these bullets under `## Boundary Rules` in
`docs/app_composition_maintenance_guide.md`:

```markdown
- Import answer and knowledge-base use cases from `rag_modules.application`, not
  `rag_modules.app.services`.
- `rag_modules.app.services` owns only runtime diagnostics and shutdown services.
- Public bootstrappers may directly call resolved composition collaborators; do
  not add invocation protocols or adapters that only forward the same method.
- Do not add forwarding-only modules. Keep a package facade only when it is the
  documented canonical import surface.
```

In `docs/public_surface_retirement_plan.md`:

1. Replace the canonical application line with these two lines:

```markdown
- Application use cases and ports: `rag_modules.application.*`
- Application composition and runtime facade: `rag_modules.app.*`
```

2. Add this canonical internal-facade bullet:

```markdown
- `rag_modules.app.diagnostics` is the single diagnostics DTO facade and imports
  directly from the artifact, runtime, and stats diagnostics owner modules.
```
3. Add this internal-freeze rule:

```markdown
- The application-use-case compatibility modules under
  `rag_modules.app.services.answer_*`,
  `rag_modules.app.services.knowledge_base_service`, and
  `rag_modules.app.services.trace_adapters` are retired in favor of
  `rag_modules.application`. The internal aggregates
  `rag_modules.app.contracts`, `rag_modules.app.diagnostics_models`, and
  `rag_modules.runtime.snapshot_utils`, plus the bootstrap invocation support
  modules, must fail instead of forwarding.
```

4. Replace the application history entry with:

```markdown
- `application`, `knowledge_base_service`, and `question_answer_service`
  facades retired in favor of `rag_modules.app.system` and
  `rag_modules.application.*`.
```

- [ ] **Step 5: Run documentation, manifest, and diff checks**

Run:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_public_surface_dependency_boundaries.py -q
python -m ruff check rag_modules/public_surface_manifest.py tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py
git diff --check
```

Expected: all tests and Ruff pass; `git diff --check` produces no output.

- [ ] **Step 6: Commit policy and documentation alignment**

```powershell
git add -- rag_modules/public_surface_manifest.py tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py docs/architecture.md docs/app_composition_maintenance_guide.md docs/public_surface_retirement_plan.md
git commit -m "docs: enforce abstraction convergence policy"
```

### Task 6: Run Release-Sensitive Verification and Measure the Result

**Files:**

- Verify only; no source files should change.

**Interfaces:**

- Consumes: all canonical imports, structural ratchets, mypy rules, and documentation from Tasks 1-5.
- Produces: evidence for merge readiness and measured post-change complexity counts.

- [ ] **Step 1: Run the focused architecture and application gate**

```powershell
python -m pytest tests/test_application_use_cases.py tests/test_answer_workflow.py tests/test_build_runtime_factory.py tests/test_serving_runtime_factory.py tests/test_app_system_runtime.py tests/test_contract_snapshot_utils.py tests/test_module_boundary_facades.py tests/test_abstraction_ratchets.py tests/test_type_contract_ratchets.py tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_public_surface_dependency_boundaries.py tests/test_public_surface_runtime_boundaries.py tests/test_consumer_owned_ports.py tests/test_import_dag.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run the API behavior slice**

```powershell
python -m pytest tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q
```

Expected: all API tests pass with no schema or route changes.

- [ ] **Step 3: Run static gates**

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy --config-file pyproject.toml
```

Expected: Ruff check passes, Ruff reports all files formatted, and mypy prints
`Success: no issues found`.

- [ ] **Step 4: Run full tests and the offline release gate**

```powershell
python -m pytest -q
python scripts/release_gate.py
```

Expected: full pytest passes and the release gate reports every offline case passed.

- [ ] **Step 5: Measure post-change files, lines, classes, protocols, and forwarders**

Run:

```powershell
@'
from pathlib import Path
import ast

root = Path("rag_modules")
files = sorted(root.rglob("*.py"))
line_count = 0
class_count = 0
protocol_count = 0
small_count = 0
forwarders = []

for path in files:
    source = path.read_text(encoding="utf-8-sig")
    line_count += len(source.splitlines())
    small_count += len(source.splitlines()) < 60
    tree = ast.parse(source, filename=str(path))
    class_count += sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id == "Protocol")
            or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
            for base in node.bases
        ):
            protocol_count += 1
    if path.name != "__init__.py":
        body = list(tree.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body.pop(0)
        body = [
            node
            for node in body
            if not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
        ]
        if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in body) and all(
            isinstance(node, (ast.Import, ast.ImportFrom))
            or (
                isinstance(node, ast.Assign)
                and all(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
            )
            for node in body
        ):
            forwarders.append(path.as_posix())

print(f"python_files={len(files)}")
print(f"python_lines={line_count}")
print(f"classes={class_count}")
print(f"protocols={protocol_count}")
print(f"files_below_60_lines={small_count}")
print(f"non_package_forwarders={len(forwarders)}")
for path in forwarders:
    print(path)
'@ | python -
```

Expected: production Python files decrease by fourteen, the four bootstrap invocation protocols
are absent, and the scoped forwarding-module ratchet reports no unapproved path. Record actual
global counts in the final handoff.

- [ ] **Step 6: Confirm clean delivery state**

```powershell
git diff --check
git status --short
git log -5 --oneline
```

Expected: `git diff --check` and `git status --short` produce no output; the five focused task
commits are visible at the branch tip. If a formatter changed a file during verification, rerun the
relevant focused and broad gates before creating a dedicated formatting commit.
