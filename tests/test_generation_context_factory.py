from __future__ import annotations

import pytest

from rag_modules.contracts import EvidenceDocument
from rag_modules.contracts.runtime import AnswerContext, RetrievalOutcome
from rag_modules.evidence_processing.answer_builder import AnswerEvidenceItem, AnswerEvidencePackage
from rag_modules.generation.context_factory import GenerationContextFactory
from rag_modules.generation.models import AnswerPlan
from rag_modules.kernel.documents import TextDocument


class _Builder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[object]]] = []

    def build(self, question: str, documents: list[EvidenceDocument]) -> AnswerEvidencePackage:
        self.calls.append(("evidence", question, list(documents)))
        return AnswerEvidencePackage(
            question=question,
            items=[AnswerEvidenceItem(citation="Evidence 1", content="evidence")],
        )

    def build_from_documents(self, question: str, documents: list[object]) -> AnswerEvidencePackage:
        self.calls.append(("documents", question, list(documents)))
        return AnswerEvidencePackage(
            question=question,
            items=[AnswerEvidenceItem(citation="Evidence 1", content="document")],
        )


def _factory() -> tuple[GenerationContextFactory, _Builder]:
    builder = _Builder()
    return GenerationContextFactory(builder), builder


def test_context_and_plan_normalization_accept_valid_forms_and_rejects_others() -> None:
    factory, _ = _factory()
    context = AnswerContext(question="tofu")
    plan = AnswerPlan(answer_type="direct_answer")

    assert factory.ensure_answer_context(context) is context
    assert factory.ensure_answer_context({"question": "mapped"}).question == "mapped"
    assert factory.ensure_plan(None) is None
    assert factory.ensure_plan(plan) is plan
    assert factory.ensure_plan({"answer_type": "comparison"}).answer_type == "comparison"
    with pytest.raises(TypeError):
        factory.ensure_answer_context("invalid")
    with pytest.raises(TypeError):
        factory.ensure_plan("invalid")


def test_package_resolution_reuses_explicit_packages_and_builds_missing_ones() -> None:
    factory, builder = _factory()
    explicit = AnswerEvidencePackage(question="explicit", items=[])
    evidence = EvidenceDocument(content="evidence", recipe_id="r1")
    document = TextDocument(content="document")

    assert (
        factory.resolve_package_from_evidence(
            question="q", evidence_documents=[evidence], package=explicit
        )
        is explicit
    )
    assert (
        factory.resolve_package_from_documents(question="q", documents=[document], package=explicit)
        is explicit
    )
    assert (
        factory.resolve_package_from_evidence(question="q", evidence_documents=[evidence]).question
        == "q"
    )
    assert (
        factory.resolve_package_from_documents(question="d", documents=[document]).question == "d"
    )
    assert [call[0] for call in builder.calls] == ["evidence", "documents"]


def test_context_package_and_document_build_paths_preserve_evidence() -> None:
    factory, builder = _factory()
    evidence = EvidenceDocument(content="evidence", recipe_id="r1")
    context = AnswerContext(
        question="tofu",
        retrieval=RetrievalOutcome(query="tofu", evidence_documents=[evidence]),
    )

    package = factory.package_from_context(context)
    enriched = factory.ensure_evidence_package(context)
    assert package.question == "tofu"
    assert enriched.has_evidence_package is True
    assert enriched.evidence_package["items"][0]["citation"] == "Evidence 1"
    assert len(builder.calls) == 2

    packaged = AnswerContext(
        question="tofu",
        evidence_package={"question": "tofu", "items": [{"content": "x", "citation": "c"}]},
    )
    assert factory.package_from_context(packaged).question == "tofu"
    assert factory.ensure_evidence_package(packaged) is packaged

    built = factory.build_answer_context_from_documents(
        question="documents", documents=[TextDocument(content="text", metadata={"node_id": "r1"})]
    )
    assert built.question == "documents"
    assert built.evidence_documents[0].content == "text"
    direct = factory.build_answer_context_from_evidence(
        question="direct", evidence_documents=[evidence], analysis={"query_complexity": 0.7}
    )
    assert direct.analysis is not None
    assert direct.evidence_documents == [evidence]
