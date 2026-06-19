"""Context and evidence-package resolution for generation."""

from __future__ import annotations

from typing import List

from ..answer_evidence_builder import AnswerEvidenceBuilder, AnswerEvidencePackage
from ..retrieval.contracts import EvidenceDocument, ensure_evidence_documents
from ..runtime import (
    AnalysisInput,
    AnswerContext,
    RetrievalOutcome,
    ensure_optional_query_analysis,
)
from .models import AnswerPlan


class GenerationContextFactory:
    """Normalize answer context, plans, and evidence packages."""

    def __init__(self, evidence_builder: AnswerEvidenceBuilder) -> None:
        self.evidence_builder = evidence_builder

    def ensure_answer_context(self, answer_context: AnswerContext | dict) -> AnswerContext:
        if isinstance(answer_context, AnswerContext):
            return answer_context
        if isinstance(answer_context, dict):
            return AnswerContext(**answer_context)
        raise TypeError("answer_context must be an AnswerContext or a compatible dict.")

    def ensure_plan(self, plan: AnswerPlan | dict | None) -> AnswerPlan | None:
        if plan is None:
            return None
        if isinstance(plan, AnswerPlan):
            return plan
        if isinstance(plan, dict):
            return AnswerPlan.from_dict(plan)
        raise TypeError("plan must be an AnswerPlan, dict, or None.")

    def package_from_context(self, answer_context: AnswerContext) -> AnswerEvidencePackage:
        if answer_context.has_evidence_package:
            return AnswerEvidencePackage.from_dict(answer_context.evidence_package)
        return self.resolve_package_from_evidence(
            question=answer_context.question,
            evidence_documents=answer_context.evidence_documents,
        )

    def ensure_evidence_package(self, answer_context: AnswerContext) -> AnswerContext:
        if answer_context.has_evidence_package:
            return answer_context
        package = self.package_from_context(answer_context)
        return answer_context.with_evidence_package(package)

    def resolve_package_from_evidence(
        self,
        *,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        package: AnswerEvidencePackage | None = None,
    ) -> AnswerEvidencePackage:
        if package is not None:
            return package
        return self.evidence_builder.build(question, list(evidence_documents or []))

    def resolve_package_from_documents(
        self,
        *,
        question: str,
        documents: List[object | EvidenceDocument] | None = None,
        package: AnswerEvidencePackage | None = None,
    ) -> AnswerEvidencePackage:
        if package is not None:
            return package
        return self.evidence_builder.build_from_documents(question, list(documents or []))

    def build_answer_context_from_documents(
        self,
        *,
        question: str,
        documents: List[object | EvidenceDocument] | None = None,
        analysis: AnalysisInput = None,
    ) -> AnswerContext:
        return self.build_answer_context_from_evidence(
            question=question,
            evidence_documents=ensure_evidence_documents(documents or []),
            analysis=analysis,
        )

    @staticmethod
    def build_answer_context_from_evidence(
        *,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        analysis: AnalysisInput = None,
    ) -> AnswerContext:
        return AnswerContext(
            question=question,
            retrieval=RetrievalOutcome(
                query=question,
                evidence_documents=list(evidence_documents or []),
            ),
            analysis=ensure_optional_query_analysis(analysis),
        )
