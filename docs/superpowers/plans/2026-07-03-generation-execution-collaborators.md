# Generation Execution Collaborators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace generation execution mixin state sharing with explicit collaborators for timeouts, usage, tracing, fallback, direct completion, two-stage completion, and streaming.

**Architecture:** `GenerationExecutionEngine` remains the public orchestration class, but it no longer inherits internal mixins or depends on a structural host protocol. Request-local state is passed through result objects and `GenerationSnapshot` updates are centralized in the trace recorder. Internal compatibility names such as `_GenerationExecutionHost` and `_DirectCompletionMixin` are removed rather than shimmed.

**Tech Stack:** Python 3.11, dataclasses, FastAPI runtime package conventions, pytest/unittest.

---

## File Structure

- `rag_modules/generation/execution/contracts.py`: shared dataclasses and typed exceptions for execution results and token usage.
- `rag_modules/generation/execution/timeouts.py`: explicit latency budget and deadline collaborator.
- `rag_modules/generation/execution/usage.py`: explicit retry and token usage collector around `GenerationClientAdapter`.
- `rag_modules/generation/execution/tracing.py`: trace creation, state mutation conventions, snapshots, and finalization.
- `rag_modules/generation/execution/fallbacks.py`: model-fallback policy and evidence-only fallback answer construction.
- `rag_modules/generation/execution/direct.py`: direct completion runner.
- `rag_modules/generation/execution/composer.py`: compose prompt runner used by the public compose API and two-stage execution.
- `rag_modules/generation/execution/two_stage.py`: two-stage plan/compose runner and direct model fallback handoff.
- `rag_modules/generation/execution/streaming.py`: streaming runner with explicit dependencies.
- `rag_modules/generation/execution/engine.py`: public engine that wires collaborators and delegates.
- `tests/test_generation_executor.py`: behavior and architecture contract tests.
- `tests/typecheck/type_contracts.py`: replace the removed mixin host contract with public engine and collaborator contracts.

### Task 1: Architecture Regression Tests

**Files:**
- Modify: `tests/test_generation_executor.py`

- [ ] **Step 1: Write failing tests**

```python
def test_generation_execution_engine_uses_explicit_collaborators(self) -> None:
    engine = GenerationExecutionEngine(
        settings=GenerationSettings(enable_two_stage=False),
        client_adapter=_FakeClientAdapter([_FakeResponse("answer")]),
        prompt_builder=_FakePromptBuilder(),
        planner=_FakePlanner(),
        empty_evidence_answer="empty",
    )

    self.assertEqual(GenerationExecutionEngine.__mro__, (GenerationExecutionEngine, object))
    self.assertTrue(hasattr(engine, "_timeout_budget"))
    self.assertTrue(hasattr(engine, "_usage_collector"))
    self.assertTrue(hasattr(engine, "_trace_recorder"))
    self.assertTrue(hasattr(engine, "_fallback_handler"))
    self.assertTrue(hasattr(engine, "_direct_runner"))
    self.assertTrue(hasattr(engine, "_two_stage_runner"))
    self.assertTrue(hasattr(engine, "_streaming_runner"))


def test_generation_trace_finalization_uses_request_scoped_usage_collector(self) -> None:
    client = _FakeClientAdapter(
        [_FakeResponse("answer")],
        token_usage=[
            {"prompt_tokens": 90, "completion_tokens": 90, "total_tokens": 180, "token_usage_source": "stale"},
            {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12, "token_usage_source": "fixture"},
        ],
    )
    engine = GenerationExecutionEngine(
        settings=GenerationSettings(
            enable_two_stage=False,
            input_cost_per_million_tokens=2.0,
            output_cost_per_million_tokens=4.0,
        ),
        client_adapter=client,
        prompt_builder=_FakePromptBuilder(),
        planner=_FakePlanner(),
        empty_evidence_answer="empty",
    )

    _answer, trace = engine.generate_with_trace(
        question="usage question",
        package=self._build_package(),
    )

    self.assertEqual(trace.prompt_tokens, 7)
    self.assertEqual(trace.completion_tokens, 5)
    self.assertEqual(trace.total_tokens, 12)
    self.assertEqual(trace.token_usage_source, "fixture")
    self.assertEqual(trace.estimated_cost_usd, 0.000034)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
python -m pytest tests/test_generation_executor.py::GenerationExecutionEngineTests::test_generation_execution_engine_uses_explicit_collaborators tests/test_generation_executor.py::GenerationExecutionEngineTests::test_generation_trace_finalization_uses_request_scoped_usage_collector -q
```

Expected: tests fail because the engine still inherits mixins and `_FakeClientAdapter` does not expose queued token usage.

### Task 2: Replace Mixin Host With Explicit Contracts

**Files:**
- Modify: `rag_modules/generation/execution/contracts.py`
- Create: `rag_modules/generation/execution/usage.py`

- [ ] **Step 1: Add execution dataclasses**

Create immutable result objects:

```python
@dataclass(frozen=True)
class GenerationTokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_source: str = ""


@dataclass(frozen=True)
class GenerationAttemptResult:
    answer: str
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    request_retries: int = 0
    status: str = "success"
    fallback_used: bool = False
    fallback_reason: str = ""
    failure: Exception | None = None


class GenerationAttemptFailed(Exception):
    def __init__(self, error: Exception, *, request_retries: int = 0) -> None:
        super().__init__(str(error))
        self.error = error
        self.request_retries = max(0, int(request_retries or 0))
```

- [ ] **Step 2: Remove host protocol names**

Delete `GenerationExecutionHost` and `_GenerationExecutionHost` from `contracts.py`. Do not re-export compatibility aliases.

### Task 3: Implement Collaborators

**Files:**
- Modify: `rag_modules/generation/execution/timeouts.py`
- Modify: `rag_modules/generation/execution/tracing.py`
- Create: `rag_modules/generation/execution/fallbacks.py`
- Create: `rag_modules/generation/execution/composer.py`
- Modify: `rag_modules/generation/execution/direct.py`
- Modify: `rag_modules/generation/execution/two_stage.py`
- Modify: `rag_modules/generation/execution/streaming.py`

- [ ] **Step 1: Convert timeout helpers**

Replace `_GenerationTimeoutMixin` with `GenerationTimeoutBudget` and `GenerationExecutionDeadline`.

- [ ] **Step 2: Convert tracing helpers**

Replace `_GenerationTraceMixin` with `GenerationTraceRecorder`. The recorder owns all `GenerationSnapshot` field mutation except request-local creation by the engine.

- [ ] **Step 3: Convert execution paths**

Replace `_DirectCompletionMixin`, `_TwoStageCompletionMixin`, and `_StreamingGenerationMixin` with runner classes. Runners receive dependencies in their constructors and return `GenerationAttemptResult` or a streaming `GenerationSnapshot`.

### Task 4: Wire Engine Directly

**Files:**
- Modify: `rag_modules/generation/execution/engine.py`

- [ ] **Step 1: Remove mixin inheritance**

Make the class definition:

```python
class GenerationExecutionEngine:
    """Own generation execution orchestration through explicit collaborators."""
```

- [ ] **Step 2: Instantiate collaborators**

In `__init__`, create `_timeout_budget`, `_usage_collector`, `_trace_recorder`, `_fallback_handler`, `_composer`, `_direct_runner`, `_two_stage_runner`, and `_streaming_runner`.

- [ ] **Step 3: Delegate public methods**

Keep the existing public methods and signatures. `generate_with_trace()` delegates direct and two-stage work to runners. `stream()` and `stream_with_trace()` delegate to `_streaming_runner`. `compose_from_context()` delegates to `_composer`.

### Task 5: Update Type and Documentation References

**Files:**
- Modify: `tests/typecheck/type_contracts.py`
- Modify: `docs/superpowers/specs/2026-06-14-api-generation-milvus-module-split-design.md`

- [ ] **Step 1: Update type contract import**

Remove the `GenerationExecutionHost` import and type the generation return value as `GenerationExecutionEngine`.

- [ ] **Step 2: Update historical design note**

Change the generation execution section to say the initial mixin split has been superseded by explicit collaborators.

### Task 6: Verification

**Files:**
- Test: `tests/test_generation_executor.py`
- Test: `tests/test_type_contract_ratchets.py`
- Test: `tests/test_public_surface_boundaries.py`

- [ ] **Step 1: Run focused tests**

```powershell
python -m pytest tests/test_generation_executor.py tests/test_type_contract_ratchets.py -q
```

- [ ] **Step 2: Run public-surface guard**

```powershell
python -m pytest tests/test_public_surface_boundaries.py -q
```

- [ ] **Step 3: Run formatting or pre-commit**

```powershell
pre-commit run --all-files
```
