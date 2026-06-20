from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rag_modules.generation.integration import GenerationIntegrationModule
from rag_modules.generation.models import AnswerPlan, RenderedPrompt


class _Context:
    def __init__(self, *, question: str, kind: str, payload, analysis=None) -> None:
        self.question = question
        self.kind = kind
        self.payload = payload
        self.analysis = analysis
        self.package = None

    def with_evidence_package(self, package):
        self.package = package
        return self


class _StubContextFactory:
    def build_answer_context_from_evidence(self, *, question, evidence_documents, analysis=None):
        return _Context(
            question=question,
            kind="evidence",
            payload=list(evidence_documents or []),
            analysis=analysis,
        )

    def build_answer_context_from_documents(self, *, question, documents, analysis=None):
        return _Context(
            question=question,
            kind="documents",
            payload=list(documents or []),
            analysis=analysis,
        )


class _StubWorkflowService:
    def __init__(self) -> None:
        self.context_factory = _StubContextFactory()
        self.client = SimpleNamespace(name="client")
        self.generate_calls: list[dict] = []
        self.compose_calls: list[dict] = []
        self.plan_calls: list[object] = []

    def generate_answer_from_context(self, answer_context):
        self.generate_calls.append({"context": answer_context})
        return f"answer::{answer_context.kind}::{answer_context.question}"

    def generate_answer_stream_from_context(self, answer_context, max_retries=None):
        self.generate_calls.append(
            {"context": answer_context, "max_retries": max_retries, "stream": True}
        )
        return iter([f"stream::{answer_context.kind}"])

    def build_answer_plan_from_context(self, answer_context):
        self.plan_calls.append(answer_context)
        return AnswerPlan(
            answer_type="explanation",
            key_points=["k1"],
            outline=["o1"],
        )

    def compose_answer_from_context(self, answer_context, *, plan=None):
        self.compose_calls.append({"context": answer_context, "plan": plan})
        return f"compose::{answer_context.kind}::{answer_context.question}"

    def render_plan_prompt_from_context(self, answer_context):
        return RenderedPrompt(
            text=f"plan::{answer_context.question}",
            system_prompt="sys",
            user_prompt="user",
        )

    def render_compose_prompt_from_context(self, answer_context, *, plan=None):
        return RenderedPrompt(
            text=f"compose::{answer_context.question}",
            system_prompt="sys",
            user_prompt="user",
            plan=plan.to_dict() if hasattr(plan, "to_dict") else dict(plan or {}),
        )

    def render_direct_answer_prompt_from_context(self, answer_context):
        return RenderedPrompt(
            text=f"direct::{answer_context.question}",
            system_prompt="sys",
            user_prompt="user",
        )


class GenerationIntegrationFacadeTests(unittest.TestCase):
    def test_generate_answer_from_evidence_translates_into_context(self) -> None:
        workflow = _StubWorkflowService()
        module = GenerationIntegrationModule(workflow_service=workflow)

        result = module.generate_answer_from_evidence(
            "为什么鱼香肉丝有层次？",
            evidence_documents=[SimpleNamespace(id="e1")],
            analysis={"strategy": "graph_rag"},
        )

        self.assertEqual(result, "answer::evidence::为什么鱼香肉丝有层次？")
        self.assertEqual(len(workflow.generate_calls), 1)
        context = workflow.generate_calls[0]["context"]
        self.assertEqual(context.kind, "evidence")
        self.assertEqual(context.analysis, {"strategy": "graph_rag"})
        self.assertEqual(len(context.payload), 1)

    def test_compose_answer_attaches_package_before_delegate(self) -> None:
        workflow = _StubWorkflowService()
        module = GenerationIntegrationModule(workflow_service=workflow)
        package = SimpleNamespace(name="pkg")
        plan = AnswerPlan(answer_type="summary", key_points=["a"], outline=["b"])

        result = module.compose_answer(
            "怎么解释宫保鸡丁的味型关系？",
            evidence_documents=[SimpleNamespace(id="e1")],
            plan=plan,
            package=package,
        )

        self.assertEqual(result, "compose::evidence::怎么解释宫保鸡丁的味型关系？")
        self.assertEqual(len(workflow.compose_calls), 1)
        context = workflow.compose_calls[0]["context"]
        self.assertIs(context.package, package)
        self.assertIs(workflow.compose_calls[0]["plan"], plan)

    def test_context_native_members_must_use_workflow_service_explicitly(self) -> None:
        workflow = _StubWorkflowService()
        module = GenerationIntegrationModule(workflow_service=workflow)
        direct_context = _Context(question="q", kind="context", payload=[])

        self.assertEqual(
            workflow.generate_answer_from_context(direct_context),
            "answer::context::q",
        )
        with self.assertRaises(AttributeError):
            module.generate_answer_from_context(direct_context)
        with self.assertRaises(AttributeError):
            _ = module.client

    def test_from_config_wraps_canonical_workflow_service(self) -> None:
        workflow = _StubWorkflowService()

        with patch(
            "rag_modules.generation.integration.GenerationWorkflowService.from_config",
            return_value=workflow,
        ) as factory:
            module = GenerationIntegrationModule.from_config(SimpleNamespace())

        self.assertIs(module.workflow_service, workflow)
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
