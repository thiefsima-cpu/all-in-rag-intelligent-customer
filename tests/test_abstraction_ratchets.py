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


def test_scoped_leaf_modules_are_not_pure_forwarders() -> None:
    violations = []
    for package_root in SCOPED_ROOTS:
        for path in package_root.rglob("*.py"):
            if path.name == "__init__.py" or path in APPROVED_FORWARDING_MODULES:
                continue
            if _is_forwarding_module(path):
                violations.append(str(path.relative_to(ROOT)))

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
