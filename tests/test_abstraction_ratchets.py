from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = ROOT / "rag_modules"
MAX_PRODUCTION_PROTOCOLS = 152
MAX_PRODUCTION_MODULES_UNDER_60_LINES = 64
MAX_PRODUCTION_ANY_NAME_NODES = 174
MAX_PRODUCTION_PYTHON_FILES = 383
SCOPED_ROOTS = (
    ROOT / "rag_modules" / "app",
    ROOT / "rag_modules" / "application",
    ROOT / "rag_modules" / "runtime",
)
APPROVED_FORWARDING_MODULES = {
    ROOT / "rag_modules" / "app" / "diagnostics.py",
}
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
    Path("rag_modules/application/answering/answer_models.py"): frozenset({"QuestionAnswerer"}),
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
FOUNDATION_ROOTS = (
    ROOT / "rag_modules" / "configuration",
    ROOT / "rag_modules" / "contracts",
    ROOT / "rag_modules" / "kernel",
)
FORWARDER_ROOTS = SCOPED_ROOTS + FOUNDATION_ROOTS
APPROVED_FOUNDATION_PROTOCOLS = {
    Path("rag_modules/contracts/build_jobs/ports.py"): frozenset(
        {"BuildJobRepositoryPort", "BuildJobRunnerPort"}
    )
}
APPROVED_FOUNDATION_SHORT_MODULES = {
    Path("rag_modules/contracts/build_jobs/errors.py"): "build-job domain errors",
    Path("rag_modules/contracts/graph.py"): "graph query DTOs",
    Path("rag_modules/contracts/runtime/policy.py"): "runtime policy DTOs",
    Path("rag_modules/kernel/documents.py"): "document normalization primitives",
    Path("rag_modules/kernel/retrieval.py"): "retrieval strategy primitives",
    Path("rag_modules/kernel/semantic_schema.py"): "semantic schema identifiers",
    Path("rag_modules/kernel/time_parsing.py"): "timestamp parsing primitives",
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


def _all_protocol_definitions(path: Path) -> list[ast.ClassDef]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(_base_name(base) == "Protocol" for base in node.bases)
    ]


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
        if not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
    ]
    imports = [node for node in body if isinstance(node, (ast.Import, ast.ImportFrom))]
    return bool(imports) and all(
        isinstance(node, (ast.Import, ast.ImportFrom)) or _is_all_assignment(node) for node in body
    )


def _is_policy_free_forwarder(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = list(node.body)
    if body and _is_docstring(body[0]):
        body.pop(0)
    if len(body) != 1 or not isinstance(body[0], ast.Return):
        return False
    if node.name.startswith("__") or any(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in node.decorator_list
    ):
        return False
    expression = body[0].value
    call = expression.value if isinstance(expression, ast.Await) else expression
    if not isinstance(call, ast.Call) or not isinstance(call.func, (ast.Name, ast.Attribute)):
        return False
    if isinstance(call.func, ast.Name) and call.func.id in {"bool", "float", "int", "str"}:
        return False
    parameter_names = {
        argument.arg
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    }
    if node.args.vararg is not None:
        parameter_names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        parameter_names.add(node.args.kwarg.arg)
    forwarded_names = {argument.id for argument in call.args if isinstance(argument, ast.Name)}
    forwarded_names.update(
        argument.value.id
        for argument in call.args
        if isinstance(argument, ast.Starred) and isinstance(argument.value, ast.Name)
    )
    forwarded_names.update(
        keyword.value.id for keyword in call.keywords if isinstance(keyword.value, ast.Name)
    )
    receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
    while isinstance(receiver, ast.Attribute):
        receiver = receiver.value
    if isinstance(receiver, ast.Name):
        forwarded_names.add(receiver.id)
    return bool(parameter_names) and parameter_names == forwarded_names


def _forwarder_candidate(source: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(source)
    return next(
        node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def test_policy_free_forwarder_predicate_detects_semantic_delegates() -> None:
    assert _is_policy_free_forwarder(_forwarder_candidate("def f(query): return target(query)"))
    assert _is_policy_free_forwarder(
        _forwarder_candidate("def f(client, query): return client.execute(query)")
    )
    assert _is_policy_free_forwarder(
        _forwarder_candidate("async def f(client, query): return await client.execute(query)")
    )
    assert _is_policy_free_forwarder(
        _forwarder_candidate("def f(*args, **kwargs): return target(*args, **kwargs)")
    )


def test_policy_free_forwarder_predicate_rejects_non_forwarders() -> None:
    assert not _is_policy_free_forwarder(
        _forwarder_candidate("def f(query): return target(query.strip())")
    )
    assert not _is_policy_free_forwarder(_forwarder_candidate("def f(query): return str(query)"))
    assert not _is_policy_free_forwarder(_forwarder_candidate("def f(): return target()"))
    assert not _is_policy_free_forwarder(
        _forwarder_candidate("def f(query):\n    result = target(query)\n    return result")
    )


def test_scoped_leaf_modules_are_not_pure_forwarders() -> None:
    violations = []
    for package_root in FORWARDER_ROOTS:
        for path in package_root.rglob("*.py"):
            if path.name == "__init__.py" or path in APPROVED_FORWARDING_MODULES:
                continue
            if _is_forwarding_module(path):
                violations.append(str(path.relative_to(ROOT)))

    assert violations == []


def test_wave_scope_does_not_have_policy_free_single_call_functions() -> None:
    violations = []
    for package_root in FOUNDATION_ROOTS:
        for path in package_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ) and _is_policy_free_forwarder(node):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.name}")

    assert violations == []


def test_protocols_outside_port_and_contract_modules_match_approved_baseline() -> None:
    actual: dict[Path, frozenset[str]] = {}
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            if path.name in {"ports.py", "contracts.py"} or path.name.endswith("_ports.py"):
                continue
            names = _protocol_definitions(path)
            if names:
                actual[path.relative_to(ROOT)] = frozenset(names)

    assert actual == APPROVED_PROTOCOL_EXCEPTIONS


def test_foundation_protocols_match_the_two_retained_build_job_ports() -> None:
    actual: dict[Path, frozenset[str]] = {}
    for package_root in FOUNDATION_ROOTS:
        for path in package_root.rglob("*.py"):
            names = _protocol_definitions(path)
            if names:
                actual[path.relative_to(ROOT)] = frozenset(names)

    assert actual == APPROVED_FOUNDATION_PROTOCOLS


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


def test_production_protocol_count_does_not_exceed_ratchet() -> None:
    definitions = [
        (path.relative_to(ROOT), node.name)
        for path in PRODUCTION_ROOT.rglob("*.py")
        for node in _all_protocol_definitions(path)
    ]

    assert len(definitions) <= MAX_PRODUCTION_PROTOCOLS, (
        "Production Protocol count exceeded the approved ratchet. Prefer a concrete type or "
        "Callable for single-implementation seams, or lower the baseline after deleting one. "
        f"count={len(definitions)} baseline={MAX_PRODUCTION_PROTOCOLS}"
    )


def test_small_production_module_count_does_not_exceed_ratchet() -> None:
    small_modules = [
        path.relative_to(ROOT)
        for path in PRODUCTION_ROOT.rglob("*.py")
        if path.name != "__init__.py"
        and len(path.read_text(encoding="utf-8-sig").splitlines()) < 60
    ]

    assert len(small_modules) <= MAX_PRODUCTION_MODULES_UNDER_60_LINES, (
        "Sub-60-line production module count exceeded the approved ratchet. Add a module only "
        "when it owns a stable responsibility; otherwise keep behavior with its owner. "
        f"count={len(small_modules)} baseline={MAX_PRODUCTION_MODULES_UNDER_60_LINES}"
    )


def test_foundation_short_modules_match_responsibility_registry() -> None:
    actual = {
        path.relative_to(ROOT)
        for package_root in FOUNDATION_ROOTS
        for path in package_root.rglob("*.py")
        if path.name != "__init__.py"
        and len(path.read_text(encoding="utf-8-sig").splitlines()) < 60
    }

    assert actual == set(APPROVED_FOUNDATION_SHORT_MODULES)


def test_foundation_modules_do_not_use_dynamic_type_escape_hatches() -> None:
    violations: list[str] = []
    prohibited_call_names = {"cast", "getattr"}
    for package_root in FOUNDATION_ROOTS:
        for path in package_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in prohibited_call_names
                ):
                    violations.append(
                        f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.id}(...)"
                    )
            violations.extend(
                f"{path.relative_to(ROOT)}:{line_number}: type ignore"
                for line_number, line in enumerate(source.splitlines(), start=1)
                if "type: ignore" in line
            )

    assert violations == []


def test_production_explicit_any_count_does_not_exceed_ratchet() -> None:
    any_name_nodes = [
        (path.relative_to(ROOT), node.lineno)
        for path in PRODUCTION_ROOT.rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path)))
        if isinstance(node, ast.Name) and node.id == "Any"
    ]

    assert len(any_name_nodes) <= MAX_PRODUCTION_ANY_NAME_NODES, (
        "Production explicit Any count exceeded the approved ratchet. Prefer object at ingress, "
        "JsonObject for JSON output, or a concrete DTO for known shapes. "
        f"count={len(any_name_nodes)} baseline={MAX_PRODUCTION_ANY_NAME_NODES}"
    )


def test_production_python_file_count_does_not_exceed_ratchet() -> None:
    python_files = list(PRODUCTION_ROOT.rglob("*.py"))

    assert len(python_files) <= MAX_PRODUCTION_PYTHON_FILES, (
        "Production Python file count exceeded the approved ratchet. Merge a new module into "
        "its canonical owner unless it has a stable independent responsibility. "
        f"count={len(python_files)} baseline={MAX_PRODUCTION_PYTHON_FILES}"
    )
