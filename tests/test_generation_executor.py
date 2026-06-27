from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.answer_evidence_builder import AnswerEvidenceItem, AnswerEvidencePackage
from rag_modules.generation import (
    AnswerPlan,
    GenerationExecutionEngine,
    GenerationSettings,
    RenderedPrompt,
)
from rag_modules.runtime import AnswerContext, QueryAnalysis, SearchStrategy


class _FakePromptBuilder:
    def build_direct_answer_prompt(self, question: str, package: AnswerEvidencePackage) -> str:
        return f"direct::{question}::{len(package.items)}"

    def build_direct_answer_prompt_from_context(self, answer_context: AnswerContext) -> str:
        question = answer_context.question
        item_count = len(answer_context.evidence_package.get("items") or [])
        return f"direct::{question}::{item_count}"

    def render_direct_answer_prompt_from_context(
        self, answer_context: AnswerContext
    ) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_type="direct",
            question=answer_context.question,
            text=self.build_direct_answer_prompt_from_context(answer_context),
            evidence_item_count=len(answer_context.evidence_package.get("items") or []),
        )

    def build_compose_prompt(
        self,
        question: str,
        package: AnswerEvidencePackage,
        plan: AnswerPlan,
    ) -> str:
        return f"compose::{question}::{len(plan.key_points)}::{len(package.items)}"

    def build_compose_prompt_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
    ) -> str:
        question = answer_context.question
        item_count = len(answer_context.evidence_package.get("items") or [])
        return f"compose::{question}::{len(plan.key_points)}::{item_count}"

    def render_compose_prompt_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
    ) -> RenderedPrompt:
        return RenderedPrompt(
            prompt_type="compose",
            question=answer_context.question,
            text=self.build_compose_prompt_from_context(answer_context, plan),
            evidence_item_count=len(answer_context.evidence_package.get("items") or []),
            plan=plan.to_dict(),
        )


class _FakePlanner:
    def __init__(self, plan: AnswerPlan | None = None) -> None:
        self.plan = plan or AnswerPlan(
            answer_type="explanation",
            reasoning_mode="grounded",
            key_points=[{"title": "kp", "claim": "claim", "citations": ["菜谱证据 1"]}],
        )
        self.calls = 0

    def build_answer_plan(
        self,
        question: str,
        package: AnswerEvidencePackage,
        analysis=None,
    ) -> AnswerPlan:
        del question, package, analysis
        self.calls += 1
        return self.plan

    def build_answer_plan_from_context(self, answer_context: AnswerContext) -> AnswerPlan:
        del answer_context
        self.calls += 1
        return self.plan


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=text))]


class _EmptyChoicesResponse:
    choices: list[object] = []


class _FakeClientAdapter:
    def __init__(
        self,
        completions: list[object] | None = None,
        stream_responses: list[object] | None = None,
    ) -> None:
        self.completions = list(completions or [])
        self.stream_responses = list(stream_responses or [])
        self.prompts: list[str] = []
        self.stream_prompts: list[str] = []
        self.timeouts: list[float] = []

    def create_completion(self, *, prompt: str, timeout: float, **_: object):
        self.prompts.append(prompt)
        self.timeouts.append(float(timeout))
        if not self.completions:
            raise AssertionError("Unexpected completion request.")
        next_result = self.completions.pop(0)
        if isinstance(next_result, Exception):
            raise next_result
        return next_result

    def stream_prompt(self, *, prompt: str, **_: object):
        self.stream_prompts.append(prompt)
        if not self.stream_responses:
            raise AssertionError("Unexpected stream request.")
        next_result = self.stream_responses.pop(0)
        if isinstance(next_result, Exception):
            raise next_result
        return iter(next_result)


class GenerationExecutionEngineTests(unittest.TestCase):
    def test_generation_execution_package_exports_canonical_engine(self) -> None:
        from rag_modules.generation.execution import (
            GenerationExecutionEngine as PackageEngine,
        )
        from rag_modules.generation.execution.engine import (
            GenerationExecutionEngine as CanonicalEngine,
        )

        self.assertIs(PackageEngine, CanonicalEngine)

    def _build_package(self) -> AnswerEvidencePackage:
        return AnswerEvidencePackage(
            question="为什么鱼香肉丝会有酸甜平衡？",
            items=[
                AnswerEvidenceItem(
                    citation="菜谱证据 1",
                    recipe_id="recipe-1",
                    recipe_name="鱼香肉丝",
                    confidence=0.92,
                    matched_terms=["酸甜", "鱼香汁"],
                    evidence_units=[
                        {
                            "claim": "鱼香汁里的糖和醋共同塑造酸甜平衡。",
                            "is_graph_evidence": True,
                        }
                    ],
                    content="鱼香肉丝使用糖、醋、酱油调味。",
                )
            ],
        )

    def test_generate_direct_path_updates_trace(self) -> None:
        settings = GenerationSettings(enable_two_stage=False, max_retries=1)
        engine = GenerationExecutionEngine(
            settings=settings,
            client_adapter=_FakeClientAdapter([_FakeResponse("直接答案")]),
            prompt_builder=_FakePromptBuilder(),
            planner=_FakePlanner(),
            empty_evidence_answer="empty",
        )

        answer, trace = engine.generate_with_trace(
            question="怎么做鱼香肉丝？",
            package=self._build_package(),
            analysis=None,
        )

        self.assertEqual(answer, "直接答案")
        self.assertEqual(trace.mode, "direct")
        self.assertEqual(trace.request_retries, 0)
        self.assertFalse(hasattr(engine, "last_trace"))

    def test_generate_two_stage_path_uses_planner_and_compose(self) -> None:
        settings = GenerationSettings(enable_two_stage=True, max_retries=1)
        planner = _FakePlanner()
        engine = GenerationExecutionEngine(
            settings=settings,
            client_adapter=_FakeClientAdapter([_FakeResponse("两阶段答案")]),
            prompt_builder=_FakePromptBuilder(),
            planner=planner,
            empty_evidence_answer="empty",
        )

        answer, trace = engine.generate_with_trace(
            question="为什么鱼香肉丝会有酸甜层次？",
            package=self._build_package(),
            analysis=QueryAnalysis(
                query_complexity=0.85,
                relationship_intensity=0.82,
                reasoning_required=True,
                recommended_strategy=SearchStrategy.GRAPH_RAG,
            ),
        )

        self.assertEqual(answer, "两阶段答案")
        self.assertEqual(planner.calls, 1)
        self.assertEqual(trace.mode, "two_stage")
        self.assertGreaterEqual(trace.plan_latency_ms, 0.0)
        self.assertGreaterEqual(trace.compose_latency_ms, 0.0)

    def test_generate_two_stage_falls_back_to_direct(self) -> None:
        settings = GenerationSettings(enable_two_stage=True, max_retries=1)
        engine = GenerationExecutionEngine(
            settings=settings,
            client_adapter=_FakeClientAdapter(
                [
                    RuntimeError("compose failed"),
                    _FakeResponse("回退后的直接答案"),
                ]
            ),
            prompt_builder=_FakePromptBuilder(),
            planner=_FakePlanner(),
            empty_evidence_answer="empty",
        )

        answer, trace = engine.generate_with_trace(
            question="为什么鱼香肉丝需要糖和醋一起平衡？",
            package=self._build_package(),
            analysis=QueryAnalysis(
                query_complexity=0.9,
                relationship_intensity=0.9,
                reasoning_required=True,
                recommended_strategy=SearchStrategy.GRAPH_RAG,
            ),
        )

        self.assertEqual(answer, "回退后的直接答案")
        self.assertTrue(trace.fallback_used)
        self.assertIn("two_stage_to_direct_model", trace.fallback_reason)
        self.assertEqual(trace.mode, "two_stage")

    def test_stream_with_trace_returns_request_scoped_trace(self) -> None:
        settings = GenerationSettings(enable_two_stage=False, max_retries=1, stream_retries=1)
        engine = GenerationExecutionEngine(
            settings=settings,
            client_adapter=_FakeClientAdapter(stream_responses=[["chunk-1", "chunk-2"]]),
            prompt_builder=_FakePromptBuilder(),
            planner=_FakePlanner(),
            empty_evidence_answer="empty",
        )
        chunks: list[str] = []

        answer, trace = engine.stream_with_trace(
            question="stream question",
            package=self._build_package(),
            analysis=None,
            chunk_callback=chunks.append,
        )

        self.assertEqual(answer, "chunk-1chunk-2")
        self.assertEqual(chunks, ["chunk-1", "chunk-2"])
        self.assertEqual(trace.mode, "direct")
        self.assertGreaterEqual(trace.direct_latency_ms, 0.0)

    def test_empty_choices_degrades_without_second_model_call(self) -> None:
        client = _FakeClientAdapter(
            [
                _EmptyChoicesResponse(),
                _FakeResponse("must not be requested"),
            ]
        )
        engine = GenerationExecutionEngine(
            settings=GenerationSettings(enable_two_stage=True),
            client_adapter=client,
            prompt_builder=_FakePromptBuilder(),
            planner=_FakePlanner(),
            empty_evidence_answer="empty",
        )

        answer, trace = engine.generate_with_trace(
            question="explain a graph relation",
            package=self._build_package(),
            analysis=QueryAnalysis(
                query_complexity=0.9,
                relationship_intensity=0.9,
                reasoning_required=True,
                recommended_strategy=SearchStrategy.GRAPH_RAG,
            ),
        )

        self.assertEqual(len(client.prompts), 1)
        self.assertEqual(len(client.completions), 1)
        self.assertEqual(trace.status, "degraded")
        self.assertTrue(trace.fallback_used)
        self.assertEqual(trace.failure_code, "generation_provider_empty_choices")
        self.assertNotIn("no choices", answer.lower())

    def test_generation_timeout_is_capped_by_total_latency_budget(self) -> None:
        client = _FakeClientAdapter([_FakeResponse("budgeted answer")])
        engine = GenerationExecutionEngine(
            settings=GenerationSettings(
                enable_two_stage=False,
                timeout_seconds=45,
                latency_budget_seconds=2,
            ),
            client_adapter=client,
            prompt_builder=_FakePromptBuilder(),
            planner=_FakePlanner(),
            empty_evidence_answer="empty",
        )

        _answer, trace = engine.generate_with_trace(
            question="budgeted question",
            package=self._build_package(),
        )

        self.assertEqual(trace.status, "success")
        self.assertEqual(len(client.timeouts), 1)
        self.assertGreater(client.timeouts[0], 0)
        self.assertLessEqual(client.timeouts[0], 2)


if __name__ == "__main__":
    unittest.main()
