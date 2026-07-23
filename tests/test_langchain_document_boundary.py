from __future__ import annotations

import ast
from pathlib import Path

ALLOWED_IMPORTERS = {Path("rag_modules/langchain_document_adapter.py")}


def test_langchain_document_imports_stay_in_adapter_or_compat_layer() -> None:
    offenders: list[str] = []
    for path in Path("rag_modules").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "langchain_core.documents":
                if path not in ALLOWED_IMPORTERS:
                    offenders.append(path.as_posix())

    assert offenders == []


def test_page_document_protocols_are_retired() -> None:
    import rag_modules.contracts as contracts
    import rag_modules.evidence_processing as evidence_processing

    assert not hasattr(contracts, "PageDocumentLike")
    assert not hasattr(evidence_processing, "PageDocumentLike")
