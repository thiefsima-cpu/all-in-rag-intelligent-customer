from __future__ import annotations

import unittest

from rag_modules.generation.models import AnswerPlan, RenderedPrompt
from rag_modules.generation.service import GenerationWorkflowService
from rag_modules.runtime import GenerationSnapshot


class _Context:
    def __init__(self, *, question: str) -> None:
        self.question = question
        self.package_attached = False


class _StubContextFactory:
    def __init__(self) -> None:
        self.ensure_context_calls: list[object] = []
        self.ensure_package_calls: list[object] = []
        self.ensure_plan_calls: list[object] = []

    def ensure_answer_context(self, answer_context):
        self.ensure_context_calls.append(answer_context)
        if isinstance(answer_context, dict):
            return _Context(question=answer_context["question"])
        return answer_context

    def ensure_evidence_package(self, answer_context):
        self.ensure_package_calls.append(answer_context)
        answer_context.package_attached = True
        return answer_context

    def ensure_plan(self, plan):
        self.ensure_plan_calls.append(plan)
        if isinstance(plan, dict):
            return AnswerPlan.from_dict(plan)
        return plan


class _StubExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def generate(self, *, answer_context):
        self.calls.append(("generate", answer_context))
        return f"answer::{answer_context.question}"

    def generate_with_trace(self, *, answer_context):
        self.calls.append(("generate_with_trace", answer_context))
        return (
            f"trace-answer::{answer_context.question}",
            GenerationSnapshot(mode="direct", total_evidence_items=1),
        )

    def stream(self, *, answer_context, max_retries=None):
        self.calls.append(("stream", answer_context))
        self.max_retries = max_retries
        return iter([f"stream::{answer_context.question}"])

    def stream_with_trace(self, *, answer_context, max_retries=None, chunk_callback=None):
        self.calls.append(("stream_with_trace", answer_context))
        self.max_retries = max_retries
        if chunk_callback:
            chunk_callback("chunk")
        return (
            f"stream-trace::{answer_context.question}",
            GenerationSnapshot(mode="stream", total_evidence_items=2),
        )

    def compose_from_context(self, context, plan):
        self.calls.append(("compose", context))
        self.plan = plan
        return f"compose::{context.question}::{plan.answer_type}"


class _StubPlanner:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def build_answer_plan_from_context(self, context):
        self.calls.append(context)
        return AnswerPlan(answer_type="summary", key_points=["k"], outline=["o"])


class _StubPromptBuilder:
    @staticmethod
    def render_plan_prompt_from_context(context):
        return RenderedPrompt(
            prompt_type="plan",
            question=context.question,
            text=f"plan::{context.question}",
        )

    @staticmethod
    def render_compose_prompt_from_context(context, plan):
        return RenderedPrompt(
            prompt_type="compose",
            question=context.question,
            text=f"compose::{context.question}",
            plan=plan.to_dict(),
        )

    @staticmethod
    def render_direct_answer_prompt_from_context(context):
        return RenderedPrompt(
            prompt_type="direct",
            question=context.question,
            text=f"direct::{context.question}",
        )


def _service() -> GenerationWorkflowService:
    service = object.__new__(GenerationWorkflowService)
    service.context_factory = _StubContextFactory()
    service.executor = _StubExecutor()
    service.planner = _StubPlanner()
    service.prompt_builder = _StubPromptBuilder()
    return service


class GenerationWorkflowServiceContextTests(unittest.TestCase):
    def test_generate_answer_from_context_normalizes_dict_context(self) -> None:
        service = _service()

        answer = service.generate_answer_from_context({"question": "q"})

        self.assertEqual(answer, "answer::q")
        self.assertEqual(service.executor.calls[0][0], "generate")
        context = service.executor.calls[0][1]
        self.assertEqual(context.question, "q")
        self.assertTrue(context.package_attached)

    def test_trace_and_stream_methods_return_generation_snapshots(self) -> None:
        service = _service()
        chunks: list[str] = []

        answer, trace = service.generate_answer_with_trace_from_context(_Context(question="trace"))
        stream_answer, stream_trace = service.generate_answer_stream_with_trace_from_context(
            _Context(question="stream"),
            max_retries=2,
            chunk_callback=chunks.append,
        )

        self.assertEqual(answer, "trace-answer::trace")
        self.assertIsInstance(trace, GenerationSnapshot)
        self.assertEqual(trace.mode, "direct")
        self.assertEqual(stream_answer, "stream-trace::stream")
        self.assertIsInstance(stream_trace, GenerationSnapshot)
        self.assertEqual(stream_trace.mode, "stream")
        self.assertEqual(chunks, ["chunk"])
        self.assertEqual(service.executor.max_retries, 2)

    def test_compose_uses_explicit_or_planned_answer_plan(self) -> None:
        service = _service()

        explicit = service.compose_answer_from_context(
            _Context(question="explicit"),
            plan={"answer_type": "explanation", "key_points": ["a"], "outline": ["b"]},
        )
        planned = service.compose_answer_from_context(_Context(question="planned"))

        self.assertEqual(explicit, "compose::explicit::explanation")
        self.assertEqual(planned, "compose::planned::summary")
        self.assertEqual(len(service.planner.calls), 1)
        self.assertEqual(service.planner.calls[0].question, "planned")

    def test_prompt_rendering_uses_context_native_service_api(self) -> None:
        service = _service()
        plan = AnswerPlan(answer_type="summary", key_points=["a"], outline=["b"])

        self.assertEqual(
            service.render_plan_prompt_from_context(_Context(question="p")).text,
            "plan::p",
        )
        self.assertEqual(
            service.render_compose_prompt_from_context(_Context(question="c"), plan=plan).text,
            "compose::c",
        )
        self.assertEqual(
            service.render_direct_answer_prompt_from_context(_Context(question="d")).text,
            "direct::d",
        )


if __name__ == "__main__":
    unittest.main()
