# String Strategy Enum Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four named string strategy families with focused Enum boundaries while keeping public JSON and config values string-compatible.

**Architecture:** Add local `str, Enum` types in the modules that own each vocabulary. Normalize strings at dataclass/Pydantic boundaries, store enum instances internally where practical, and serialize `.value` to existing payloads. Keep existing constants as compatibility aliases so broad call sites can migrate without a public contract change.

**Tech Stack:** Python 3.11, dataclasses, Pydantic v2 validators, unittest/pytest, existing `rag_modules` runtime/configuration/retrieval/generation/query contracts.

---

## File Structure

- Modify `rag_modules/runtime/artifacts/manifest.py`: define `ArtifactStage`, normalize `ArtifactManifest.stage`, keep stage constants and payload strings.
- Modify `rag_modules/runtime/artifacts/__init__.py`: export `ArtifactStage`.
- Modify `tests/test_build_pipeline_manifest_lifecycle.py`: add focused artifact-stage enum compatibility tests.
- Modify `rag_modules/contracts/query.py`: use `SearchStrategy` and add `QueryPlannerMode` for query plan route strategy/planner mode normalization.
- Modify `rag_modules/query_understanding/planning/calibration.py`: compare/return route strategies through `SearchStrategy` values.
- Modify `rag_modules/query_understanding/planning/rule_based.py`: construct `QueryPlan` with enum-derived route strategy and planner mode.
- Modify `rag_modules/query_understanding/planning/service.py`: assign `QueryPlannerMode` values instead of raw planner-mode strings.
- Modify `tests/test_query_semantics.py`: add route strategy/planner mode normalization tests.
- Modify `rag_modules/retrieval/candidate_generator.py`: define/reuse `CandidateSourceDegradationStrategy`, store enum internally, preserve behavior.
- Modify `rag_modules/retrieval/runtime_profile/candidate_source_settings.py`: reuse the same enum and export compatibility constants.
- Modify `rag_modules/configuration/model_sections/retrieval.py`: validate degradation strategy in config.
- Modify `tests/test_retrieval_candidate_generator.py`, `tests/test_hybrid_search_service.py`, and `tests/test_configuration_section_loaders.py`: cover enum storage and config rejection.
- Modify `rag_modules/generation/models.py`: add `GenerationPlannerMode`, normalize/reject runtime settings planner mode.
- Modify `rag_modules/configuration/model_sections/generation.py`: validate generation planner mode in config.
- Modify `rag_modules/generation/planner.py`: compare planner mode through enum values.
- Modify `rag_modules/generation/__init__.py`: export `GenerationPlannerMode`.
- Modify `tests/test_generation_executor.py` and `tests/test_configuration_section_loaders.py`: cover valid and invalid planner mode normalization.

## Task 1: Artifact Stage Enum

**Files:**
- Modify: `rag_modules/runtime/artifacts/manifest.py`
- Modify: `rag_modules/runtime/artifacts/__init__.py`
- Test: `tests/test_build_pipeline_manifest_lifecycle.py`

- [ ] **Step 1: Write the failing artifact-stage tests**

Add `ArtifactStage` to the import list in `tests/test_build_pipeline_manifest_lifecycle.py`:

```python
from rag_modules.runtime.artifacts import (
    ARTIFACT_STAGE_BUILDING,
    ARTIFACT_STAGE_DOCUMENTS_READY,
    ARTIFACT_STAGE_FAILED,
    ARTIFACT_STAGE_MANIFEST_UNREADABLE,
    ARTIFACT_STAGE_READY,
    ARTIFACT_STAGE_REBUILDING,
    ARTIFACT_STAGE_STALE,
    ArtifactManifest,
    ArtifactStage,
)
```

Add these methods to `KnowledgeBaseManifestLifecycleTests`:

```python
    def test_artifact_manifest_accepts_enum_stage_and_serializes_string(self) -> None:
        manifest = ArtifactManifest(stage=ArtifactStage.READY)

        self.assertIs(manifest.stage, ArtifactStage.READY)
        self.assertTrue(manifest.is_ready)
        self.assertEqual(manifest.to_dict()["stage"], "ready")

    def test_artifact_manifest_from_dict_and_evolve_normalize_stage(self) -> None:
        manifest = ArtifactManifest.from_dict({"stage": "documents_ready"})
        evolved = manifest.evolve(stage="ready")

        self.assertIs(manifest.stage, ArtifactStage.DOCUMENTS_READY)
        self.assertIs(evolved.stage, ArtifactStage.READY)
        self.assertEqual(evolved.to_dict()["stage"], "ready")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests/test_build_pipeline_manifest_lifecycle.py -q
```

Expected: FAIL with an import error or attribute error mentioning `ArtifactStage`.

- [ ] **Step 3: Implement `ArtifactStage` and normalization**

In `rag_modules/runtime/artifacts/manifest.py`, import `Enum`, add the enum above constants, and
derive constants from enum values:

```python
from enum import Enum
```

```python
class ArtifactStage(str, Enum):
    MISSING = "missing"
    DOCUMENTS_READY = "documents_ready"
    BUILDING = "building"
    REBUILDING = "rebuilding"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"
    MANIFEST_UNREADABLE = "manifest_unreadable"


def _artifact_stage(value: "ArtifactStage | str | None") -> ArtifactStage:
    if isinstance(value, ArtifactStage):
        return value
    try:
        return ArtifactStage(str(value or ArtifactStage.MISSING.value))
    except ValueError:
        return ArtifactStage.MISSING
```

Replace the stage constants:

```python
ARTIFACT_STAGE_MISSING = ArtifactStage.MISSING.value
ARTIFACT_STAGE_DOCUMENTS_READY = ArtifactStage.DOCUMENTS_READY.value
ARTIFACT_STAGE_BUILDING = ArtifactStage.BUILDING.value
ARTIFACT_STAGE_REBUILDING = ArtifactStage.REBUILDING.value
ARTIFACT_STAGE_READY = ArtifactStage.READY.value
ARTIFACT_STAGE_FAILED = ArtifactStage.FAILED.value
ARTIFACT_STAGE_STALE = ArtifactStage.STALE.value
ARTIFACT_STAGE_MANIFEST_UNREADABLE = ArtifactStage.MANIFEST_UNREADABLE.value
```

Use enum sets:

```python
ARTIFACT_IN_PROGRESS_STAGES = frozenset(
    {
        ArtifactStage.BUILDING,
        ArtifactStage.REBUILDING,
        ArtifactStage.DOCUMENTS_READY,
    }
)
ARTIFACT_INVALID_STAGES = frozenset(
    {
        ArtifactStage.MISSING,
        ArtifactStage.FAILED,
        ArtifactStage.STALE,
        ArtifactStage.MANIFEST_UNREADABLE,
    }
)
```

Update `ArtifactManifest` stage field and add `__post_init__`:

```python
    stage: ArtifactStage | str = ArtifactStage.MISSING

    def __post_init__(self) -> None:
        self.stage = _artifact_stage(self.stage)
```

Update stage comparisons and serialization:

```python
    @property
    def is_ready(self) -> bool:
        return self.stage == ArtifactStage.READY

    @property
    def is_missing(self) -> bool:
        return self.stage == ArtifactStage.MISSING

    @property
    def is_stale(self) -> bool:
        return self.stage == ArtifactStage.STALE

    @property
    def is_failed(self) -> bool:
        return self.stage in {ArtifactStage.FAILED, ArtifactStage.MANIFEST_UNREADABLE}

    @property
    def is_in_progress(self) -> bool:
        return self.stage in ARTIFACT_IN_PROGRESS_STAGES

    @property
    def is_invalid(self) -> bool:
        return self.stage in ARTIFACT_INVALID_STAGES
```

In `to_dict()`:

```python
            "stage": self.stage.value,
```

In `evolve()`, normalize stage if present before `replace()`:

```python
        if "stage" in changes:
            changes["stage"] = _artifact_stage(changes["stage"])
```

In `from_dict()` and `missing()`, pass enum or string through the normalizer:

```python
            stage=_artifact_stage(payload.get("stage")),
```

```python
            stage=ArtifactStage.MISSING,
```

Add `"ArtifactStage"` to `__all__`.

In `rag_modules/runtime/artifacts/__init__.py`, import and export `ArtifactStage`.

- [ ] **Step 4: Run artifact tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_build_pipeline_manifest_lifecycle.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit artifact-stage change**

Run:

```powershell
git add rag_modules/runtime/artifacts/manifest.py rag_modules/runtime/artifacts/__init__.py tests/test_build_pipeline_manifest_lifecycle.py
git commit -m "refactor: type artifact manifest stages"
```

## Task 2: Route Strategy and Query Planner Mode

**Files:**
- Modify: `rag_modules/contracts/query.py`
- Modify: `rag_modules/query_understanding/planning/calibration.py`
- Modify: `rag_modules/query_understanding/planning/rule_based.py`
- Modify: `rag_modules/query_understanding/planning/service.py`
- Test: `tests/test_query_semantics.py`

- [ ] **Step 1: Write failing query strategy tests**

Update imports in `tests/test_query_semantics.py`:

```python
from rag_modules.contracts import (
    QueryPlan,
    QueryPlannerMode,
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
)
from rag_modules.runtime import SearchStrategy
```

Add these tests to `QuerySemanticsTests`:

```python
    def test_query_plan_normalizes_route_strategy_and_planner_mode_enums(self) -> None:
        plan = QueryPlan.from_dict(
            "recommend tofu",
            {
                "strategy": "combined",
                "planner_mode": "fast_rule",
                "constraints": {"needs_recipe_recommendation": True},
            },
        )

        self.assertIs(plan.strategy, SearchStrategy.COMBINED)
        self.assertIs(plan.planner_mode, QueryPlannerMode.FAST_RULE)
        self.assertEqual(plan.to_dict()["strategy"], "combined")
        self.assertEqual(plan.to_dict()["planner_mode"], "fast_rule")

    def test_query_plan_keeps_invalid_strategy_fallback_behavior(self) -> None:
        plan = QueryPlan.from_dict(
            "recommend tofu",
            {
                "strategy": "typo",
                "planner_mode": "llm",
                "constraints": {"needs_recipe_recommendation": True},
            },
        )

        self.assertIs(plan.strategy, SearchStrategy.COMBINED)
        self.assertIn("invalid_strategy:typo", plan.validation_errors)
        self.assertEqual(plan.to_dict()["strategy"], "combined")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests/test_query_semantics.py -q
```

Expected: FAIL because `QueryPlannerMode` is missing or `plan.strategy` remains a string.

- [ ] **Step 3: Implement query plan normalization**

In `rag_modules/contracts/query.py`, add imports and helpers:

```python
from enum import Enum

from ..runtime.analysis_models import SearchStrategy
```

```python
class QueryPlannerMode(str, Enum):
    LLM = "llm"
    RULE_BASED = "rule_based"
    FAST_RULE = "fast_rule"
    FALLBACK_RULE = "fallback_rule"


def _search_strategy(value: Any) -> SearchStrategy:
    if isinstance(value, SearchStrategy):
        return value
    return SearchStrategy(str(value or SearchStrategy.HYBRID_TRADITIONAL.value))


def _query_planner_mode(value: Any) -> QueryPlannerMode:
    if isinstance(value, QueryPlannerMode):
        return value
    try:
        return QueryPlannerMode(str(value or QueryPlannerMode.LLM.value))
    except ValueError:
        return QueryPlannerMode.LLM
```

Change `QueryPlan` fields:

```python
    strategy: SearchStrategy | str = SearchStrategy.HYBRID_TRADITIONAL
    planner_mode: QueryPlannerMode | str = QueryPlannerMode.LLM
```

Add `__post_init__` to `QueryPlan`:

```python
    def __post_init__(self) -> None:
        self.strategy = _search_strategy(self.strategy)
        self.planner_mode = _query_planner_mode(self.planner_mode)
```

In `QueryPlan.from_dict()`, validate raw strategy first, then assign enum:

```python
        raw_strategy = str(data.get("strategy") or SearchStrategy.HYBRID_TRADITIONAL.value)
        try:
            strategy = SearchStrategy(raw_strategy)
        except ValueError:
            validation_errors.append(f"invalid_strategy:{raw_strategy}")
            strategy = (
                SearchStrategy.COMBINED
                if constraints.has_constraints()
                else SearchStrategy.HYBRID_TRADITIONAL
            )
```

Return `planner_mode=_query_planner_mode(data.get("planner_mode"))`.

In `QueryPlan.to_dict()`:

```python
            "strategy": self.strategy.value,
            "planner_mode": self.planner_mode.value,
```

Export `QueryPlannerMode` in `__all__`.

- [ ] **Step 4: Update route strategy comparisons in planning code**

In `rag_modules/query_understanding/planning/calibration.py`, import `SearchStrategy` and replace
route strategy string sets/comparisons with enum-normalized values:

```python
from ...runtime import SearchStrategy
```

Use:

```python
_VALID_STRATEGIES = {strategy.value for strategy in SearchStrategy}
```

Keep method signatures returning `str` only if broader callers need strings, but compare against
`SearchStrategy.COMBINED.value`, `SearchStrategy.GRAPH_RAG.value`, and
`SearchStrategy.HYBRID_TRADITIONAL.value`.

In `rag_modules/query_understanding/planning/rule_based.py`, import `SearchStrategy` and
`QueryPlannerMode`; use `.value` for strings returned by calibrator and enum for `QueryPlan`:

```python
from ...runtime import SearchStrategy
from ...contracts import QueryPlan, QueryPlannerMode, QuerySemanticRuntimeSettings
```

```python
            current_strategy=SearchStrategy.HYBRID_TRADITIONAL.value,
```

```python
            strategy=SearchStrategy(strategy),
            fallback_reason="rule_based",
            planner_mode=QueryPlannerMode.RULE_BASED,
```

In `rag_modules/query_understanding/planning/service.py`, import `QueryPlannerMode` and assign:

```python
            plan.planner_mode = QueryPlannerMode.FAST_RULE
```

```python
            plan.planner_mode = QueryPlannerMode.LLM
```

```python
            plan.planner_mode = QueryPlannerMode.FALLBACK_RULE
```

When logging, use `plan.planner_mode.value` if needed.

- [ ] **Step 5: Run query tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_query_semantics.py tests/test_runtime_workflow_models.py tests/test_answer_workflow.py -q
```

Expected: PASS. If existing tests compare `plan.strategy` to strings, update assertions to compare
`plan.to_dict()["strategy"]` for wire-format tests or `SearchStrategy.*` for internal tests.

- [ ] **Step 6: Commit query strategy change**

Run:

```powershell
git add rag_modules/contracts/query.py rag_modules/query_understanding/planning/calibration.py rag_modules/query_understanding/planning/rule_based.py rag_modules/query_understanding/planning/service.py tests/test_query_semantics.py tests/test_runtime_workflow_models.py tests/test_answer_workflow.py
git commit -m "refactor: type query route strategies"
```

## Task 3: Candidate-Source Degradation Strategy

**Files:**
- Modify: `rag_modules/retrieval/candidate_generator.py`
- Modify: `rag_modules/retrieval/runtime_profile/candidate_source_settings.py`
- Modify: `rag_modules/configuration/model_sections/retrieval.py`
- Test: `tests/test_retrieval_candidate_generator.py`
- Test: `tests/test_hybrid_search_service.py`
- Test: `tests/test_configuration_section_loaders.py`

- [ ] **Step 1: Write failing degradation strategy tests**

In `tests/test_retrieval_candidate_generator.py`, update imports:

```python
from rag_modules.retrieval.candidate_generator import (
    CandidateSourceDegradationStrategy,
    RetrievalCandidateGenerator,
)
```

Add:

```python
    def test_degradation_strategy_is_stored_as_enum(self) -> None:
        generator = RetrievalCandidateGenerator(
            sources=[],
            source_degradation_strategy="fail_fast",
        )

        self.assertIs(
            generator.source_degradation_strategy,
            CandidateSourceDegradationStrategy.FAIL_FAST,
        )
```

In `tests/test_hybrid_search_service.py`, import `CandidateSourceDegradationStrategy` and update
the final assertion:

```python
        self.assertIs(
            service.candidate_generator.source_degradation_strategy,
            CandidateSourceDegradationStrategy.FAIL_FAST,
        )
```

In `tests/test_configuration_section_loaders.py`, add:

```python
    def test_retrieval_settings_reject_invalid_candidate_source_degradation_strategy(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(
                source=EnvConfigSource(
                    environ={
                        "RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY": "keep_going",
                    }
                )
            )

        self.assertConfigErrorMentions(
            context.exception,
            "candidate_source_degradation_strategy",
            "continue",
            "fail_fast",
        )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because `CandidateSourceDegradationStrategy` is missing and invalid config is not
rejected.

- [ ] **Step 3: Implement shared degradation strategy enum**

In `rag_modules/retrieval/candidate_generator.py`, import `Enum` and add:

```python
from enum import Enum
```

```python
class CandidateSourceDegradationStrategy(str, Enum):
    CONTINUE = "continue"
    FAIL_FAST = "fail_fast"


def _normalize_source_degradation_strategy(
    value: "CandidateSourceDegradationStrategy | str",
) -> CandidateSourceDegradationStrategy:
    if isinstance(value, CandidateSourceDegradationStrategy):
        return value
    normalized = str(value or CandidateSourceDegradationStrategy.CONTINUE.value).strip().lower()
    try:
        return CandidateSourceDegradationStrategy(normalized)
    except ValueError:
        supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
        raise ValueError(f"source_degradation_strategy must be one of: {supported}") from None
```

Replace constants:

```python
SOURCE_DEGRADATION_STRATEGY_CONTINUE = CandidateSourceDegradationStrategy.CONTINUE.value
SOURCE_DEGRADATION_STRATEGY_FAIL_FAST = CandidateSourceDegradationStrategy.FAIL_FAST.value
SUPPORTED_SOURCE_DEGRADATION_STRATEGIES = {
    strategy.value for strategy in CandidateSourceDegradationStrategy
}
```

Change constructor annotation:

```python
        source_degradation_strategy: CandidateSourceDegradationStrategy | str = (
            CandidateSourceDegradationStrategy.CONTINUE
        ),
```

Change `_should_raise_degradation()`:

```python
        return self.source_degradation_strategy is CandidateSourceDegradationStrategy.FAIL_FAST
```

Export `CandidateSourceDegradationStrategy`.

- [ ] **Step 4: Reuse enum from runtime profile and config**

In `rag_modules/retrieval/runtime_profile/candidate_source_settings.py`, import the enum and
normalizer:

```python
from ..candidate_generator import (
    CandidateSourceDegradationStrategy,
    _normalize_source_degradation_strategy,
)
```

Derive constants:

```python
CANDIDATE_SOURCE_DEGRADATION_CONTINUE = CandidateSourceDegradationStrategy.CONTINUE.value
CANDIDATE_SOURCE_DEGRADATION_FAIL_FAST = CandidateSourceDegradationStrategy.FAIL_FAST.value
SUPPORTED_CANDIDATE_SOURCE_DEGRADATION_STRATEGIES = {
    strategy.value for strategy in CandidateSourceDegradationStrategy
}
```

Change dataclass field and `__post_init__`:

```python
    degradation_strategy: CandidateSourceDegradationStrategy | str = (
        CandidateSourceDegradationStrategy.CONTINUE
    )
```

```python
        self.degradation_strategy = _normalize_degradation_strategy(
            self.degradation_strategy,
        )
```

Have `_normalize_degradation_strategy()` return the enum by delegating to
`_normalize_source_degradation_strategy()`.

In `to_dict()`, serialize enum values:

```python
        return {
            field.name: (
                getattr(self, field.name).value
                if isinstance(getattr(self, field.name), CandidateSourceDegradationStrategy)
                else getattr(self, field.name)
            )
            for field in self.__dataclass_fields__.values()
        }
```

In `rag_modules/configuration/model_sections/retrieval.py`, import the enum and validate:

```python
from ...retrieval.candidate_generator import CandidateSourceDegradationStrategy
```

```python
    @model_validator(mode="after")
    def normalize_degradation_strategy(self) -> Self:
        normalized = self.candidate_source_degradation_strategy.strip().lower() or (
            CandidateSourceDegradationStrategy.CONTINUE.value
        )
        try:
            strategy = CandidateSourceDegradationStrategy(normalized)
        except ValueError:
            supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
            raise ValueError(
                f"candidate_source_degradation_strategy must be one of: {supported}"
            ) from None
        object.__setattr__(
            self,
            "candidate_source_degradation_strategy",
            strategy.value,
        )
        return self
```

- [ ] **Step 5: Run degradation tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit degradation strategy change**

Run:

```powershell
git add rag_modules/retrieval/candidate_generator.py rag_modules/retrieval/runtime_profile/candidate_source_settings.py rag_modules/configuration/model_sections/retrieval.py tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_configuration_section_loaders.py
git commit -m "refactor: type candidate degradation strategy"
```

## Task 4: Generation Planner Mode

**Files:**
- Modify: `rag_modules/generation/models.py`
- Modify: `rag_modules/configuration/model_sections/generation.py`
- Modify: `rag_modules/generation/planner.py`
- Modify: `rag_modules/generation/__init__.py`
- Test: `tests/test_generation_executor.py`
- Test: `tests/test_configuration_section_loaders.py`

- [ ] **Step 1: Write failing generation planner mode tests**

In `tests/test_generation_executor.py`, import `GenerationPlannerMode`:

```python
from rag_modules.generation import (
    AnswerPlan,
    GenerationExecutionEngine,
    GenerationPlannerMode,
    GenerationSettings,
    RenderedPrompt,
)
```

Add:

```python
    def test_generation_settings_normalizes_planner_mode_to_enum(self) -> None:
        settings = GenerationSettings(planner_mode="hybrid")

        self.assertIs(settings.planner_mode, GenerationPlannerMode.HYBRID)
```

In `tests/test_configuration_section_loaders.py`, add:

```python
    def test_generation_settings_reject_invalid_planner_mode(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(
                source=EnvConfigSource(
                    environ={
                        "GENERATION_PLANNER_MODE": "rules",
                    }
                )
            )

        self.assertConfigErrorMentions(
            context.exception,
            "generation_planner_mode",
            "rule",
            "hybrid",
            "llm",
        )
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```powershell
python -m pytest tests/test_generation_executor.py tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because `GenerationPlannerMode` is missing or invalid planner mode is accepted.

- [ ] **Step 3: Implement generation planner mode enum**

In `rag_modules/generation/models.py`, import `Enum` and add:

```python
from enum import Enum
```

```python
class GenerationPlannerMode(str, Enum):
    RULE = "rule"
    HYBRID = "hybrid"
    LLM = "llm"


def _generation_planner_mode(value: "GenerationPlannerMode | str") -> GenerationPlannerMode:
    if isinstance(value, GenerationPlannerMode):
        return value
    normalized = str(value or GenerationPlannerMode.RULE.value).strip().lower()
    try:
        return GenerationPlannerMode(normalized)
    except ValueError:
        supported = ", ".join(mode.value for mode in GenerationPlannerMode)
        raise ValueError(f"planner_mode must be one of: {supported}") from None
```

Change `GenerationSettings.planner_mode`:

```python
    planner_mode: GenerationPlannerMode | str = GenerationPlannerMode.RULE
```

In `__post_init__`:

```python
        self.planner_mode = _generation_planner_mode(self.planner_mode)
```

In `rag_modules/generation/planner.py`, import `GenerationPlannerMode` and compare:

```python
from .models import AnswerPlan, GenerationPlannerMode, GenerationSettings
```

```python
        if self.settings.planner_mode is GenerationPlannerMode.RULE:
            return self._build_rule_based_plan(question, package)
        if (
            self.settings.planner_mode is GenerationPlannerMode.HYBRID
            and self._can_use_rule_plan(package, analysis)
        ):
            return self._build_rule_based_plan(question, package)
```

In `rag_modules/generation/__init__.py`, export `GenerationPlannerMode`.

- [ ] **Step 4: Validate generation config planner mode**

In `rag_modules/configuration/model_sections/generation.py`, import `Self`, `model_validator`, and
`GenerationPlannerMode`:

```python
from typing import Self

from pydantic import model_validator

from ...generation.models import GenerationPlannerMode
```

Add validator:

```python
    @model_validator(mode="after")
    def normalize_generation_planner_mode(self) -> Self:
        normalized = self.generation_planner_mode.strip().lower() or (
            GenerationPlannerMode.RULE.value
        )
        try:
            mode = GenerationPlannerMode(normalized)
        except ValueError:
            supported = ", ".join(mode.value for mode in GenerationPlannerMode)
            raise ValueError(f"generation_planner_mode must be one of: {supported}") from None
        object.__setattr__(self, "generation_planner_mode", mode.value)
        return self
```

- [ ] **Step 5: Run generation tests to verify GREEN**

Run:

```powershell
python -m pytest tests/test_generation_executor.py tests/test_configuration_section_loaders.py tests/test_generation_prompt_contract.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit generation planner mode change**

Run:

```powershell
git add rag_modules/generation/models.py rag_modules/generation/planner.py rag_modules/generation/__init__.py rag_modules/configuration/model_sections/generation.py tests/test_generation_executor.py tests/test_configuration_section_loaders.py tests/test_generation_prompt_contract.py
git commit -m "refactor: type generation planner modes"
```

## Task 5: Integration Verification and Public Surface Check

**Files:**
- Read/verify: all modified files from Tasks 1-4
- Optional modify: only tests whose expectations need string-vs-enum adjustment

- [ ] **Step 1: Run narrow combined tests**

Run:

```powershell
python -m pytest tests/test_build_pipeline_manifest_lifecycle.py tests/test_query_semantics.py tests/test_retrieval_candidate_generator.py tests/test_hybrid_search_service.py tests/test_generation_executor.py tests/test_configuration_section_loaders.py -q
```

Expected: PASS.

- [ ] **Step 2: Run related runtime/API contract tests**

Run:

```powershell
python -m pytest tests/test_runtime_type_contracts.py tests/test_runtime_workflow_models.py tests/test_answer_response_mapping.py tests/test_api_app.py -q
```

Expected: PASS. If failures come from internal enum objects leaking into public DTOs, fix the
`to_dict()`/mapping boundary to emit `.value`, then rerun.

- [ ] **Step 3: Run public surface guard tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Expected: PASS. No new public modules should be exposed except enum names through already-public
packages where needed by tests.

- [ ] **Step 4: Run formatting/linting**

Run:

```powershell
pre-commit run --all-files
```

Expected: PASS. If Ruff modifies files, inspect `git diff` and rerun relevant tests.

- [ ] **Step 5: Final status check**

Run:

```powershell
git status --short
git diff --stat
```

Expected: only intentional implementation/test files are modified.

- [ ] **Step 6: Commit final test expectation cleanup if needed**

If Task 5 required follow-up fixes in the related runtime/API contract tests, run:

```powershell
git add tests/test_runtime_type_contracts.py tests/test_runtime_workflow_models.py tests/test_answer_response_mapping.py tests/test_api_app.py
git commit -m "test: verify strategy enum convergence"
```

If Task 5 changed a different already-listed file from Tasks 1-4, add that exact file instead of
the command above. If no files changed after the task commits, skip this commit.

## Self-Review

- Spec coverage: Artifact stage is Task 1, route strategy and query planner mode are Task 2,
  candidate-source degradation strategy is Task 3, generation planner mode is Task 4, and
  compatibility/integration checks are Task 5.
- Placeholder scan: No placeholder markers are present. The optional final cleanup commit is
  conditional on Task 5 producing follow-up edits and names the expected test files explicitly.
- Type consistency: `ArtifactStage`, `SearchStrategy`, `CandidateSourceDegradationStrategy`,
  `GenerationPlannerMode`, and `QueryPlannerMode` are consistently named across tests and
  implementation steps.
