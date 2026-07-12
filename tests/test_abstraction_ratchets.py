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
