from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_MODULES = ROOT / "rag_modules"


def _module_name(path: Path) -> tuple[str, bool]:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _is_type_checking_guard(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _resolve_import_from(
    current_module: str,
    is_package: bool,
    node: ast.ImportFrom,
) -> str | None:
    if node.level == 0:
        return node.module

    current_parts = current_module.split(".")
    package_parts = current_parts if is_package else current_parts[:-1]
    keep = max(0, len(package_parts) - (node.level - 1))
    resolved_parts = package_parts[:keep]
    if node.module:
        resolved_parts.extend(node.module.split("."))
    return ".".join(resolved_parts)


class _ImportVisitor(ast.NodeVisitor):
    def __init__(self, current_module: str, is_package: bool) -> None:
        self.current_module = current_module
        self.is_package = is_package
        self.imported_modules: list[str] = []

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking_guard(node.test):
            for child in node.orelse:
                self.visit(child)
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.imported_modules.extend(alias.name for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module_name = _resolve_import_from(self.current_module, self.is_package, node)
        if module_name:
            self.imported_modules.append(module_name)


def _internal_package_import_graph() -> dict[str, set[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    modules = {
        path: _module_name(path)
        for path in RAG_MODULES.rglob("*.py")
        if "__pycache__" not in path.parts
    }
    owners = {
        module_name.split(".")[1]
        for module_name, _is_package in modules.values()
        if module_name.startswith("rag_modules.") and len(module_name.split(".")) > 1
    }

    for owner in owners:
        graph.setdefault(owner, set())

    for path, (current_module, is_package) in modules.items():
        current_parts = current_module.split(".")
        if len(current_parts) < 2:
            continue
        source_owner = current_parts[1]
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        visitor = _ImportVisitor(current_module, is_package)
        visitor.visit(tree)

        for imported_module in visitor.imported_modules:
            if imported_module != "rag_modules" and not imported_module.startswith("rag_modules."):
                continue
            imported_parts = imported_module.split(".")
            if len(imported_parts) < 2:
                continue
            target_owner = imported_parts[1]
            if target_owner != source_owner:
                graph[source_owner].add(target_owner)

    return graph


def _strongly_connected_components(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[tuple[str, ...]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for dependency in sorted(graph[node]):
            if dependency not in indices:
                strongconnect(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dependency])

        if lowlinks[node] != indices[node]:
            return

        component: list[str] = []
        while True:
            dependency = stack.pop()
            on_stack.remove(dependency)
            component.append(dependency)
            if dependency == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            strongconnect(node)

    return sorted(components, key=lambda item: (-len(item), item))


def test_rag_modules_internal_import_graph_is_acyclic() -> None:
    graph = _internal_package_import_graph()
    cycles = _strongly_connected_components(graph)

    details = []
    for component in cycles:
        component_set = set(component)
        edges = [
            f"{source} -> {target}"
            for source in component
            for target in sorted(graph[source] & component_set)
        ]
        details.append(f"{', '.join(component)}\n  " + "\n  ".join(edges))

    assert cycles == [], "Found cyclic rag_modules package imports:\n" + "\n\n".join(details)


def test_interfaces_do_not_import_retrieval_implementations() -> None:
    violations: list[str] = []
    interfaces_dir = RAG_MODULES / "interfaces"

    for path in interfaces_dir.rglob("*.py"):
        module_name, is_package = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        visitor = _ImportVisitor(module_name, is_package)
        visitor.visit(tree)
        for imported_module in visitor.imported_modules:
            if imported_module == "rag_modules.retrieval" or imported_module.startswith(
                "rag_modules.retrieval."
            ):
                violations.append(f"{path.relative_to(ROOT)} imports {imported_module}")

    assert violations == []
