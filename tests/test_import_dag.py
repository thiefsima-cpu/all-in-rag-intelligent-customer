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
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
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
