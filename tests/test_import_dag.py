from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
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


@dataclass(slots=True)
class _BindingState:
    dynamic_loaders: dict[str, str] = field(default_factory=lambda: {"__import__": "__import__"})
    importlib_aliases: set[str] = field(default_factory=set)
    builtins_aliases: set[str] = field(default_factory=set)
    lazy_dynamic_targets: set[str] = field(default_factory=set)
    type_checking_names: set[str] = field(default_factory=set)
    typing_aliases: set[str] = field(default_factory=set)

    def copy(self) -> _BindingState:
        return _BindingState(
            dynamic_loaders=dict(self.dynamic_loaders),
            importlib_aliases=set(self.importlib_aliases),
            builtins_aliases=set(self.builtins_aliases),
            lazy_dynamic_targets=set(self.lazy_dynamic_targets),
            type_checking_names=set(self.type_checking_names),
            typing_aliases=set(self.typing_aliases),
        )

    @classmethod
    def merge(cls, states: tuple[_BindingState, ...]) -> _BindingState:
        if not states:
            raise ValueError("binding-state merge requires at least one state")
        loader_kinds: dict[str, set[str]] = defaultdict(set)
        for state in states:
            for name, kind in state.dynamic_loaders.items():
                loader_kinds[name].add(kind)
        dynamic_loaders = {
            name: ("import_module" if "import_module" in kinds else sorted(kinds)[0])
            for name, kinds in loader_kinds.items()
        }
        lazy_dynamic_targets = set(states[0].lazy_dynamic_targets)
        for state in states[1:]:
            lazy_dynamic_targets.intersection_update(state.lazy_dynamic_targets)
        return cls(
            dynamic_loaders=dynamic_loaders,
            importlib_aliases=set().union(*(state.importlib_aliases for state in states)),
            builtins_aliases=set().union(*(state.builtins_aliases for state in states)),
            lazy_dynamic_targets=lazy_dynamic_targets,
            type_checking_names=set().union(*(state.type_checking_names for state in states)),
            typing_aliases=set().union(*(state.typing_aliases for state in states)),
        )


def _inventory_edge_sort_key(
    edge: ImportEdge,
) -> tuple[str, int, str, str, DependencyKind, str, str]:
    return (
        edge.path.as_posix(),
        edge.line,
        edge.source_node,
        edge.target_node,
        edge.kind,
        edge.source_module,
        edge.target_module,
    )


def _concrete_cycle_edge_sort_key(
    edge: ImportEdge,
) -> tuple[str, str, int, DependencyKind, str, str]:
    return (
        edge.target_node,
        edge.path.as_posix(),
        edge.line,
        edge.kind,
        edge.source_module,
        edge.target_module,
    )


def _module_name(path: Path, *, root: Path = ROOT) -> tuple[str, bool]:
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


@lru_cache(maxsize=1)
def _production_module_index() -> frozenset[str]:
    return frozenset(
        _module_name(path)[0]
        for path in RAG_MODULES.rglob("*.py")
        if "__pycache__" not in path.parts
    )


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


def _source_package(source_module: str, *, is_package: bool) -> str:
    if is_package:
        return source_module
    return source_module.rpartition(".")[0]


def _resolve_dynamic_target(
    source_module: str,
    target: str,
    *,
    is_package: bool,
    package: str | None = None,
) -> str:
    if not target.startswith("."):
        return target
    level = len(target) - len(target.lstrip("."))
    return _resolve_import_from(
        package or _source_package(source_module, is_package=is_package),
        is_package=True,
        level=level,
        module=target.lstrip("."),
    )


def _literal_lazy_export_definition(
    statement: ast.stmt,
) -> tuple[str, tuple[ast.Constant, ...]] | None:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
        target = statement.targets[0]
        value = statement.value
    elif isinstance(statement, ast.AnnAssign):
        target = statement.target
        value = statement.value
    else:
        return None
    if not (
        isinstance(target, ast.Name)
        and target.id.endswith("_EXPORTS")
        and isinstance(value, ast.Dict)
        and value.keys
        and all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in value.keys)
        and all(
            isinstance(item, ast.Constant)
            and isinstance(item.value, str)
            and item.value.startswith(".")
            for item in value.values
        )
    ):
        return None
    return target.id, tuple(item for item in value.values if isinstance(item, ast.Constant))


def _mutation_root_name(target: ast.AST) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Subscript):
        return _mutation_root_name(target.value)
    return None


class _LazyTableMutationVisitor(ast.NodeVisitor):
    _MUTATING_METHODS = frozenset(
        {"__setitem__", "clear", "pop", "popitem", "setdefault", "update"}
    )

    def __init__(self, definitions: Mapping[str, ast.stmt]) -> None:
        self.definitions = definitions
        self.aliases = {name: name for name in definitions}
        self.mutations: set[tuple[str, int]] = set()

    def _record_target(self, target: ast.AST, statement: ast.AST) -> None:
        binding = _mutation_root_name(target)
        name = self.aliases.get(binding or "")
        if name is None:
            return
        if isinstance(target, ast.Name) and binding == name and statement is self.definitions[name]:
            return
        if isinstance(target, ast.Name) and binding != name:
            return
        self.mutations.add((name, statement.lineno))

    def _update_alias(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        if isinstance(value, ast.Name) and value.id in self.aliases:
            self.aliases[target.id] = self.aliases[value.id]
        elif target.id not in self.definitions:
            self.aliases.pop(target.id, None)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._record_target(target, node)
            self._update_alias(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self._record_target(node.target, node)
            self._update_alias(node.target, node.value)
        self.visit(node.annotation)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.value)
        self._record_target(node.target, node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self._record_target(node.target, node)
        self._update_alias(node.target, node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self._record_target(target, node)
            if isinstance(target, ast.Name):
                self.aliases.pop(target.id, None)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in self._MUTATING_METHODS:
            binding = _mutation_root_name(node.func.value)
            name = self.aliases.get(binding or "")
            if name is not None:
                self.mutations.add((name, node.lineno))
        self.generic_visit(node)


def _lazy_export_table_analysis(
    tree: ast.Module,
) -> tuple[dict[str, tuple[ast.Constant, ...]], tuple[tuple[str, int], ...]]:
    tables: dict[str, tuple[ast.Constant, ...]] = {}
    definitions: dict[str, ast.stmt] = {}
    for statement in tree.body:
        definition = _literal_lazy_export_definition(statement)
        if definition is None:
            continue
        name, values = definition
        if name not in definitions:
            definitions[name] = statement
            tables[name] = values
    visitor = _LazyTableMutationVisitor(definitions)
    visitor.visit(tree)
    mutations = tuple(sorted(visitor.mutations, key=lambda item: (item[1], item[0])))
    invalid_names = {name for name, _line in mutations}
    return (
        {name: values for name, values in tables.items() if name not in invalid_names},
        mutations,
    )


def _static_lazy_export_tables(tree: ast.Module) -> dict[str, tuple[ast.Constant, ...]]:
    tables, _mutations = _lazy_export_table_analysis(tree)
    return tables


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
        self.bindings = _BindingState()
        self.lazy_export_tables: set[str] = set()

    @property
    def dynamic_loaders(self) -> dict[str, str]:
        return self.bindings.dynamic_loaders

    @property
    def importlib_aliases(self) -> set[str]:
        return self.bindings.importlib_aliases

    @property
    def builtins_aliases(self) -> set[str]:
        return self.bindings.builtins_aliases

    @property
    def lazy_dynamic_targets(self) -> set[str]:
        return self.bindings.lazy_dynamic_targets

    @property
    def type_checking_names(self) -> set[str]:
        return self.bindings.type_checking_names

    @property
    def typing_aliases(self) -> set[str]:
        return self.bindings.typing_aliases

    def _visit_branch(
        self,
        statements: list[ast.stmt],
        initial: _BindingState,
        *,
        kind: DependencyKind | None = None,
    ) -> _BindingState:
        previous_bindings = self.bindings
        previous_kind = self.kind
        self.bindings = initial.copy()
        if kind is not None:
            self.kind = kind
        for statement in statements:
            self.visit(statement)
        result = self.bindings.copy()
        self.bindings = previous_bindings
        self.kind = previous_kind
        return result

    @staticmethod
    def _bound_names(target: ast.AST) -> tuple[str, ...]:
        if isinstance(target, ast.Name):
            return (target.id,)
        if isinstance(target, ast.Starred):
            return _ImportVisitor._bound_names(target.value)
        if isinstance(target, (ast.List, ast.Tuple)):
            return tuple(name for item in target.elts for name in _ImportVisitor._bound_names(item))
        return ()

    def _clear_binding(self, name: str) -> None:
        self._clear_dynamic_binding(name)
        self._clear_typing_binding(name)
        self.lazy_dynamic_targets.discard(name)

    def _clear_target_bindings(self, target: ast.AST) -> None:
        for name in self._bound_names(target):
            self._clear_binding(name)

    def _record(self, target_module: str, line: int) -> None:
        if target_module:
            self.imports.append(RawImport(target_module, line, self.kind))

    def _dynamic_package(self, node: ast.Call) -> str | None:
        package_node = node.args[1] if len(node.args) > 1 else None
        if package_node is None:
            package_node = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "package"),
                None,
            )
        if isinstance(package_node, ast.Constant) and isinstance(package_node.value, str):
            return package_node.value
        if isinstance(package_node, ast.Name) and package_node.id == "__package__":
            return _source_package(self.source_module, is_package=self.is_package)
        return None

    def _dynamic_import_function(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return self.dynamic_loaders.get(node.id)
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            return None
        if node.attr == "import_module" and node.value.id in self.importlib_aliases:
            return "import_module"
        if node.attr == "__import__" and node.value.id in self.builtins_aliases:
            return "__import__"
        return None

    def _clear_dynamic_binding(self, name: str) -> None:
        self.dynamic_loaders.pop(name, None)
        self.importlib_aliases.discard(name)
        self.builtins_aliases.discard(name)

    def _bind_dynamic_loader(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        function_name = self._dynamic_import_function(value)
        self._clear_dynamic_binding(target.id)
        if function_name is not None:
            self.dynamic_loaders[target.id] = function_name

    def _lazy_export_source(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = node.func.value
            if (
                node.func.attr == "get"
                and isinstance(owner, ast.Name)
                and owner.id in self.lazy_export_tables
                and len(node.args) == 1
                and not node.keywords
            ):
                return owner.id
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
            if node.value.id in self.lazy_export_tables:
                return node.value.id
        return None

    def _bind_lazy_target(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            return
        if self._lazy_export_source(value) is None:
            self.lazy_dynamic_targets.discard(target.id)
        else:
            self.lazy_dynamic_targets.add(target.id)

    def _is_lazy_dynamic_target(self, node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Name) and node.id in self.lazy_dynamic_targets
        ) or self._lazy_export_source(node) is not None

    def _is_type_checking_guard(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.type_checking_names
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "TYPE_CHECKING"
            and isinstance(node.value, ast.Name)
            and node.value.id in self.typing_aliases
        )

    def _clear_typing_binding(self, name: str) -> None:
        self.type_checking_names.discard(name)
        self.typing_aliases.discard(name)

    def visit_Module(self, node: ast.Module) -> None:
        tables, mutations = _lazy_export_table_analysis(node)
        self.lazy_export_tables = set(tables)
        if self.relative_path in CONTROLLED_LAZY_IMPORT_FILES:
            self.dynamic_import_errors.extend(
                f"{self.relative_path}:{line}: mutated lazy import table {name}"
                for name, line in mutations
            )
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        is_type_guard = self._is_type_checking_guard(node.test)
        self.visit(node.test)
        initial = self.bindings.copy()
        body_state = self._visit_branch(
            node.body,
            initial,
            kind="type" if is_type_guard else self.kind,
        )
        else_state = self._visit_branch(node.orelse, initial, kind=self.kind)
        self.bindings = (
            else_state if is_type_guard else _BindingState.merge((body_state, else_state))
        )

    def _visit_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        if node.args.vararg is not None:
            arguments.append(node.args.vararg)
        if node.args.kwarg is not None:
            arguments.append(node.args.kwarg)
        for argument in arguments:
            if argument.annotation is not None:
                self.visit(argument.annotation)
        if node.returns is not None:
            self.visit(node.returns)

    @staticmethod
    def _argument_names(arguments: ast.arguments) -> tuple[str, ...]:
        names = [
            argument.arg
            for argument in [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
            ]
        ]
        if arguments.vararg is not None:
            names.append(arguments.vararg.arg)
        if arguments.kwarg is not None:
            names.append(arguments.kwarg.arg)
        return tuple(names)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self._visit_function_signature(node)
        self._clear_binding(node.name)
        outer = self.bindings.copy()
        self.bindings = outer.copy()
        for name in self._argument_names(node.args):
            self._clear_binding(name)
        for statement in node.body:
            self.visit(statement)
        self.bindings = outer

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in node.args.defaults:
            self.visit(default)
        for default in node.args.kw_defaults:
            if default is not None:
                self.visit(default)
        outer = self.bindings
        self.bindings = outer.copy()
        for name in self._argument_names(node.args):
            self._clear_binding(name)
        self.visit(node.body)
        self.bindings = outer

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword.value)
        self._clear_binding(node.name)
        outer = self.bindings.copy()
        self.bindings = outer.copy()
        for statement in node.body:
            self.visit(statement)
        self.bindings = outer

    def _visit_try(self, node: ast.Try | ast.TryStar) -> None:
        initial = self.bindings.copy()
        previous = self.bindings
        self.bindings = initial.copy()
        exception_prefixes = [initial]
        for statement in node.body:
            self.visit(statement)
            exception_prefixes.append(self.bindings.copy())
        body_state = self.bindings.copy()
        self.bindings = previous
        exception_state = _BindingState.merge(tuple(exception_prefixes))
        success_state = self._visit_branch(node.orelse, body_state, kind=self.kind)
        alternatives = [success_state]
        for handler in node.handlers:
            previous = self.bindings
            self.bindings = exception_state.copy()
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name is not None:
                self._clear_binding(handler.name)
            for statement in handler.body:
                self.visit(statement)
            if handler.name is not None:
                self._clear_binding(handler.name)
            alternatives.append(self.bindings.copy())
            self.bindings = previous
        self.bindings = _BindingState.merge(tuple(alternatives))
        for statement in node.finalbody:
            self.visit(statement)

    def visit_Try(self, node: ast.Try) -> None:
        self._visit_try(node)

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._visit_try(node)

    def _visit_for(self, node: ast.For | ast.AsyncFor) -> None:
        self.visit(node.iter)
        initial = self.bindings.copy()
        loop_state = initial
        while True:
            previous = self.bindings
            self.bindings = loop_state.copy()
            self.visit(node.target)
            self._clear_target_bindings(node.target)
            for statement in node.body:
                self.visit(statement)
            body_state = self.bindings.copy()
            self.bindings = previous
            next_loop_state = _BindingState.merge((initial, body_state))
            if next_loop_state == loop_state:
                loop_state = next_loop_state
                break
            loop_state = next_loop_state
        else_state = self._visit_branch(node.orelse, loop_state, kind=self.kind)
        self.bindings = _BindingState.merge((loop_state, else_state))

    def visit_For(self, node: ast.For) -> None:
        self._visit_for(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._visit_for(node)

    def visit_While(self, node: ast.While) -> None:
        self.visit(node.test)
        initial = self.bindings.copy()
        loop_state = initial
        while True:
            body_state = self._visit_branch(node.body, loop_state, kind=self.kind)
            next_loop_state = _BindingState.merge((initial, body_state))
            if next_loop_state == loop_state:
                loop_state = next_loop_state
                break
            loop_state = next_loop_state
        else_state = self._visit_branch(node.orelse, loop_state, kind=self.kind)
        self.bindings = _BindingState.merge((loop_state, else_state))

    def _visit_with(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self.visit(item.optional_vars)
                self._clear_target_bindings(item.optional_vars)
        for statement in node.body:
            self.visit(statement)

    def visit_With(self, node: ast.With) -> None:
        self._visit_with(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self._visit_with(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node.lineno)
            binding = alias.asname or alias.name.split(".", maxsplit=1)[0]
            self._clear_dynamic_binding(binding)
            self._clear_typing_binding(binding)
            if alias.name == "importlib":
                self.importlib_aliases.add(binding)
            elif alias.name == "builtins":
                self.builtins_aliases.add(binding)
            elif alias.name == "typing":
                self.typing_aliases.add(binding)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        target_module = _resolve_import_from(
            self.source_module,
            is_package=self.is_package,
            level=node.level,
            module=node.module,
        )
        self._record(target_module, node.lineno)
        for alias in node.names:
            imported_module = ".".join(part for part in (target_module, alias.name) if part)
            if imported_module in _production_module_index():
                self._record(imported_module, node.lineno)
            binding = alias.asname or alias.name
            self._clear_dynamic_binding(binding)
            self._clear_typing_binding(binding)
            if node.level == 0 and node.module == "importlib" and alias.name == "import_module":
                self.dynamic_loaders[binding] = "import_module"
            elif node.level == 0 and node.module == "builtins" and alias.name == "__import__":
                self.dynamic_loaders[binding] = "__import__"
            elif node.level == 0 and node.module == "typing" and alias.name == "TYPE_CHECKING":
                self.type_checking_names.add(binding)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self.visit(target)
            self._bind_assignment_target(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is None:
            self.visit(node.target)
            self.visit(node.annotation)
            return
        self.visit(node.value)
        self.visit(node.target)
        self._bind_assignment_target(node.target, node.value)
        self.visit(node.annotation)

    def _bind_assignment_target(self, target: ast.AST, value: ast.AST) -> None:
        if not isinstance(target, ast.Name):
            self._clear_target_bindings(target)
            return
        self._clear_typing_binding(target.id)
        self._bind_dynamic_loader(target, value)
        self._bind_lazy_target(target, value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self.visit(node.target)
        self.visit(node.value)
        self._clear_target_bindings(node.target)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        self.visit(node.target)
        self._bind_assignment_target(node.target, node.value)

    def visit_Delete(self, node: ast.Delete) -> None:
        for target in node.targets:
            self.visit(target)
            self._clear_target_bindings(target)

    def visit_Call(self, node: ast.Call) -> None:
        function_name = self._dynamic_import_function(node.func)
        if function_name is None:
            self.generic_visit(node)
            return
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            self._record(
                _resolve_dynamic_target(
                    self.source_module,
                    node.args[0].value,
                    is_package=self.is_package,
                    package=self._dynamic_package(node),
                ),
                node.lineno,
            )
        elif not (
            self.relative_path in CONTROLLED_LAZY_IMPORT_FILES
            and node.args
            and self._is_lazy_dynamic_target(node.args[0])
        ):
            self.dynamic_import_errors.append(
                f"{self.relative_path}:{node.lineno}: non-literal {function_name}"
            )
        self.generic_visit(node)


def _lazy_table_imports(tree: ast.AST, source_module: str) -> list[RawImport]:
    imports: list[RawImport] = []
    if not isinstance(tree, ast.Module):
        return imports
    for values in _static_lazy_export_tables(tree).values():
        for value in values:
            imports.append(
                RawImport(
                    _resolve_dynamic_target(source_module, value.value, is_package=True),
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
        edges=tuple(sorted(edges, key=_inventory_edge_sort_key)),
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
            key=_concrete_cycle_edge_sort_key,
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


def test_import_from_records_an_existing_internal_submodule() -> None:
    imports = _collect_imports_from_source(
        """
from . import AdvancedGraphRAGSystem
from . import query_understanding
""",
        source_module="rag_modules",
        is_package=True,
        relative_path="rag_modules/__init__.py",
    )

    assert {item.target_module for item in imports} == {
        "rag_modules",
        "rag_modules.query_understanding",
    }


def test_relative_dynamic_import_from_module_uses_its_package() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module

import_module("..generation", __package__)
import_module(".contracts", package="rag_modules")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {item.target_module for item in imports} == {
        "importlib",
        "rag_modules.contracts",
        "rag_modules.generation",
    }


def test_aliased_dynamic_import_loaders_are_detected() -> None:
    imports = _collect_imports_from_source(
        """
import importlib as il
import builtins as bi
from builtins import __import__ as builtin_load
from importlib import import_module as load

load("rag_modules.generation")
il.import_module("rag_modules.retrieval")
builtin_load("rag_modules.graph")
assigned_load = __import__
assigned_load("rag_modules.routing")
bi.__import__("rag_modules.kernel")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {item.target_module for item in imports} == {
        "builtins",
        "importlib",
        "rag_modules.generation",
        "rag_modules.graph",
        "rag_modules.kernel",
        "rag_modules.retrieval",
        "rag_modules.routing",
    }


def test_dynamic_import_aliases_stop_matching_after_rebinding() -> None:
    source = """
import builtins as bi
import importlib as il
from importlib import import_module as load

bi = object()
il = object()
from config import load as load

bi.__import__(requested)
il.import_module(requested)
load(requested)
"""
    tree = ast.parse(source, filename="rag_modules/runtime/sample.py")
    visitor = _ImportVisitor(
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )
    visitor.visit(tree)

    assert visitor.dynamic_import_errors == []


def test_assignment_rhs_uses_loader_binding_before_plain_and_annotated_rebinding() -> None:
    source = """
from importlib import import_module as load
from importlib import import_module as annotated_load

load = load("rag_modules.generation")
annotated_load: object = annotated_load("rag_modules.retrieval")
"""
    tree = ast.parse(source, filename="rag_modules/runtime/sample.py")
    visitor = _ImportVisitor(
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )
    visitor.visit(tree)

    assert [item for item in visitor.imports if item.target_module.startswith("rag_modules.")] == [
        RawImport("rag_modules.generation", 5, "runtime"),
        RawImport("rag_modules.retrieval", 6, "runtime"),
    ]


def test_function_scope_shadow_does_not_erase_outer_loader_or_type_guard() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module
from typing import TYPE_CHECKING

def helper():
    import_module = object()
    TYPE_CHECKING = False

import_module("rag_modules.generation")
if TYPE_CHECKING:
    from ..graph import GraphPath
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {
        (item.target_module, item.kind)
        for item in imports
        if item.target_module.startswith("rag_modules.")
    } == {
        ("rag_modules.generation", "runtime"),
        ("rag_modules.graph", "type"),
    }


def test_function_parameters_and_local_imports_stay_in_their_scope() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module

def shadowed(import_module):
    import_module("rag_modules.routing")

def local_loader():
    from importlib import import_module as local_load
    local_load("rag_modules.graph")

local_load("rag_modules.generation")
import_module("rag_modules.retrieval")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {
        item.target_module for item in imports if item.target_module.startswith("rag_modules.")
    } == {"rag_modules.graph", "rag_modules.retrieval"}


def test_if_and_try_branches_preserve_a_possible_loader_binding() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module as load

if condition:
    load = object()
load("rag_modules.generation")

try:
    load = object()
except Exception:
    pass
load("rag_modules.retrieval")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {
        item.target_module for item in imports if item.target_module.startswith("rag_modules.")
    } == {"rag_modules.generation", "rag_modules.retrieval"}


def test_try_handlers_preserve_loader_bound_before_a_possible_exception() -> None:
    imports = _collect_imports_from_source(
        """
import importlib

load = object()
try:
    load = importlib.import_module
    might_raise()
    load = object()
except Exception:
    pass
load("rag_modules.generation")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert "rag_modules.generation" in {item.target_module for item in imports}


def test_loops_reach_a_loader_binding_from_a_later_iteration() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module

for_load = object()
for item in items:
    for_load("rag_modules.generation")
    for_load = import_module

while_load = object()
while condition:
    while_load("rag_modules.retrieval")
    while_load = import_module
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {
        item.target_module for item in imports if item.target_module.startswith("rag_modules.")
    } == {"rag_modules.generation", "rag_modules.retrieval"}


def test_lazy_target_must_be_safe_on_every_if_branch() -> None:
    source = """
from importlib import import_module

_EXPORTS = {"Thing": ".thing"}

if condition:
    module_name = requested
else:
    module_name = _EXPORTS.get(name)
import_module(module_name, __name__)
"""
    tree = ast.parse(source, filename="rag_modules/__init__.py")
    visitor = _ImportVisitor(
        source_module="rag_modules",
        is_package=True,
        relative_path="rag_modules/__init__.py",
    )
    visitor.visit(tree)

    assert visitor.dynamic_import_errors == [
        "rag_modules/__init__.py:10: non-literal import_module"
    ]


def test_binding_targets_shadow_loaders_inside_their_runtime_region() -> None:
    imports = _collect_imports_from_source(
        """
from importlib import import_module as load

for load in loaders:
    load("rag_modules.generation")
with manager() as load:
    load("rag_modules.retrieval")
try:
    operation()
except Exception as load:
    load("rag_modules.graph")
load += replacement
load("rag_modules.routing")
(load := replacement)
load("rag_modules.app")
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert not [item for item in imports if item.target_module.startswith("rag_modules.")]


def test_controlled_lazy_file_rejects_unrelated_non_literal_loader_target() -> None:
    source = """
from importlib import import_module as load

_LAZY_EXPORTS = {"PublicThing": ".thing"}

def resolve(name, requested):
    module_name = _LAZY_EXPORTS.get(name)
    load(module_name, __name__)
    load(requested, __name__)
"""
    tree = ast.parse(source, filename="rag_modules/__init__.py")
    visitor = _ImportVisitor(
        source_module="rag_modules",
        is_package=True,
        relative_path="rag_modules/__init__.py",
    )
    visitor.visit(tree)
    imports = [*visitor.imports, *_lazy_table_imports(tree, "rag_modules")]

    assert RawImport("rag_modules.thing", 4, "runtime") in imports
    assert visitor.dynamic_import_errors == ["rag_modules/__init__.py:9: non-literal import_module"]


def test_controlled_lazy_file_rejects_lazy_get_with_a_dynamic_default() -> None:
    source = """
from importlib import import_module as load

_LAZY_EXPORTS = {"PublicThing": ".thing"}

def resolve(name, requested):
    module_name = _LAZY_EXPORTS.get(name, requested)
    load(module_name, __name__)
"""
    tree = ast.parse(source, filename="rag_modules/__init__.py")
    visitor = _ImportVisitor(
        source_module="rag_modules",
        is_package=True,
        relative_path="rag_modules/__init__.py",
    )
    visitor.visit(tree)

    assert visitor.dynamic_import_errors == ["rag_modules/__init__.py:8: non-literal import_module"]


def test_controlled_lazy_tables_reject_mutation_and_leave_no_static_targets() -> None:
    mutations = {
        "reassignment": "_EXPORTS = requested",
        "subscript assignment": '_EXPORTS["Injected"] = requested',
        "subscript augmented assignment": '_EXPORTS["Injected"] |= requested',
        "mapping augmented assignment": "_EXPORTS |= requested",
        "subscript deletion": 'del _EXPORTS["Safe"]',
        "update": '_EXPORTS.update({"Injected": requested})',
        "setdefault": '_EXPORTS.setdefault("Injected", requested)',
        "clear": "_EXPORTS.clear()",
        "pop": '_EXPORTS.pop("Safe")',
        "popitem": "_EXPORTS.popitem()",
    }

    for label, mutation in mutations.items():
        source = "\n".join(
            (
                "from importlib import import_module",
                '_EXPORTS = {"Safe": ".safe"}',
                mutation,
                "module_name = _EXPORTS.get(name)",
                "import_module(module_name, __name__)",
            )
        )
        tree = ast.parse(source, filename="rag_modules/__init__.py")
        visitor = _ImportVisitor(
            source_module="rag_modules",
            is_package=True,
            relative_path="rag_modules/__init__.py",
        )
        visitor.visit(tree)

        assert (
            "rag_modules/__init__.py:3: mutated lazy import table _EXPORTS"
            in visitor.dynamic_import_errors
        ), label
        assert _lazy_table_imports(tree, "rag_modules") == [], label


def test_controlled_lazy_tables_reject_mutation_through_an_alias() -> None:
    source = "\n".join(
        (
            "from importlib import import_module",
            '_EXPORTS = {"Safe": ".safe"}',
            "_ALIAS = _EXPORTS",
            '_ALIAS.update({"Injected": requested})',
            "module_name = _EXPORTS.get(name)",
            "import_module(module_name, __name__)",
        )
    )
    tree = ast.parse(source, filename="rag_modules/__init__.py")
    visitor = _ImportVisitor(
        source_module="rag_modules",
        is_package=True,
        relative_path="rag_modules/__init__.py",
    )
    visitor.visit(tree)

    assert (
        "rag_modules/__init__.py:4: mutated lazy import table _EXPORTS"
        in visitor.dynamic_import_errors
    )
    assert _lazy_table_imports(tree, "rag_modules") == []


def test_type_checking_guard_requires_a_typing_binding() -> None:
    imports = _collect_imports_from_source(
        """
import config
import typing as t
from typing import TYPE_CHECKING as CHECKING

if config.TYPE_CHECKING:
    from ..generation import service
if t.TYPE_CHECKING:
    from ..kernel import json_types
if CHECKING:
    from ..contracts import RetrievalRequest
""",
        source_module="rag_modules.runtime.sample",
        is_package=False,
        relative_path="rag_modules/runtime/sample.py",
    )

    assert {
        (item.target_module, item.kind)
        for item in imports
        if item.target_module.startswith("rag_modules.")
    } == {
        ("rag_modules.contracts", "type"),
        ("rag_modules.generation", "runtime"),
        ("rag_modules.generation.service", "runtime"),
        ("rag_modules.kernel", "type"),
        ("rag_modules.kernel.json_types", "type"),
    }


def test_concrete_cycle_format_includes_closed_path_and_edge_evidence() -> None:
    edges = (
        ImportEdge(
            source_module="rag_modules.runtime.sample",
            target_module="rag_modules.generation.service",
            source_node="runtime",
            target_node="generation",
            path=ROOT / "rag_modules/runtime/sample.py",
            line=11,
            kind="type",
        ),
        ImportEdge(
            source_module="rag_modules.generation.service",
            target_module="rag_modules.app.system",
            source_node="generation",
            target_node="app",
            path=ROOT / "rag_modules/generation/service.py",
            line=22,
            kind="runtime",
        ),
        ImportEdge(
            source_module="rag_modules.app.system",
            target_module="rag_modules.runtime.sample",
            source_node="app",
            target_node="runtime",
            path=ROOT / "rag_modules/app/system.py",
            line=33,
            kind="runtime",
        ),
    )

    rendered = _format_component(("app", "generation", "runtime"), edges)

    assert rendered == "\n".join(
        (
            "app -> runtime -> generation -> app",
            f"  app -[runtime {Path('rag_modules/app/system.py')}:33]-> runtime",
            f"  runtime -[type {Path('rag_modules/runtime/sample.py')}:11]-> generation",
            f"  generation -[runtime {Path('rag_modules/generation/service.py')}:22]-> app",
        )
    )


def test_edge_sort_keys_have_a_stable_total_module_level_order() -> None:
    shared = {
        "source_node": "runtime",
        "target_node": "generation",
        "path": ROOT / "rag_modules/runtime/sample.py",
        "line": 11,
        "kind": "runtime",
    }
    edges = (
        ImportEdge(
            source_module="rag_modules.runtime.zeta",
            target_module="rag_modules.generation.alpha",
            **shared,
        ),
        ImportEdge(
            source_module="rag_modules.runtime.alpha",
            target_module="rag_modules.generation.zeta",
            **shared,
        ),
        ImportEdge(
            source_module="rag_modules.runtime.alpha",
            target_module="rag_modules.generation.alpha",
            **shared,
        ),
    )
    expected = [
        ("rag_modules.runtime.alpha", "rag_modules.generation.alpha"),
        ("rag_modules.runtime.alpha", "rag_modules.generation.zeta"),
        ("rag_modules.runtime.zeta", "rag_modules.generation.alpha"),
    ]

    assert [
        (edge.source_module, edge.target_module)
        for edge in sorted(edges, key=_inventory_edge_sort_key)
    ] == expected
    assert [
        (edge.source_module, edge.target_module)
        for edge in sorted(edges, key=_concrete_cycle_edge_sort_key)
    ] == expected


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
