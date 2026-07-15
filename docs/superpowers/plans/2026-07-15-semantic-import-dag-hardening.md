# Semantic Import DAG Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the build/runtime semantic dependency cycle and enforce a classified,
allow-listed runtime and type import DAG for every production module.

**Architecture:** Move cross-subsystem graph-preparation DTOs into the neutral contracts package,
replace runtime's build/routing annotations with consumer-owned minimal protocols, and replace the
runtime-only package-cycle test with an AST inventory that labels runtime and type edges. Keep
policy data in a separate test module so architectural changes require an explicit allow-list edit.

**Tech Stack:** Python 3.11, dataclasses, typing `Protocol`, Python `ast`, pytest, mypy, Ruff,
pre-commit.

## Global Constraints

- Python must remain `>=3.11,<3.12`.
- Do not add production or development dependencies.
- Do not change HTTP schemas, artifact formats, graph queries, retrieval ranking, or DTO fields.
- Do not preserve old build-pipeline DTO paths through aliases, forwarding definitions, or package
  re-exports.
- `TYPE_CHECKING` imports are architecture dependencies and use the same allow-list as runtime
  imports.
- Every `rag_modules/**/*.py` file must belong to exactly one declared architectural node.
- Use `apply_patch` for source edits and preserve unrelated worktree changes.
- Follow red-green-refactor: run every new focused test before and after its implementation.

---

### Task 1: Move Graph-Preparation DTOs to Contracts

**Files:**

- Create: `rag_modules/contracts/graph_preparation.py`
- Create: `tests/test_graph_preparation_contracts.py`
- Modify: `rag_modules/contracts/__init__.py`
- Modify: `rag_modules/build_pipeline/__init__.py`
- Modify: `rag_modules/build_pipeline/ports.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/__init__.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/models.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/loader.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/state.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/document_builder.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/statistics.py`
- Modify: `rag_modules/build_pipeline/graph_preparation/module.py`
- Modify: `rag_modules/retrieval/ports.py`
- Modify: `rag_modules/app/ports.py`
- Modify: `tests/test_document_artifact_cache.py`
- Modify: `tests/typecheck/type_contracts.py`

**Interfaces:**

- Produces: `GraphNode`, `GraphLoadCounts`, and `GraphPreparationStats` defined in
  `rag_modules.contracts.graph_preparation` and exported by `rag_modules.contracts`.
- Preserves: all constructors, fields, `__post_init__` normalization, and `to_dict()` payloads.
- Removes: all three DTO definitions and exports from build-pipeline modules.

- [ ] **Step 1: Write the failing ownership and hard-cutover tests**

Create `tests/test_graph_preparation_contracts.py`:

```python
from __future__ import annotations

from importlib import import_module


def test_graph_preparation_dtos_are_owned_by_contracts() -> None:
    contracts = import_module("rag_modules.contracts.graph_preparation")

    graph_node = contracts.GraphNode(
        node_id=7,
        labels=["Recipe", ""],
        name=None,
        properties={"difficulty": "easy"},
    )
    counts = contracts.GraphLoadCounts(recipes=1, ingredients=2, cooking_steps=3)
    stats = contracts.GraphPreparationStats(total_recipes=1, total_chunks=4)

    assert contracts.GraphNode.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphLoadCounts.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphPreparationStats.__module__ == "rag_modules.contracts.graph_preparation"
    assert graph_node.node_id == "7"
    assert graph_node.labels == ["Recipe"]
    assert graph_node.name == ""
    assert counts.to_dict() == {"recipes": 1, "ingredients": 2, "cooking_steps": 3}
    assert stats.to_dict() == {
        "total_recipes": 1,
        "total_ingredients": 0,
        "total_cooking_steps": 0,
        "total_documents": 0,
        "total_chunks": 4,
    }


def test_contract_package_exports_graph_preparation_dtos() -> None:
    contracts = import_module("rag_modules.contracts")

    assert contracts.GraphNode.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphLoadCounts.__module__ == "rag_modules.contracts.graph_preparation"
    assert contracts.GraphPreparationStats.__module__ == "rag_modules.contracts.graph_preparation"
    assert {"GraphNode", "GraphLoadCounts", "GraphPreparationStats"} <= set(contracts.__all__)


def test_build_pipeline_no_longer_exports_contract_owned_dtos() -> None:
    build_pipeline = import_module("rag_modules.build_pipeline")
    graph_preparation = import_module("rag_modules.build_pipeline.graph_preparation")
    models = import_module("rag_modules.build_pipeline.graph_preparation.models")
    statistics = import_module("rag_modules.build_pipeline.graph_preparation.statistics")

    assert not hasattr(build_pipeline, "GraphNode")
    assert "GraphNode" not in build_pipeline.__all__
    assert not hasattr(graph_preparation, "GraphNode")
    assert "GraphNode" not in graph_preparation.__all__
    assert not hasattr(models, "GraphNode")
    assert not hasattr(models, "GraphLoadCounts")
    assert not hasattr(statistics, "GraphPreparationStats")
```

- [ ] **Step 2: Run the ownership tests and verify RED**

Run:

```powershell
python -m pytest tests/test_graph_preparation_contracts.py -q
```

Expected: FAIL because `rag_modules.contracts.graph_preparation` does not exist and the old build
exports still resolve.

- [ ] **Step 3: Create the canonical contracts module**

Create `rag_modules/contracts/graph_preparation.py` with the existing behavior unchanged:

```python
"""Neutral graph-preparation data contracts shared across subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.json_types import JsonObject


@dataclass(slots=True)
class GraphNode:
    """Structured graph node data loaded from Neo4j."""

    node_id: str
    labels: list[str] = field(default_factory=list)
    name: str = ""
    properties: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.node_id = str(self.node_id or "")
        self.labels = [str(label) for label in (self.labels or []) if str(label)]
        self.name = str(self.name or "")
        self.properties = dict(self.properties or {})


@dataclass(slots=True, frozen=True)
class GraphLoadCounts:
    """Counts of graph nodes loaded into preparation state."""

    recipes: int = 0
    ingredients: int = 0
    cooking_steps: int = 0

    def to_dict(self) -> JsonObject:
        return {
            "recipes": self.recipes,
            "ingredients": self.ingredients,
            "cooking_steps": self.cooking_steps,
        }


@dataclass(slots=True, frozen=True)
class GraphPreparationStats:
    """Stable graph-preparation statistics with JSON serialization."""

    total_recipes: int = 0
    total_ingredients: int = 0
    total_cooking_steps: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    categories: dict[str, int] = field(default_factory=dict)
    cuisines: dict[str, int] = field(default_factory=dict)
    difficulties: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0
    include_distributions: bool = False

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "total_recipes": self.total_recipes,
            "total_ingredients": self.total_ingredients,
            "total_cooking_steps": self.total_cooking_steps,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
        }
        if not self.include_distributions:
            return payload
        payload.update(
            {
                "categories": dict(self.categories),
                "cuisines": dict(self.cuisines),
                "difficulties": dict(self.difficulties),
                "avg_content_length": self.avg_content_length,
                "avg_chunk_size": self.avg_chunk_size,
            }
        )
        return payload


__all__ = ["GraphLoadCounts", "GraphNode", "GraphPreparationStats"]
```

Export the definitions from `rag_modules/contracts/__init__.py`:

```python
from .graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats
```

Add these exact names to `__all__` in alphabetical position:

```python
"GraphLoadCounts",
"GraphNode",
"GraphPreparationStats",
```

- [ ] **Step 4: Remove the old definitions and exports**

In `rag_modules/build_pipeline/graph_preparation/models.py`, delete `GraphNode` and
`GraphLoadCounts`. Keep `JsonObject`, `GraphRelation`, `PreparedIngredientInput`, and
`PreparedStepInput` unchanged.

In `rag_modules/build_pipeline/graph_preparation/statistics.py`, remove the dataclass imports and
the `GraphPreparationStats` definition, then import the canonical result type under a private name
so the retired module path does not remain accessible:

```python
from ...contracts.graph_preparation import GraphPreparationStats as _GraphPreparationStats
from .state import GraphPreparationState
```

Change the service annotation and both constructor calls from `GraphPreparationStats` to
`_GraphPreparationStats`.

In `rag_modules/build_pipeline/graph_preparation/__init__.py`, use:

```python
from .models import GraphRelation
```

and remove `GraphNode` from `__all__`.

In `rag_modules/build_pipeline/__init__.py`, use:

```python
from .graph_preparation import GraphDataPreparationModule, GraphRelation
```

and remove `GraphNode` from `__all__`.

- [ ] **Step 5: Point every producer and consumer at the canonical owner**

Apply these exact import replacements:

```python
# rag_modules/build_pipeline/graph_preparation/loader.py
from ...contracts.graph_preparation import GraphLoadCounts, GraphNode

# rag_modules/build_pipeline/graph_preparation/state.py
from ...contracts.graph_preparation import GraphNode

# rag_modules/build_pipeline/graph_preparation/document_builder.py
from ...contracts.graph_preparation import GraphNode
from .models import PreparedIngredientInput, PreparedStepInput

# rag_modules/build_pipeline/graph_preparation/module.py
from ...contracts.graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats
from .models import PreparedIngredientInput, PreparedStepInput
from .statistics import GraphPreparationStatisticsService

# rag_modules/build_pipeline/ports.py, inside TYPE_CHECKING
from ..contracts.graph_preparation import GraphLoadCounts, GraphPreparationStats

# rag_modules/retrieval/ports.py, inside TYPE_CHECKING
from ..contracts.graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats

# rag_modules/app/ports.py, inside TYPE_CHECKING
from ..contracts.graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats

# tests/test_document_artifact_cache.py
from rag_modules.contracts import GraphPreparationStats

# tests/typecheck/type_contracts.py
from rag_modules.contracts import GraphLoadCounts, GraphPreparationStats
```

Remove the two former build-pipeline imports from `tests/typecheck/type_contracts.py`; keep its
existing construction assertions unchanged.

- [ ] **Step 6: Run the DTO and graph-preparation slice and verify GREEN**

Run:

```powershell
python -m pytest tests/test_graph_preparation_contracts.py tests/test_graph_data_preparation_module.py tests/test_document_artifact_cache.py tests/test_consumer_owned_ports.py -q
```

Expected: PASS.

Run the strict type slice:

```powershell
python -m mypy rag_modules/contracts/graph_preparation.py rag_modules/build_pipeline/graph_preparation rag_modules/build_pipeline/ports.py rag_modules/retrieval/ports.py rag_modules/app/ports.py tests/typecheck/type_contracts.py
```

Expected: PASS with no type errors.

- [ ] **Step 7: Commit the neutral contract migration**

```powershell
git add rag_modules/contracts rag_modules/build_pipeline rag_modules/retrieval/ports.py rag_modules/app/ports.py tests/test_graph_preparation_contracts.py tests/test_document_artifact_cache.py tests/typecheck/type_contracts.py
git commit -m "refactor: move graph preparation dtos to contracts"
```

---

### Task 2: Give Runtime Minimal Statistics Source Ports

**Files:**

- Create: `tests/test_runtime_stats_adapters.py`
- Modify: `rag_modules/runtime/ports.py`
- Modify: `rag_modules/runtime/stats_ports.py`
- Modify: `rag_modules/runtime/stats_adapters.py`

**Interfaces:**

- Produces: runtime-owned `GraphStatisticsSourcePort`,
  `VectorCollectionStatisticsSourcePort`, `RouteStatisticsSourcePort`, and
  `QueryTraceStatisticsSourcePort`.
- Preserves: all `DefaultRuntimeStatsAccess` return payloads and `None` handling.
- Removes: runtime type imports from build_pipeline and routing.

- [ ] **Step 1: Write the failing runtime statistics port tests**

Create `tests/test_runtime_stats_adapters.py`:

```python
from __future__ import annotations

from rag_modules.runtime import stats_ports
from rag_modules.runtime.stats_adapters import DefaultRuntimeStatsAccess


class _StatsPayload:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> object:
        return dict(self.payload)


class _GraphStatsSource:
    def get_statistics(self) -> object:
        return _StatsPayload({"total_recipes": 2})


class _VectorStatsSource:
    def get_collection_stats(self, collection_name: str | None = None) -> object:
        return {"collection_name": collection_name or "recipes", "row_count": 4}


class _RouteStatsSource:
    def get_route_statistics(self) -> object:
        return _StatsPayload({"total_queries": 3})


class _TraceStatsSource:
    def stats(self) -> object:
        return _StatsPayload({"written_events": 5})


def test_runtime_owns_minimal_statistics_source_ports() -> None:
    expected = {
        "GraphStatisticsSourcePort",
        "VectorCollectionStatisticsSourcePort",
        "RouteStatisticsSourcePort",
        "QueryTraceStatisticsSourcePort",
    }

    assert expected <= set(stats_ports.__all__)
    for name in expected:
        assert getattr(stats_ports, name).__module__ == "rag_modules.runtime.stats_ports"


def test_default_runtime_stats_access_coerces_minimal_source_shapes() -> None:
    access = DefaultRuntimeStatsAccess()

    assert access.get_graph_data_stats(_GraphStatsSource()) == {"total_recipes": 2}
    assert access.get_vector_collection_stats(_VectorStatsSource()) == {
        "collection_name": "recipes",
        "row_count": 4,
    }
    assert access.get_route_stats(_RouteStatsSource()) == {"total_queries": 3}
    assert access.get_query_trace_stats(_TraceStatsSource()) == {"written_events": 5}
    assert access.get_graph_data_stats(None) == {}
    assert access.get_vector_collection_stats(None) == {}
    assert access.get_route_stats(None) == {}
    assert access.get_query_trace_stats(None) == {}
```

- [ ] **Step 2: Run the runtime statistics tests and verify RED**

Run:

```powershell
python -m pytest tests/test_runtime_stats_adapters.py -q
```

Expected: FAIL because the four runtime-owned source protocols do not exist.

- [ ] **Step 3: Replace external annotations with runtime-owned protocols**

Replace `rag_modules/runtime/stats_ports.py` with:

```python
"""Runtime-owned statistics access contracts."""

from __future__ import annotations

from typing import Protocol

from ..kernel.json_types import JsonObject


class GraphStatisticsSourcePort(Protocol):
    """Graph data source shape needed for runtime diagnostics."""

    def get_statistics(self) -> object: ...


class VectorCollectionStatisticsSourcePort(Protocol):
    """Vector collection source shape needed for runtime diagnostics."""

    def get_collection_stats(self, collection_name: str | None = None) -> object: ...


class RouteStatisticsSourcePort(Protocol):
    """Routing source shape needed for runtime diagnostics."""

    def get_route_statistics(self) -> object: ...


class QueryTraceStatisticsSourcePort(Protocol):
    """Query trace source shape needed for runtime diagnostics."""

    def stats(self) -> object: ...


class RuntimeProfilePayloadSource(Protocol):
    """Runtime-profile shaped object that can expose a JSON-compatible payload."""

    def to_dict(self) -> object: ...


class RuntimeStatsAccessPort(Protocol):
    """Stable boundary for runtime statistics and profile payload extraction."""

    def get_graph_data_stats(
        self,
        data_module: GraphStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_vector_collection_stats(
        self,
        index_module: VectorCollectionStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_route_stats(
        self,
        routing_workflow: RouteStatisticsSourcePort | None,
    ) -> JsonObject: ...

    def get_retrieval_runtime_profile(
        self,
        retrieval_runtime_profile: RuntimeProfilePayloadSource | None,
    ) -> JsonObject: ...

    def get_query_trace_stats(
        self,
        query_tracer: QueryTraceStatisticsSourcePort | None,
    ) -> JsonObject: ...


__all__ = [
    "GraphStatisticsSourcePort",
    "QueryTraceStatisticsSourcePort",
    "RouteStatisticsSourcePort",
    "RuntimeProfilePayloadSource",
    "RuntimeStatsAccessPort",
    "VectorCollectionStatisticsSourcePort",
]
```

Replace the external type-only imports in `rag_modules/runtime/stats_adapters.py` with runtime-owned
imports:

```python
from .stats_ports import (
    GraphStatisticsSourcePort,
    QueryTraceStatisticsSourcePort,
    RouteStatisticsSourcePort,
    RuntimeProfilePayloadSource,
    VectorCollectionStatisticsSourcePort,
)
```

Use these exact annotations on the existing methods without changing their bodies:

```python
def get_graph_data_stats(
    self,
    data_module: GraphStatisticsSourcePort | None,
) -> JsonObject: ...

def get_vector_collection_stats(
    self,
    index_module: VectorCollectionStatisticsSourcePort | None,
) -> JsonObject: ...

def get_route_stats(
    self,
    routing_workflow: RouteStatisticsSourcePort | None,
) -> JsonObject: ...

def get_retrieval_runtime_profile(
    self,
    retrieval_runtime_profile: RuntimeProfilePayloadSource | None,
) -> JsonObject: ...

def get_query_trace_stats(
    self,
    query_tracer: QueryTraceStatisticsSourcePort | None,
) -> JsonObject: ...
```

Delete `TYPE_CHECKING` and the imports from `routing.contracts` and `runtime.ports` in this file.

- [ ] **Step 4: Make runtime graph-data results opaque**

In `rag_modules/runtime/ports.py`, change the typing import to:

```python
from typing import Protocol
```

Delete the `TYPE_CHECKING` block that imports build-pipeline DTOs, then use:

```python
def load_graph_data(self) -> object: ...

def get_statistics(self) -> object: ...
```

Keep every other `GraphDataModulePort`, `VectorIndexModulePort`, and `QueryTracerPort` member
unchanged.

- [ ] **Step 5: Run runtime, build, and app diagnostics tests and verify GREEN**

Run:

```powershell
python -m pytest tests/test_runtime_stats_adapters.py tests/test_runtime_artifact_adapters.py tests/test_runtime_diagnostics_service.py tests/test_build_pipeline_stats_presenter.py tests/test_knowledge_base_workflow.py tests/test_runtime_type_contracts.py -q
```

Expected: PASS.

Run:

```powershell
python -m mypy rag_modules/runtime/ports.py rag_modules/runtime/stats_ports.py rag_modules/runtime/stats_adapters.py rag_modules/build_pipeline/stats_presenter.py rag_modules/app/services/runtime_diagnostics_service.py
```

Expected: PASS with no type errors.

- [ ] **Step 6: Commit the runtime port convergence**

```powershell
git add rag_modules/runtime/ports.py rag_modules/runtime/stats_ports.py rag_modules/runtime/stats_adapters.py tests/test_runtime_stats_adapters.py
git commit -m "refactor: narrow runtime statistics ports"
```

---

### Task 3: Install the Runtime-and-Type DAG Gate

**Files:**

- Create: `tests/import_dag_policy.py`
- Modify: `tests/test_import_dag.py`

**Interfaces:**

- Produces: one AST inventory of `ImportEdge` records labeled `runtime` or `type`.
- Produces: separately checked runtime and semantic graphs.
- Enforces: exact module classification and `ALLOWED_IMPORTS` for all inter-node edges.
- Preserves: source-only testing with no production module imports or external services.

- [ ] **Step 1: Add a failing type-edge collector test**

Before replacing the current collector, append this focused test to `tests/test_import_dag.py`:

```python
def test_type_checking_body_and_runtime_else_are_classified_separately() -> None:
    imports = _collect_imports_from_source(
        """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..build_pipeline.ports import GraphDataModulePort
else:
    from ..contracts import RetrievalRequest
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {(item.target_module, item.kind) for item in imports} == {
        ("typing", "runtime"),
        ("rag_modules.build_pipeline.ports", "type"),
        ("rag_modules.contracts", "runtime"),
    }
```

- [ ] **Step 2: Run the collector test and verify RED**

Run:

```powershell
python -m pytest tests/test_import_dag.py::test_type_checking_body_and_runtime_else_are_classified_separately -q
```

Expected: FAIL because `_collect_imports_from_source` and dependency kinds do not exist.

- [ ] **Step 3: Add the reviewed architectural policy**

Create `tests/import_dag_policy.py`:

```python
from __future__ import annotations

CONTROLLED_LAZY_IMPORT_FILES = frozenset(
    {
        "rag_modules/__init__.py",
        "rag_modules/graph/__init__.py",
        "rag_modules/infra/__init__.py",
        "rag_modules/query_understanding/__init__.py",
        "rag_modules/retrieval/__init__.py",
        "rag_modules/routing/__init__.py",
    }
)

EXACT_MODULE_NODES = {
    "rag_modules": "package_root",
    "rag_modules.evaluation": "evaluation",
    "rag_modules.langchain_document_adapter": "langchain_adapter",
    "rag_modules.public_surface_manifest": "public_surface",
    "rag_modules.safe_logging": "safe_logging",
    "rag_modules.telemetry": "telemetry",
    "rag_modules.trace_privacy": "trace_privacy",
}

NODE_PREFIXES = {
    "app": ("rag_modules.app",),
    "application": ("rag_modules.application",),
    "build_pipeline": ("rag_modules.build_pipeline",),
    "configuration": ("rag_modules.configuration",),
    "contracts": ("rag_modules.contracts",),
    "domain": ("rag_modules.domain",),
    "evidence_processing": ("rag_modules.evidence_processing",),
    "generation": ("rag_modules.generation",),
    "graph": ("rag_modules.graph",),
    "graph_index": ("rag_modules.graph_index",),
    "infra": ("rag_modules.infra",),
    "interfaces": ("rag_modules.interfaces",),
    "kernel": ("rag_modules.kernel",),
    "observability": ("rag_modules.observability",),
    "query_policy": ("rag_modules.query_policy",),
    "query_understanding": ("rag_modules.query_understanding",),
    "retrieval": ("rag_modules.retrieval",),
    "routing": ("rag_modules.routing",),
    "runtime": ("rag_modules.runtime",),
}

ALLOWED_IMPORTS = {
    "package_root": frozenset({"app", "application", "generation", "infra"}),
    "app": frozenset(
        {
            "application",
            "build_pipeline",
            "configuration",
            "contracts",
            "generation",
            "graph",
            "infra",
            "kernel",
            "observability",
            "query_policy",
            "query_understanding",
            "retrieval",
            "routing",
            "runtime",
            "telemetry",
        }
    ),
    "application": frozenset({"contracts", "kernel", "safe_logging"}),
    "build_pipeline": frozenset(
        {"configuration", "contracts", "domain", "infra", "kernel", "runtime", "safe_logging"}
    ),
    "configuration": frozenset({"contracts", "kernel", "query_policy"}),
    "contracts": frozenset({"kernel"}),
    "domain": frozenset({"kernel"}),
    "evidence_processing": frozenset({"contracts"}),
    "generation": frozenset(
        {
            "configuration",
            "contracts",
            "evidence_processing",
            "infra",
            "kernel",
            "query_policy",
            "safe_logging",
        }
    ),
    "graph": frozenset(
        {
            "configuration",
            "contracts",
            "evidence_processing",
            "graph_index",
            "kernel",
            "query_policy",
            "query_understanding",
            "retrieval",
            "runtime",
            "safe_logging",
        }
    ),
    "graph_index": frozenset({"kernel", "query_policy", "query_understanding"}),
    "infra": frozenset({"contracts", "kernel", "safe_logging"}),
    "interfaces": frozenset(
        {
            "app",
            "application",
            "configuration",
            "contracts",
            "kernel",
            "query_policy",
            "runtime",
            "safe_logging",
            "telemetry",
        }
    ),
    "kernel": frozenset(),
    "observability": frozenset(
        {"configuration", "contracts", "kernel", "safe_logging", "trace_privacy"}
    ),
    "query_policy": frozenset(),
    "query_understanding": frozenset(
        {"contracts", "kernel", "query_policy", "safe_logging"}
    ),
    "retrieval": frozenset(
        {
            "configuration",
            "contracts",
            "evidence_processing",
            "graph_index",
            "infra",
            "kernel",
            "query_understanding",
            "runtime",
            "safe_logging",
        }
    ),
    "routing": frozenset(
        {
            "contracts",
            "kernel",
            "query_policy",
            "query_understanding",
            "retrieval",
            "safe_logging",
        }
    ),
    "runtime": frozenset({"contracts", "kernel", "safe_logging"}),
    "evaluation": frozenset(),
    "langchain_adapter": frozenset({"kernel"}),
    "public_surface": frozenset(),
    "safe_logging": frozenset(),
    "telemetry": frozenset(),
    "trace_privacy": frozenset({"contracts"}),
}
```

- [ ] **Step 4: Replace the AST gate with a kind-aware inventory**

Replace `tests/test_import_dag.py` with the implementation below. Keep the focused collector test
from Step 1 at the end of the file.

```python
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Mapping

from tests.import_dag_policy import (
    ALLOWED_IMPORTS,
    CONTROLLED_LAZY_IMPORT_FILES,
    EXACT_MODULE_NODES,
    NODE_PREFIXES,
)

ROOT = Path(__file__).resolve().parents[1]
RAG_MODULES = ROOT / "rag_modules"
DependencyKind = Literal["runtime", "type"]


@dataclass(frozen=True, slots=True)
class RawImport:
    target_module: str
    line: int
    kind: DependencyKind


@dataclass(frozen=True, slots=True)
class ImportEdge:
    source_module: str
    target_module: str
    source_node: str
    target_node: str
    path: Path
    line: int
    kind: DependencyKind


@dataclass(frozen=True, slots=True)
class ImportInventory:
    classification_errors: tuple[str, ...]
    dynamic_import_errors: tuple[str, ...]
    edges: tuple[ImportEdge, ...]


def _module_name(path: Path, *, root: Path = ROOT) -> tuple[str, bool]:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def architectural_nodes(
    module: str,
    *,
    exact_modules: Mapping[str, str] = EXACT_MODULE_NODES,
    node_prefixes: Mapping[str, tuple[str, ...]] = NODE_PREFIXES,
) -> tuple[str, ...]:
    matches: list[tuple[int, str]] = []
    exact_owner = exact_modules.get(module)
    if exact_owner is not None:
        matches.append((len(module), exact_owner))
    matches.extend(
        (len(prefix), node)
        for node, prefixes in node_prefixes.items()
        for prefix in prefixes
        if module == prefix or module.startswith(f"{prefix}.")
    )
    if not matches:
        return ()
    longest = max(length for length, _node in matches)
    return tuple(sorted({node for length, node in matches if length == longest}))


def _resolve_import_from(
    source_module: str,
    *,
    is_package: bool,
    level: int,
    module: str | None,
) -> str:
    if level == 0:
        return module or ""
    package_parts = source_module.split(".") if is_package else source_module.split(".")[:-1]
    keep = max(0, len(package_parts) - (level - 1))
    suffix = (module or "").split(".") if module else []
    return ".".join([*package_parts[:keep], *suffix])


def _resolve_dynamic_target(source_module: str, target: str) -> str:
    if not target.startswith("."):
        return target
    level = len(target) - len(target.lstrip("."))
    return _resolve_import_from(
        source_module,
        is_package=True,
        level=level,
        module=target.lstrip("."),
    )


def _is_type_checking_guard(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _dynamic_import_function(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name) and node.id in {"import_module", "__import__"}:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr == "import_module":
        return "import_module"
    return None


class _ImportVisitor(ast.NodeVisitor):
    def __init__(
        self,
        *,
        source_module: str,
        is_package: bool,
        relative_path: str,
    ) -> None:
        self.source_module = source_module
        self.is_package = is_package
        self.relative_path = relative_path
        self.kind: DependencyKind = "runtime"
        self.imports: list[RawImport] = []
        self.dynamic_import_errors: list[str] = []

    def _record(self, target_module: str, line: int) -> None:
        if target_module:
            self.imports.append(RawImport(target_module, line, self.kind))

    def visit_If(self, node: ast.If) -> None:
        if not _is_type_checking_guard(node.test):
            self.generic_visit(node)
            return
        previous_kind = self.kind
        self.kind = "type"
        for child in node.body:
            self.visit(child)
        self.kind = previous_kind
        for child in node.orelse:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record(
            _resolve_import_from(
                self.source_module,
                is_package=self.is_package,
                level=node.level,
                module=node.module,
            ),
            node.lineno,
        )

    def visit_Call(self, node: ast.Call) -> None:
        function_name = _dynamic_import_function(node.func)
        if function_name is None:
            self.generic_visit(node)
            return
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(
            node.args[0].value, str
        ):
            self._record(
                _resolve_dynamic_target(self.source_module, node.args[0].value),
                node.lineno,
            )
        elif self.relative_path not in CONTROLLED_LAZY_IMPORT_FILES:
            self.dynamic_import_errors.append(
                f"{self.relative_path}:{node.lineno}: non-literal {function_name}"
            )
        self.generic_visit(node)


def _lazy_table_imports(tree: ast.AST, source_module: str) -> list[RawImport]:
    imports: list[RawImport] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for value in node.values:
            if not (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value.startswith(".")
            ):
                continue
            imports.append(
                RawImport(
                    _resolve_dynamic_target(source_module, value.value),
                    value.lineno,
                    "runtime",
                )
            )
    return imports


def _collect_imports_from_source(
    source: str,
    *,
    source_module: str,
    is_package: bool,
    relative_path: str,
) -> list[RawImport]:
    tree = ast.parse(source, filename=relative_path)
    visitor = _ImportVisitor(
        source_module=source_module,
        is_package=is_package,
        relative_path=relative_path,
    )
    visitor.visit(tree)
    imports = list(visitor.imports)
    if relative_path in CONTROLLED_LAZY_IMPORT_FILES:
        imports.extend(_lazy_table_imports(tree, source_module))
    return sorted(set(imports), key=lambda item: (item.line, item.target_module, item.kind))


def _classification_error(module: str, owners: tuple[str, ...]) -> str:
    if not owners:
        return f"{module}: unclassified"
    return f"{module}: ambiguous owners {', '.join(owners)}"


@lru_cache(maxsize=1)
def _import_inventory() -> ImportInventory:
    classification_errors: list[str] = []
    dynamic_import_errors: list[str] = []
    edges: set[ImportEdge] = set()
    for path in sorted(RAG_MODULES.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source_module, is_package = _module_name(path)
        source_owners = architectural_nodes(source_module)
        if len(source_owners) != 1:
            classification_errors.append(_classification_error(source_module, source_owners))
            continue
        source_node = source_owners[0]
        relative_path = path.relative_to(ROOT).as_posix()
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=relative_path)
        visitor = _ImportVisitor(
            source_module=source_module,
            is_package=is_package,
            relative_path=relative_path,
        )
        visitor.visit(tree)
        raw_imports = list(visitor.imports)
        dynamic_import_errors.extend(visitor.dynamic_import_errors)
        if relative_path in CONTROLLED_LAZY_IMPORT_FILES:
            raw_imports.extend(_lazy_table_imports(tree, source_module))
        for item in raw_imports:
            target = item.target_module
            if target != "rag_modules" and not target.startswith("rag_modules."):
                continue
            target_owners = architectural_nodes(target)
            if len(target_owners) != 1:
                classification_errors.append(_classification_error(target, target_owners))
                continue
            target_node = target_owners[0]
            if target_node == source_node:
                continue
            edges.add(
                ImportEdge(
                    source_module=source_module,
                    target_module=target,
                    source_node=source_node,
                    target_node=target_node,
                    path=path,
                    line=item.line,
                    kind=item.kind,
                )
            )
    return ImportInventory(
        classification_errors=tuple(sorted(set(classification_errors))),
        dynamic_import_errors=tuple(sorted(set(dynamic_import_errors))),
        edges=tuple(
            sorted(
                edges,
                key=lambda edge: (
                    edge.path.as_posix(),
                    edge.line,
                    edge.source_node,
                    edge.target_node,
                    edge.kind,
                ),
            )
        ),
    )


def _strongly_connected_components(edges: tuple[ImportEdge, ...]) -> list[tuple[str, ...]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for node in ALLOWED_IMPORTS:
        adjacency.setdefault(node, set())
    for edge in edges:
        adjacency[edge.source_node].add(edge.target_node)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in sorted(adjacency[node]):
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            target = stack.pop()
            on_stack.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in sorted(adjacency):
        if node not in indices:
            visit(node)
    return sorted(components)


def _concrete_cycle(
    component: tuple[str, ...],
    edges: tuple[ImportEdge, ...],
) -> list[ImportEdge]:
    members = set(component)
    adjacency: dict[str, list[ImportEdge]] = defaultdict(list)
    for edge in edges:
        if edge.source_node in members and edge.target_node in members:
            adjacency[edge.source_node].append(edge)
    active: dict[str, int] = {}
    visited: set[str] = set()
    path_nodes: list[str] = []
    path_edges: list[ImportEdge] = []

    def visit(node: str) -> list[ImportEdge] | None:
        active[node] = len(path_nodes)
        path_nodes.append(node)
        for edge in sorted(
            adjacency[node],
            key=lambda item: (item.target_node, item.path.as_posix(), item.line, item.kind),
        ):
            target = edge.target_node
            if target in active:
                return [*path_edges[active[target] :], edge]
            if target in visited:
                continue
            path_edges.append(edge)
            cycle = visit(target)
            if cycle is not None:
                return cycle
            path_edges.pop()
        path_nodes.pop()
        active.pop(node)
        visited.add(node)
        return None

    for node in component:
        if node in visited:
            continue
        cycle = visit(node)
        if cycle is not None:
            return cycle
    raise AssertionError(f"could not render cycle for component {component}")


def _format_component(component: tuple[str, ...], edges: tuple[ImportEdge, ...]) -> str:
    cycle = _concrete_cycle(component, edges)
    node_path = [cycle[0].source_node, *(edge.target_node for edge in cycle)]
    details = [" -> ".join(node_path)]
    details.extend(
        f"  {edge.source_node} -[{edge.kind} {edge.path.relative_to(ROOT)}:{edge.line}]-> "
        f"{edge.target_node}"
        for edge in cycle
    )
    return "\n".join(details)


def test_type_checking_body_and_runtime_else_are_classified_separately() -> None:
    imports = _collect_imports_from_source(
        """
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..build_pipeline.ports import GraphDataModulePort
else:
    from ..contracts import RetrievalRequest
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {(item.target_module, item.kind) for item in imports} == {
        ("typing", "runtime"),
        ("rag_modules.build_pipeline.ports", "type"),
        ("rag_modules.contracts", "runtime"),
    }


def test_unknown_and_ambiguous_modules_do_not_receive_an_owner() -> None:
    assert architectural_nodes("rag_modules.new_subsystem.module") == ()
    assert architectural_nodes(
        "rag_modules.overlap.module",
        exact_modules={},
        node_prefixes={
            "first": ("rag_modules.overlap",),
            "second": ("rag_modules.overlap",),
        },
    ) == ("first", "second")


def test_every_module_is_classified_and_every_edge_is_allowed() -> None:
    inventory = _import_inventory()
    declared_nodes = set(EXACT_MODULE_NODES.values()) | set(NODE_PREFIXES)
    assert set(ALLOWED_IMPORTS) == declared_nodes
    assert not inventory.classification_errors, "Classification errors:\n" + "\n".join(
        inventory.classification_errors
    )
    assert not inventory.dynamic_import_errors, "Dynamic import errors:\n" + "\n".join(
        inventory.dynamic_import_errors
    )
    forbidden = [
        edge
        for edge in inventory.edges
        if edge.target_node not in ALLOWED_IMPORTS[edge.source_node]
    ]
    assert not forbidden, "Forbidden import edges:\n" + "\n".join(
        f"{edge.path.relative_to(ROOT)}:{edge.line}: {edge.kind} "
        f"{edge.source_node} -> {edge.target_node} ({edge.target_module})"
        for edge in forbidden
    )


def test_runtime_and_semantic_import_graphs_are_acyclic() -> None:
    inventory = _import_inventory()
    runtime_edges = tuple(edge for edge in inventory.edges if edge.kind == "runtime")
    semantic_edges = inventory.edges
    failures: list[str] = []
    for graph_name, edges in (("runtime", runtime_edges), ("semantic", semantic_edges)):
        components = _strongly_connected_components(edges)
        if components:
            failures.append(
                f"{graph_name} graph:\n"
                + "\n\n".join(_format_component(component, edges) for component in components)
            )
    assert not failures, "Cyclic import graphs:\n" + "\n\n".join(failures)
```

- [ ] **Step 5: Run the upgraded gate and verify GREEN**

Run:

```powershell
python -m pytest tests/test_import_dag.py -q
```

Expected: four tests PASS. The inventory contains no runtime SCC, semantic SCC, unclassified
module, dynamic-import violation, or forbidden edge.

- [ ] **Step 6: Run architecture and public-surface guards**

Run:

```powershell
python -m pytest tests/test_import_dag.py tests/test_dependency_isolation.py tests/test_public_surface_boundaries.py tests/test_public_surface_build_boundaries.py tests/test_public_surface_runtime_boundaries.py tests/test_public_api_manifest.py tests/test_module_boundary_facades.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit the semantic DAG gate**

```powershell
git add tests/import_dag_policy.py tests/test_import_dag.py
git commit -m "test: enforce semantic import dag policy"
```

---

### Task 4: Verify the Hard Cutover and Release Gate

**Files:**

- Verify: all files changed in Tasks 1-3
- Modify only if formatter output requires it: files changed in Tasks 1-3

**Interfaces:**

- Consumes: canonical graph-preparation contracts, runtime-owned statistics ports, and the
  repository-wide semantic DAG policy.
- Produces: fresh evidence that focused behavior, typing, formatting, the full suite, and the
  offline release gate pass.

- [ ] **Step 1: Prove old imports and reverse dependencies are absent**

Run:

```powershell
rg -n --glob '*.py' "build_pipeline\.graph_preparation\.(models|statistics)|from \.graph_preparation\.(models|statistics)|from \.\.routing\.contracts import RoutingWorkflowProtocol" rag_modules tests
```

Expected: no matches; `rg` exits 1 because the retired imports are absent.

Run:

```powershell
rg -n --glob '*.py' --pcre2 'class (GraphNode|GraphLoadCounts|GraphPreparationStats)\b' rag_modules
```

Expected: exactly three matches, all in
`rag_modules/contracts/graph_preparation.py`.

- [ ] **Step 2: Run the focused behavior and architecture suite**

Run:

```powershell
python -m pytest tests/test_graph_preparation_contracts.py tests/test_graph_data_preparation_module.py tests/test_document_artifact_cache.py tests/test_runtime_stats_adapters.py tests/test_runtime_artifact_adapters.py tests/test_runtime_diagnostics_service.py tests/test_build_pipeline_stats_presenter.py tests/test_knowledge_base_workflow.py tests/test_runtime_type_contracts.py tests/test_consumer_owned_ports.py tests/test_import_dag.py tests/test_dependency_isolation.py tests/test_public_api_manifest.py tests/test_type_contract_ratchets.py -q
```

Expected: PASS.

- [ ] **Step 3: Run mypy and repository hooks**

Run:

```powershell
python -m mypy rag_modules tests/typecheck
```

Expected: PASS with no type errors.

Run:

```powershell
pre-commit run --all-files
```

Expected: all hooks PASS. If Ruff changes a file, inspect the diff and rerun the complete command
until it passes without further edits.

- [ ] **Step 4: Run the full test suite**

Run:

```powershell
python -m pytest -q
```

Expected: PASS with zero failures.

- [ ] **Step 5: Run the offline release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: exit code 0 and all offline release checks PASS.

- [ ] **Step 6: Inspect the final diff and commit formatter-only follow-ups if needed**

Run:

```powershell
git status --short
git diff --check
git diff --stat
```

Expected: only the planned files are changed and `git diff --check` reports no whitespace errors.
If pre-commit produced formatter-only edits after the Task 3 commit, commit only those edits:

```powershell
git add rag_modules tests
git commit -m "style: format semantic dag changes"
```
