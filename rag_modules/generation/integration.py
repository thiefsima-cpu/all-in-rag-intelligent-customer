"""Generation facade over the canonical workflow service."""

from __future__ import annotations

from typing import Any, List

from ..answer_evidence_builder import AnswerEvidencePackage
from ..configuration.models import GraphRAGConfig
from ..retrieval.contracts import EvidenceDocument, PageDocumentLike
from .models import AnswerPlan, GenerationDecision, GenerationTrace, RenderedPrompt
from .service import GenerationWorkflowService


class GenerationIntegrationModule:
    """Question/evidence facade over a context-native service."""

    def __init__(
        self,
        *args,
        workflow_service: GenerationWorkflowService | None = None,
        **kwargs,
    ) -> None:
        self.workflow_service = workflow_service or GenerationWorkflowService(*args, **kwargs)

    @classmethod
    def from_config(cls, config: GraphRAGConfig) -> "GenerationIntegrationModule":
        return cls(workflow_service=GenerationWorkflowService.from_config(config))

    def generate_answer_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
        analysis: Any = None,
    ) -> str:
        return self.workflow_service.generate_answer_from_context(
            self._context_from_evidence(
                question=question,
                evidence_documents=evidence_documents,
                analysis=analysis,
            )
        )

    def generate_answer_with_trace_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
        analysis: Any = None,
    ):
        return self.workflow_service.generate_answer_with_trace_from_context(
            self._context_from_evidence(
                question=question,
                evidence_documents=evidence_documents,
                analysis=analysis,
            )
        )

    def generate_answer_stream_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
        max_retries: int | None = None,
        analysis: Any = None,
    ):
        return self.workflow_service.generate_answer_stream_from_context(
            self._context_from_evidence(
                question=question,
                evidence_documents=evidence_documents,
                analysis=analysis,
            ),
            max_retries=max_retries,
        )

    def generate_answer_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
        analysis: Any = None,
    ) -> str:
        return self.workflow_service.generate_answer_from_context(
            self._context_from_documents(
                question=question,
                documents=documents,
                analysis=analysis,
            )
        )

    def generate_answer_with_trace_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
        analysis: Any = None,
    ):
        return self.workflow_service.generate_answer_with_trace_from_context(
            self._context_from_documents(
                question=question,
                documents=documents,
                analysis=analysis,
            )
        )

    def generate_answer_stream_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
        max_retries: int | None = None,
        analysis: Any = None,
    ):
        return self.workflow_service.generate_answer_stream_from_context(
            self._context_from_documents(
                question=question,
                documents=documents,
                analysis=analysis,
            ),
            max_retries=max_retries,
        )

    def generate_adaptive_answer(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
        analysis: Any = None,
    ) -> str:
        return self.generate_answer_from_documents(question, documents, analysis=analysis)

    def generate_adaptive_answer_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
        analysis: Any = None,
    ) -> str:
        return self.generate_answer_from_evidence(
            question,
            evidence_documents,
            analysis=analysis,
        )

    def generate_adaptive_answer_stream(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument],
        max_retries: int | None = None,
        analysis: Any = None,
    ):
        return self.generate_answer_stream_from_documents(
            question,
            documents,
            max_retries=max_retries,
            analysis=analysis,
        )

    def generate_adaptive_answer_stream_from_evidence(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument],
        max_retries: int | None = None,
        analysis: Any = None,
    ):
        return self.generate_answer_stream_from_evidence(
            question,
            evidence_documents,
            max_retries=max_retries,
            analysis=analysis,
        )

    def build_answer_plan(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        package: AnswerEvidencePackage | None = None,
    ) -> AnswerPlan:
        return self.workflow_service.build_answer_plan_from_context(
            self._with_package(
                self._context_from_evidence(
                    question=question,
                    evidence_documents=evidence_documents,
                    analysis=analysis,
                ),
                package,
            )
        )

    def build_answer_plan_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        package: AnswerEvidencePackage | None = None,
    ) -> AnswerPlan:
        return self.workflow_service.build_answer_plan_from_context(
            self._with_package(
                self._context_from_documents(
                    question=question,
                    documents=documents,
                    analysis=analysis,
                ),
                package,
            )
        )

    def compose_answer(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        plan: AnswerPlan | dict | None = None,
        package: AnswerEvidencePackage | None = None,
    ) -> str:
        return self.workflow_service.compose_answer_from_context(
            self._with_package(
                self._context_from_evidence(
                    question=question,
                    evidence_documents=evidence_documents,
                    analysis=analysis,
                ),
                package,
            ),
            plan=plan,
        )

    def compose_answer_from_documents(
        self,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        plan: AnswerPlan | dict | None = None,
        package: AnswerEvidencePackage | None = None,
    ) -> str:
        return self.workflow_service.compose_answer_from_context(
            self._with_package(
                self._context_from_documents(
                    question=question,
                    documents=documents,
                    analysis=analysis,
                ),
                package,
            ),
            plan=plan,
        )

    def render_plan_prompt(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        package: AnswerEvidencePackage | None = None,
    ) -> RenderedPrompt:
        return self.workflow_service.render_plan_prompt_from_context(
            self._with_package(
                self._context_from_evidence(
                    question=question,
                    evidence_documents=evidence_documents,
                    analysis=analysis,
                ),
                package,
            )
        )

    def render_compose_prompt(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        plan: AnswerPlan | dict | None = None,
        package: AnswerEvidencePackage | None = None,
    ) -> RenderedPrompt:
        return self.workflow_service.render_compose_prompt_from_context(
            self._with_package(
                self._context_from_evidence(
                    question=question,
                    evidence_documents=evidence_documents,
                    analysis=analysis,
                ),
                package,
            ),
            plan=plan,
        )

    def render_direct_answer_prompt(
        self,
        question: str,
        evidence_documents: List[EvidenceDocument] | None = None,
        *,
        analysis: Any = None,
        package: AnswerEvidencePackage | None = None,
    ) -> RenderedPrompt:
        return self.workflow_service.render_direct_answer_prompt_from_context(
            self._with_package(
                self._context_from_evidence(
                    question=question,
                    evidence_documents=evidence_documents,
                    analysis=analysis,
                ),
                package,
            )
        )

    def _context_from_evidence(
        self,
        *,
        question: str,
        evidence_documents: List[EvidenceDocument] | None,
        analysis: Any = None,
    ):
        return self.workflow_service.context_factory.build_answer_context_from_evidence(
            question=question,
            evidence_documents=evidence_documents,
            analysis=analysis,
        )

    def _context_from_documents(
        self,
        *,
        question: str,
        documents: List[PageDocumentLike | EvidenceDocument] | None,
        analysis: Any = None,
    ):
        return self.workflow_service.context_factory.build_answer_context_from_documents(
            question=question,
            documents=documents,
            analysis=analysis,
        )

    @staticmethod
    def _with_package(answer_context, package: AnswerEvidencePackage | None):
        if package is None:
            return answer_context
        return answer_context.with_evidence_package(package)


__all__ = [
    "AnswerPlan",
    "GenerationDecision",
    "GenerationIntegrationModule",
    "GenerationTrace",
    "RenderedPrompt",
]
