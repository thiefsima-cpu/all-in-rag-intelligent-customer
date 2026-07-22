"""Shared offline helpers for answer-pipeline smoke tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable

from rag_modules.app.providers import create_default_runtime_provider
from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
from rag_modules.contracts.runtime.generation import GenerationSnapshot
from rag_modules.contracts.runtime.workflows import AnswerContext
from rag_modules.evidence_processing.answer_builder import AnswerEvidenceBuilder
from rag_modules.generation import (
    GenerationExecutionEngine,
    GenerationPlanner,
    GenerationPromptBuilder,
    GenerationSettings,
)
from rag_modules.observability.tracing import QueryTracer
from rag_modules.observability.tracing_sinks import QueryTraceSink
from rag_modules.retrieval.runtime_profile import RetrievalRuntimeProfileFactory


class CaptureSink(QueryTraceSink):
    def __init__(self) -> None:
        self.events = []

    def write(self, event) -> None:
        self.events.append(event)

    def close(self) -> None:
        return None


class OfflineCompletions:
    def __init__(self, responses: Iterable[str]) -> None:
        self.responses = list(responses)

    def create_completion(self, *, prompt: str, **_: object):
        if not self.responses:
            raise AssertionError(f"Unexpected completion request for prompt: {prompt[:80]}")
        text = self.responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

    def stream_prompt(self, **_: object):
        raise AssertionError("Offline answer pipeline smoke does not use streaming.")

    @staticmethod
    def load_json_payload(payload: str):
        raise AssertionError("Rule planner mode should not request JSON planning payloads.")

    @staticmethod
    def response_text(response) -> str:
        return str(response.choices[0].message.content or "")


class OfflineGenerationModule:
    def __init__(self, responses: Iterable[str]) -> None:
        self.settings = GenerationSettings(planner_mode="rule", max_retries=1)
        self.evidence_builder = AnswerEvidenceBuilder(max_content_chars=700)
        self.prompt_builder = GenerationPromptBuilder(
            settings=self.settings,
            evidence_max_chars=700,
        )
        self.client_adapter = OfflineCompletions(responses)
        self.planner = GenerationPlanner(
            settings=self.settings,
            client_adapter=self.client_adapter,
            prompt_builder=self.prompt_builder,
        )
        self.executor = GenerationExecutionEngine(
            settings=self.settings,
            client_adapter=self.client_adapter,
            prompt_builder=self.prompt_builder,
            planner=self.planner,
            empty_evidence_answer="empty",
        )

    def generate_answer_from_context(self, answer_context, *, control=None):
        answer, _trace = self.generate_answer_with_trace_from_context(
            answer_context,
            control=control,
        )
        return answer

    def generate_answer_with_trace_from_context(
        self,
        answer_context,
        *,
        control=None,
    ) -> tuple[str, GenerationSnapshot]:
        context = (
            answer_context
            if isinstance(answer_context, AnswerContext)
            else AnswerContext(**dict(answer_context))
        )
        package = self.evidence_builder.build(
            context.question,
            context.evidence_documents,
        )
        return self.executor.generate_with_trace(
            answer_context=context.with_evidence_package(package),
            control=control,
        )


def build_tracer() -> tuple[QueryTracer, CaptureSink]:
    sink = CaptureSink()
    tracer = QueryTracer(
        load_config(
            source=EnvConfigSource(environ={}),
            overrides={
                "observability": {
                    "enable_query_tracing": True,
                    "query_trace_path": "unused.jsonl",
                }
            },
        ),
        sink=sink,
    )
    return tracer, sink


def build_answer_workflow(
    *,
    config,
    query_router,
    generation_module,
    query_tracer,
    retrieval_profile=None,
):
    """Compose the answer use case with the same provider used by runtime assembly."""

    retrieval_profile = retrieval_profile or RetrievalRuntimeProfileFactory().build(config)
    return create_default_runtime_provider().services.provide_answer_workflow(
        config=config,
        query_router=query_router,
        generation_module=generation_module,
        query_tracer=query_tracer,
        retrieval_profile=retrieval_profile,
    )
