from __future__ import annotations

import unittest

from rag_modules.configuration.models import GraphRAGConfig
from rag_modules.generation.models import AnswerPlan, GenerationSettings, RenderedPrompt
from rag_modules.generation.service import GenerationWorkflowService
from rag_modules.query_policy.models import (
    GenerationPolicy,
    GraphPolicy,
    GraphReasoningPolicy,
    LexiconPolicy,
    PolicyMetadata,
    PromptTemplates,
    QueryPolicyBundle,
    RelationPolicy,
    RoutingPolicy,
    ScoringPolicy,
)
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


def _policy_bundle(*, policy_version: str = "test-policy-v1") -> QueryPolicyBundle:
    return QueryPolicyBundle(
        metadata=PolicyMetadata(
            schema_version="policy-bundle-v1",
            policy_version=policy_version,
            prompt_version="test-prompts-v1",
            policy_hash="sha256:policy",
            prompt_hash="sha256:prompt",
            bundle_name="test-policy",
        ),
        lexicon=LexiconPolicy(term_sets={}, regex_rules={}),
        relations=RelationPolicy(
            graph_routing_strategies=(),
            graph_query_types=(),
            graph_relation_types=(),
            preferred_relation_excluded_types=(),
            semantic_relation_hints={},
            relation_index_keywords={},
            relation_index_suffix_templates={},
            relation_query_markers={},
            entity_linker_preferred_labels=(),
            entity_linker_query_type_priorities={},
            entity_linker_relation_priorities={},
        ),
        scoring=ScoringPolicy(
            structural_relationship_factor=1.0,
            length_norm_chars=100,
            weights={},
            boosts={},
        ),
        routing=RoutingPolicy(
            graph_first_query_types=(),
            multi_hop_graph_first_relation_hits=1,
            meaningful_constraint_fields=(),
            validation_labels={},
        ),
        graph=GraphPolicy(
            max_depth={},
            max_nodes={},
            sub_questions=(),
            reasoning=GraphReasoningPolicy(
                causal_relation_types=(),
                compositional_relation_types=(),
                comparison_markers=(),
                semantic_relation_key_specs={},
            ),
        ),
        generation=GenerationPolicy(
            answer_types={},
            relation_explanation_markers=(),
            rule_plan={},
            decision={"default_answer_type": "direct_answer"},
            fallback_answer={},
        ),
        runtime_defaults={},
        prompts=PromptTemplates(
            query_planner="query",
            answer_plan="plan {question} {evidence_summary}",
            answer_compose="compose {question} {plan_json} {evidence_text}",
            answer_direct="direct {question} {evidence_text}",
        ),
    )


def _service() -> GenerationWorkflowService:
    service = object.__new__(GenerationWorkflowService)
    service.context_factory = _StubContextFactory()
    service.executor = _StubExecutor()
    service.planner = _StubPlanner()
    service.prompt_builder = _StubPromptBuilder()
    return service


class GenerationWorkflowServiceContextTests(unittest.TestCase):
    def test_constructor_accepts_settings_client_factory_and_prompt_policy(self) -> None:
        client = object()
        settings = GenerationSettings(
            model_name="settings-model",
            temperature=0.35,
            max_tokens=1536,
            request_retries=3,
        )

        service = GenerationWorkflowService(
            settings=settings,
            client_factory=lambda: client,
            prompt_policy=_policy_bundle(policy_version="constructor-policy-v1"),
            evidence_max_chars=1200,
            base_url="https://llm.example/v1",
            circuit_breaker_failure_threshold=7,
            circuit_breaker_recovery_seconds=12.5,
        )

        self.assertIs(service.settings, settings)
        self.assertEqual(service.model_name, "settings-model")
        self.assertEqual(service.temperature, 0.35)
        self.assertEqual(service.max_tokens, 1536)
        self.assertIs(service.client, client)
        self.assertEqual(service.base_url, "https://llm.example/v1")
        self.assertEqual(service.evidence_max_chars, 1200)
        self.assertEqual(
            service.prompt_builder.policy_snapshot.policy_version,
            "constructor-policy-v1",
        )

    def test_from_config_maps_to_generation_settings_and_injected_dependencies(self) -> None:
        client = object()
        config = GraphRAGConfig.from_dict(
            {
                "models": {
                    "llm_model": "config-model",
                    "llm_base_url": "https://config.example/v1",
                    "circuit_breaker_failure_threshold": 9,
                    "circuit_breaker_recovery_seconds": 15.0,
                    "llm_input_cost_per_million_tokens": 0.5,
                    "llm_output_cost_per_million_tokens": 1.5,
                },
                "generation": {
                    "temperature": 0.25,
                    "max_tokens": 1024,
                    "generation_timeout_seconds": 12,
                    "generation_stream_timeout_seconds": 13,
                    "generation_request_retries": 4,
                    "generation_evidence_max_chars": 900,
                },
            }
        )

        service = GenerationWorkflowService.from_config(
            config,
            client_factory=lambda: client,
            prompt_policy=_policy_bundle(policy_version="config-policy-v1"),
        )

        self.assertEqual(service.settings.model_name, "config-model")
        self.assertEqual(service.settings.temperature, 0.25)
        self.assertEqual(service.settings.max_tokens, 1024)
        self.assertEqual(service.settings.timeout_seconds, 12)
        self.assertEqual(service.settings.stream_timeout_seconds, 13)
        self.assertEqual(service.settings.request_retries, 4)
        self.assertEqual(service.settings.input_cost_per_million_tokens, 0.5)
        self.assertEqual(service.settings.output_cost_per_million_tokens, 1.5)
        self.assertIs(service.client, client)
        self.assertEqual(service.base_url, "https://config.example/v1")
        self.assertEqual(service.evidence_max_chars, 900)
        self.assertEqual(
            service.prompt_builder.policy_snapshot.policy_version,
            "config-policy-v1",
        )

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
