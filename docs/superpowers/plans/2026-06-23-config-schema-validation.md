# Config Schema Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace scattered dataclass and section-loader configuration validation with one authoritative Pydantic schema and precise profile/env/override errors.

**Architecture:** `models.py` becomes the single schema authority. `env.py` converts supported environment variables into a nested override payload, `assembly.py` performs source-order merges and Pydantic validation, `loader.py` only orchestrates precedence and metadata, and `errors.py` exposes configuration-specific diagnostics.

**Tech Stack:** Python 3.11, Pydantic v2, TOML via `tomllib`, pytest, Ruff.

---

## File Structure

- Create `rag_modules/configuration/errors.py`
  - Owns `ConfigErrorDetail` and `ConfigurationError`.
- Create `rag_modules/configuration/validation.py`
  - Converts Pydantic `ValidationError` and parser failures into `ConfigurationError`.
- Modify `rag_modules/configuration/models.py`
  - Replace dataclass config classes with Pydantic `BaseModel` classes.
  - Keep public class names and methods: `to_dict`, `to_domain_dict`, `with_overrides`, `from_dict`.
- Modify `rag_modules/configuration/env.py`
  - Keep `EnvConfigSource`.
  - Add explicit env var to dotted-field mapping and strict parsers.
  - Stop using silent fallback for malformed values.
- Modify `rag_modules/configuration/assembly.py`
  - Make override merging schema-driven instead of manually rejecting unknown fields.
  - Build configs through `GraphRAGConfig.model_validate`.
- Modify `rag_modules/configuration/profiles.py`
  - Validate each TOML payload against the Pydantic schema before merging.
- Modify `rag_modules/configuration/loader.py`
  - Stop using section loaders for the primary config path.
  - Apply defaults, profile, env, and explicit overrides once, then validate once.
- Modify `rag_modules/configuration/sections/common.py`
  - Add a thin schema-backed section loader helper.
- Modify `rag_modules/configuration/sections/*.py`
  - Replace field-by-field casts with thin wrappers over the schema-backed helper.
- Modify `rag_modules/configuration/query_understanding_loader.py`
  - Replace field-by-field casts with a thin wrapper over the schema-backed helper.
- Modify `rag_modules/configuration/__init__.py`
  - Export `ConfigurationError`.
- Modify tests:
  - `tests/test_configuration_profiles.py`
  - `tests/test_configuration_section_loaders.py`
  - `tests/test_configuration_defaults.py`
  - `tests/test_query_understanding_config.py` if query-understanding env behavior needs a direct regression.

---

### Task 1: Add Failing Diagnostics Tests

**Files:**
- Modify: `tests/test_configuration_section_loaders.py`
- Modify: `tests/test_configuration_profiles.py`
- Modify: `tests/test_configuration_defaults.py`

- [ ] **Step 1: Add env diagnostics tests**

Add these imports to `tests/test_configuration_section_loaders.py`:

```python
from rag_modules.configuration import ConfigurationError
```

Add this helper near the top of `ConfigurationSectionLoaderTests`:

```python
    def assertConfigErrorMentions(
        self,
        error: ConfigurationError,
        *expected_fragments: str,
    ) -> None:
        message = str(error)
        for fragment in expected_fragments:
            self.assertIn(fragment, message)
```

Add these tests to `ConfigurationSectionLoaderTests`:

```python
    def test_invalid_environment_int_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(source=EnvConfigSource(environ={"TOP_K": "many"}))

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "TOP_K",
            "retrieval.top_k",
            "integer",
        )

    def test_invalid_environment_bool_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(source=EnvConfigSource(environ={"API_AUTH_ENABLED": "sometimes"}))

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "API_AUTH_ENABLED",
            "api.auth_enabled",
            "boolean",
        )

    def test_invalid_environment_json_reports_variable_and_field_path(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            load_config(
                source=EnvConfigSource(
                    environ={"ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES": "not-json"}
                )
            )

        self.assertConfigErrorMentions(
            context.exception,
            "environment",
            "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
            "graph.entity_linker_query_type_label_priorities",
            "JSON object",
        )
```

- [ ] **Step 2: Add profile diagnostics tests**

Add this import to `tests/test_configuration_profiles.py`:

```python
from rag_modules.configuration import ConfigurationError
```

Add this helper to `ConfigurationProfilesTests`:

```python
    def assertConfigErrorMentions(
        self,
        error: ConfigurationError,
        *expected_fragments: str,
    ) -> None:
        message = str(error)
        for fragment in expected_fragments:
            self.assertIn(fragment, message)
```

Add these tests to `ConfigurationProfilesTests`:

```python
    def test_profile_unknown_nested_field_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "bad.toml"
            profile_path.write_text("[retrieval]\ntopkk = 4\n", encoding="utf-8")

            with self.assertRaises(ConfigurationError) as context:
                load_config(
                    source=EnvConfigSource(environ={}),
                    profile_path=str(profile_path),
                    profiles_dir=tmpdir,
                )

        self.assertConfigErrorMentions(
            context.exception,
            "profile",
            str(profile_path.resolve()),
            "retrieval.topkk",
            "extra",
        )

    def test_profile_wrong_scalar_type_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "bad.toml"
            profile_path.write_text('[retrieval]\ntop_k = "fast"\n', encoding="utf-8")

            with self.assertRaises(ConfigurationError) as context:
                load_config(
                    source=EnvConfigSource(environ={}),
                    profile_path=str(profile_path),
                    profiles_dir=tmpdir,
                )

        self.assertConfigErrorMentions(
            context.exception,
            "profile",
            str(profile_path.resolve()),
            "retrieval.top_k",
            "integer",
        )

    def test_profile_scalar_for_nested_section_reports_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = Path(tmpdir) / "bad.toml"
            profile_path.write_text('[query_understanding]\nplanner = "fast"\n', encoding="utf-8")

            with self.assertRaises(ConfigurationError) as context:
                load_config(
                    source=EnvConfigSource(environ={}),
                    profile_path=str(profile_path),
                    profiles_dir=tmpdir,
                )

        self.assertConfigErrorMentions(
            context.exception,
            "profile",
            str(profile_path.resolve()),
            "query_understanding.planner",
            "dictionary",
        )
```

- [ ] **Step 3: Add cross-field diagnostics test**

Add this import to `tests/test_configuration_defaults.py`:

```python
from rag_modules.configuration import ConfigurationError
```

Add this test to `ConfigurationDefaultTests`:

```python
    def test_dimension_mismatch_reports_both_field_paths(self) -> None:
        with self.assertRaises(ConfigurationError) as context:
            GraphRAGConfig.from_dict(
                {
                    "storage": {"milvus_dimension": 512},
                    "models": {"embedding_dimension": 1024},
                }
            )

        message = str(context.exception)
        self.assertIn("storage.milvus_dimension", message)
        self.assertIn("models.embedding_dimension", message)
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because `ConfigurationError` is not exported and invalid env/profile values do not yet raise the new diagnostics.

- [ ] **Step 5: Commit the failing tests**

```powershell
git add tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py
git commit -m "test: capture precise configuration validation errors"
```

---

### Task 2: Add Configuration Error Types

**Files:**
- Create: `rag_modules/configuration/errors.py`
- Create: `rag_modules/configuration/validation.py`
- Modify: `rag_modules/configuration/__init__.py`

- [ ] **Step 1: Create the error model**

Create `rag_modules/configuration/errors.py`:

```python
"""Configuration-specific validation diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ConfigErrorDetail:
    source_kind: str
    source: str
    path: str
    message: str

    def format(self) -> str:
        source_text = f"{self.source_kind} {self.source}".strip()
        path_text = self.path or "<root>"
        return f"{source_text}: {path_text}: {self.message}"


class ConfigurationError(ValueError):
    """Raised when profile, environment, or override configuration is invalid."""

    def __init__(self, details: Iterable[ConfigErrorDetail] | str) -> None:
        if isinstance(details, str):
            self.details: tuple[ConfigErrorDetail, ...] = ()
            super().__init__(details)
            return
        self.details = tuple(details)
        message = "Invalid configuration"
        if self.details:
            message = "Invalid configuration: " + "; ".join(
                detail.format() for detail in self.details
            )
        super().__init__(message)


__all__ = ["ConfigErrorDetail", "ConfigurationError"]
```

- [ ] **Step 2: Create validation formatting helpers**

Create `rag_modules/configuration/validation.py`:

```python
"""Helpers for turning schema/parser failures into configuration diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from .errors import ConfigErrorDetail, ConfigurationError


def dotted_path(location: Iterable[Any]) -> str:
    return ".".join(str(part) for part in location if str(part))


def normalize_reason(message: str) -> str:
    lowered = message.lower()
    if "valid integer" in lowered or "int_type" in lowered:
        return "expected integer"
    if "valid number" in lowered or "float_type" in lowered:
        return "expected number"
    if "valid boolean" in lowered or "bool_type" in lowered:
        return "expected boolean"
    if "valid dictionary" in lowered or "model_type" in lowered:
        return "expected dictionary"
    if "extra inputs" in lowered:
        return "extra field is not allowed"
    return message


def raise_validation_error(
    exc: ValidationError,
    *,
    source_kind: str,
    source: str,
) -> None:
    details = [
        ConfigErrorDetail(
            source_kind=source_kind,
            source=source,
            path=dotted_path(error.get("loc", ())),
            message=normalize_reason(str(error.get("msg", ""))),
        )
        for error in exc.errors()
    ]
    raise ConfigurationError(details) from exc


def raise_parser_error(
    *,
    source_kind: str,
    source: str,
    path: str,
    message: str,
) -> None:
    raise ConfigurationError(
        [
            ConfigErrorDetail(
                source_kind=source_kind,
                source=source,
                path=path,
                message=message,
            )
        ]
    )


__all__ = [
    "dotted_path",
    "normalize_reason",
    "raise_parser_error",
    "raise_validation_error",
]
```

- [ ] **Step 3: Export the new error type**

Modify `rag_modules/configuration/__init__.py`:

```python
from .errors import ConfigErrorDetail, ConfigurationError
```

Add both names to `__all__`:

```python
    "ConfigErrorDetail",
    "ConfigurationError",
```

- [ ] **Step 4: Run tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py -q
```

Expected: FAIL because the old dataclass/loader path still raises old errors or silently accepts malformed env JSON.

- [ ] **Step 5: Commit**

```powershell
git add rag_modules/configuration/errors.py rag_modules/configuration/validation.py rag_modules/configuration/__init__.py
git commit -m "feat: add configuration validation diagnostics"
```

---

### Task 3: Convert Config Models To Pydantic Schema

**Files:**
- Modify: `rag_modules/configuration/models.py`

- [ ] **Step 1: Replace dataclass imports and section base**

In `rag_modules/configuration/models.py`, remove dataclass imports and add Pydantic imports:

```python
import os
from typing import Any, Dict, List, Mapping, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rag_modules.query_policy import get_query_policy
from rag_modules.query_understanding.registry import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)

from .validation import raise_validation_error
```

Replace `ConfigSection` with:

```python
class ConfigSection(BaseModel):
    """Serializable section base."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="python")
```

- [ ] **Step 2: Add query policy default helpers**

Add these helpers above the query setting models:

```python
_QUERY_POLICY = get_query_policy()
_PLANNER_DEFAULTS = _QUERY_POLICY.runtime_section("planner")
_SEMANTIC_DEFAULTS = _QUERY_POLICY.runtime_section("semantics")


def _planner_default(name: str, fallback: Any) -> Any:
    return _PLANNER_DEFAULTS.get(name, fallback)


def _semantic_default(name: str, fallback: Any) -> Any:
    return _SEMANTIC_DEFAULTS.get(name, fallback)
```

- [ ] **Step 3: Convert section classes to Pydantic models with defaults**

Replace the dataclass section definitions with Pydantic classes that declare the same public fields and these defaults:

```python
class StorageSettings(ConfigSection):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = Field(default="password", repr=False)
    neo4j_database: str = "neo4j"
    milvus_host: str = "localhost"
    milvus_port: int = 19530
    milvus_collection_name: str = "cooking_knowledge"
    milvus_dimension: int = 1024
    enable_index_cache: bool = True
    index_cache_dir: str = "storage/indexes"
    artifact_manifest_path: str = ""
    milvus_blue_green_enabled: bool = True
    milvus_collection_alias_suffix: str = "__active"
    build_job_store_path: str = ""
    neo4j_max_connection_pool_size: int = Field(default=50, ge=1)
    neo4j_connection_acquisition_timeout_seconds: float = 30.0
    neo4j_max_connection_lifetime_seconds: float = 3600.0
    neo4j_connection_timeout_seconds: float = 15.0


class ModelSettings(ConfigSection):
    api_key: str = Field(default="", repr=False)
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/embeddings/"
        "multimodal-embedding/multimodal-embedding"
    )
    rerank_base_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    embedding_model: str = "qwen3-vl-embedding"
    llm_model: str = "qwen3.7-plus"
    rerank_model: str = "qwen3-vl-rerank"
    embedding_dimension: int = 1024
    embedding_batch_size: int = 10
    enable_rerank: bool = True
    llm_timeout_seconds: int = 20
    embedding_timeout_seconds: int = 60
    rerank_timeout_seconds: int = 20
    http_pool_connections: int = Field(default=10, ge=1)
    http_pool_maxsize: int = Field(default=20, ge=1)
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1)
    circuit_breaker_recovery_seconds: float = 30.0
    llm_input_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)
    llm_output_cost_per_million_tokens: float = Field(default=0.0, ge=0.0)


class RetrievalSettings(ConfigSection):
    top_k: int = 5
    vector_search_ef: int = 128
    vector_search_max_k: int = 50
    rrf_k: int = 60
    hybrid_default_candidate_multiplier: int = 2
    hybrid_default_candidate_min_candidates: int = 10
    hybrid_constraint_candidate_multiplier: int = 6
    hybrid_constraint_candidate_min_candidates: int = 30
    router_combined_candidate_multiplier: int = 6
    router_combined_candidate_min_candidates: int = 30
    router_graph_supplement_candidate_multiplier: int = 2
    router_graph_supplement_candidate_min_candidates: int = 10
    retrieval_preserve_graph_evidence: bool = True
    enable_parent_doc_retrieval: bool = True
    parent_doc_top_n: int = 3
    parent_doc_max_chars: int = 4000
    candidate_source_failure_threshold: int = Field(default=1, ge=1)
    candidate_source_recovery_seconds: float = Field(default=30.0, ge=0.1)
    candidate_source_degradation_strategy: str = "continue"

    @model_validator(mode="after")
    def normalize_strategy(self) -> Self:
        self.candidate_source_degradation_strategy = (
            self.candidate_source_degradation_strategy.strip().lower() or "continue"
        )
        return self
```

Convert the query-understanding models with defaults from `get_query_policy()`:

```python
class QueryPlannerSettings(ConfigSection):
    cache_size: int = Field(default_factory=lambda: int(_planner_default("cache_size", 128)))
    fast_rule_planning: bool = Field(
        default_factory=lambda: bool(_planner_default("fast_rule_planning", True))
    )
    llm_temperature: float = Field(
        default_factory=lambda: float(_planner_default("llm_temperature", 0.0))
    )
    llm_max_tokens: int = Field(
        default_factory=lambda: int(_planner_default("llm_max_tokens", 1200))
    )


class QuerySemanticScoringSettings(ConfigSection):
    relation_intensity_reference_ratio: float = Field(
        default_factory=lambda: float(
            _semantic_default("relation_intensity_reference_ratio", 0.5)
        )
    )
    complexity_relation_hit_weight: float = Field(
        default_factory=lambda: float(_semantic_default("complexity_relation_hit_weight", 0.14))
    )
    complexity_constraint_hit_weight: float = Field(
        default_factory=lambda: float(_semantic_default("complexity_constraint_hit_weight", 0.1))
    )
    complexity_structural_hit_weight: float = Field(
        default_factory=lambda: float(_semantic_default("complexity_structural_hit_weight", 0.12))
    )
    complexity_length_weight: float = Field(
        default_factory=lambda: float(_semantic_default("complexity_length_weight", 0.28))
    )
    complexity_length_norm_chars: int = Field(
        default_factory=lambda: int(_semantic_default("complexity_length_norm_chars", 140))
    )
    reasoning_complexity_threshold: float = Field(
        default_factory=lambda: float(_semantic_default("reasoning_complexity_threshold", 0.7))
    )
    reasoning_relationship_threshold: float = Field(
        default_factory=lambda: float(_semantic_default("reasoning_relationship_threshold", 0.4))
    )
    relation_hit_intensity_boost_base: float = Field(
        default_factory=lambda: float(_semantic_default("relation_hit_intensity_boost_base", 0.45))
    )
    relation_hit_intensity_boost_step: float = Field(
        default_factory=lambda: float(_semantic_default("relation_hit_intensity_boost_step", 0.12))
    )
    relation_hit_complexity_boost_base: float = Field(
        default_factory=lambda: float(_semantic_default("relation_hit_complexity_boost_base", 0.55))
    )
    relation_hit_complexity_boost_step: float = Field(
        default_factory=lambda: float(_semantic_default("relation_hit_complexity_boost_step", 0.08))
    )
```

Add these remaining section classes with explicit defaults:

```python
class QuerySemanticExtractionSettings(ConfigSection):
    source_entity_limit: int = Field(
        default_factory=lambda: int(_semantic_default("source_entity_limit", 3))
    )
    entity_keyword_limit: int = Field(
        default_factory=lambda: int(_semantic_default("entity_keyword_limit", 4))
    )
    semantic_profile_entity_keyword_limit: int = Field(
        default_factory=lambda: int(
            _semantic_default("semantic_profile_entity_keyword_limit", 6)
        )
    )
    topic_keyword_limit: int = Field(
        default_factory=lambda: int(_semantic_default("topic_keyword_limit", 4))
    )
    semantic_profile_topic_keyword_start: int = Field(
        default_factory=lambda: int(
            _semantic_default("semantic_profile_topic_keyword_start", 4)
        )
    )
    semantic_profile_topic_keyword_limit: int = Field(
        default_factory=lambda: int(
            _semantic_default("semantic_profile_topic_keyword_limit", 6)
        )
    )
    target_entity_limit: int = Field(
        default_factory=lambda: int(_semantic_default("target_entity_limit", 2))
    )


class QuerySemanticRoutingSettings(ConfigSection):
    high_relationship_routing_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("high_relationship_routing_threshold", 0.7)
        )
    )
    multi_hop_hint_entity_count: int = Field(
        default_factory=lambda: int(_semantic_default("multi_hop_hint_entity_count", 2))
    )
    multi_hop_hint_relationship_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("multi_hop_hint_relationship_threshold", 0.55)
        )
    )
    combined_strategy_relationship_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("combined_strategy_relationship_threshold", 0.4)
        )
    )
    combined_strategy_complexity_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("combined_strategy_complexity_threshold", 0.6)
        )
    )
    source_entity_seed_relationship_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("source_entity_seed_relationship_threshold", 0.4)
        )
    )
    source_entity_backfill_relationship_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("source_entity_backfill_relationship_threshold", 0.55)
        )
    )
    rule_fallback_confidence: float = Field(
        default_factory=lambda: float(_semantic_default("rule_fallback_confidence", 0.45))
    )


class QuerySemanticTraversalSettings(ConfigSection):
    entity_relation_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("entity_relation_max_depth", 1))
    )
    path_finding_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("path_finding_max_depth", 3))
    )
    path_finding_high_intensity_max_depth: int = Field(
        default_factory=lambda: int(
            _semantic_default("path_finding_high_intensity_max_depth", 4)
        )
    )
    path_finding_high_intensity_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("path_finding_high_intensity_threshold", 0.6)
        )
    )
    subgraph_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("subgraph_max_depth", 2))
    )
    subgraph_high_intensity_max_depth: int = Field(
        default_factory=lambda: int(
            _semantic_default("subgraph_high_intensity_max_depth", 3)
        )
    )
    subgraph_high_intensity_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("subgraph_high_intensity_threshold", 0.5)
        )
    )
    clustering_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("clustering_max_depth", 3))
    )
    default_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("default_max_depth", 2))
    )
    default_high_intensity_max_depth: int = Field(
        default_factory=lambda: int(
            _semantic_default("default_high_intensity_max_depth", 3)
        )
    )
    default_high_intensity_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("default_high_intensity_threshold", 0.7)
        )
    )
    entity_relation_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("entity_relation_max_nodes", 20))
    )
    path_finding_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("path_finding_max_nodes", 40))
    )
    subgraph_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("subgraph_max_nodes", 80))
    )
    clustering_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("clustering_max_nodes", 60))
    )
    default_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("default_max_nodes", 50))
    )
    graph_query_max_depth_cap: int = Field(
        default_factory=lambda: int(_semantic_default("graph_query_max_depth_cap", 4))
    )
    graph_query_fallback_name_chars: int = Field(
        default_factory=lambda: int(_semantic_default("graph_query_fallback_name_chars", 16))
    )


class QuerySemanticAdaptiveTraversalSettings(ConfigSection):
    multi_hop_subgraph_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("adaptive_multi_hop_subgraph_threshold", 0.7)
        )
    )
    subgraph_multi_hop_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("adaptive_subgraph_multi_hop_threshold", 0.45)
        )
    )
    entity_relation_multi_hop_threshold: float = Field(
        default_factory=lambda: float(
            _semantic_default("adaptive_entity_relation_multi_hop_threshold", 0.5)
        )
    )
    subgraph_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_subgraph_max_depth", 3))
    )
    subgraph_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_subgraph_max_nodes", 100))
    )
    multi_hop_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_multi_hop_max_depth", 3))
    )
    multi_hop_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_multi_hop_max_nodes", 50))
    )
    entity_relation_max_depth: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_entity_relation_max_depth", 2))
    )
    entity_relation_max_nodes: int = Field(
        default_factory=lambda: int(_semantic_default("adaptive_entity_relation_max_nodes", 40))
    )


class GenerationSettings(ConfigSection):
    temperature: float = 0.1
    max_tokens: int = 2048
    generation_timeout_seconds: int = 25
    generation_stream_timeout_seconds: int = 25
    generation_latency_budget_seconds: int = 24
    generation_plan_max_tokens: int = 600
    generation_compose_max_tokens: int = 1100
    generation_direct_max_tokens: int = 700
    generation_plan_temperature: float = 0.0
    generation_planner_mode: str = "rule"
    generation_max_retries: int = 1
    generation_request_retries: int = 1
    generation_stream_retries: int = 1
    generation_evidence_max_chars: int = 700
    generation_enable_two_stage: bool = True
    generation_two_stage_complexity_threshold: float = 0.68
    generation_two_stage_relationship_threshold: float = 0.58
    generation_direct_max_evidence_items: int = 2
    generation_two_stage_max_evidence_items: int = 3
    generation_plan_max_evidence_items: int = 2
    generation_max_graph_paths_per_item: int = 1
    generation_max_evidence_units_per_item: int = 4
    generation_include_document_evidence: bool = False
    generation_compose_include_content: bool = False
    generation_fallback_on_timeout: bool = False


class GraphSettings(ConfigSection):
    enable_semantic_graph_schema: bool = True
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_graph_depth: int = 2
    graph_rank_base_weight: float = 1.0
    graph_rank_semantic_relation_weight: float = 0.08
    graph_rank_evidence_unit_weight: float = 0.03
    graph_rank_relationship_weight: float = 0.01
    graph_rank_recipe_presence_weight: float = 0.1
    graph_rank_query_overlap_weight: float = 0.02
    entity_linker_limit_per_entity: int = 4
    entity_linker_min_confidence: float = 0.45
    entity_linker_max_same_name_candidates: int = 2
    entity_linker_query_type_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_query_type_priorities
    )
    entity_linker_relation_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_relation_priorities
    )


class ObservabilitySettings(ConfigSection):
    enable_query_tracing: bool = True
    query_trace_path: str = "storage/traces/query_trace.jsonl"
    query_trace_async_enabled: bool = True
    query_trace_max_queue_size: int = 256
    query_trace_fingerprint_salt: str = Field(default="", repr=False)
    enable_opentelemetry: bool = False
    otel_service_name: str = "graphrag"
    otel_exporter_otlp_endpoint: str = ""
    otel_trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    enable_prometheus: bool = True
    prometheus_public: bool = False


class ApiSettings(ConfigSection):
    auth_enabled: bool = True
    access_token: str = Field(default="", repr=False)
    docs_enabled: bool = False
    openapi_enabled: bool = False
    docs_public: bool = False
    openapi_public: bool = False
    max_request_body_bytes: int = Field(default=16 * 1024, ge=1024)
    max_concurrent_answers: int = Field(default=0, ge=0)
    answer_acquire_timeout_seconds: float = Field(default=0.25, ge=0.0)
    stream_executor_max_workers: int = Field(default=4, ge=1)
    stream_queue_max_size: int = Field(default=64, ge=1)
    serving_hot_refresh_enabled: bool = True
    serving_hot_refresh_interval_seconds: float = Field(default=2.0, ge=0.1)
```

- [ ] **Step 4: Convert nested `from_dict` methods**

Replace dataclass construction in nested `from_dict` methods with Pydantic validation:

```python
class QuerySemanticSettings(ConfigSection):
    scoring: QuerySemanticScoringSettings = Field(default_factory=QuerySemanticScoringSettings)
    extraction: QuerySemanticExtractionSettings = Field(
        default_factory=QuerySemanticExtractionSettings
    )
    routing: QuerySemanticRoutingSettings = Field(default_factory=QuerySemanticRoutingSettings)
    traversal: QuerySemanticTraversalSettings = Field(
        default_factory=QuerySemanticTraversalSettings
    )
    adaptive_traversal: QuerySemanticAdaptiveTraversalSettings = Field(
        default_factory=QuerySemanticAdaptiveTraversalSettings
    )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QuerySemanticSettings":
        return cls.model_validate(dict(data or {}))


class QueryUnderstandingSettings(ConfigSection):
    planner: QueryPlannerSettings = Field(default_factory=QueryPlannerSettings)
    semantics: QuerySemanticSettings = Field(default_factory=QuerySemanticSettings)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QueryUnderstandingSettings":
        return cls.model_validate(dict(data or {}))
```

- [ ] **Step 5: Convert `GraphRAGConfig` root model**

Replace the dataclass `GraphRAGConfig` with:

```python
class GraphRAGConfig(BaseModel):
    """Root configuration with true nested domain sections."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    storage: StorageSettings = Field(default_factory=StorageSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    query_understanding: QueryUnderstandingSettings = Field(
        default_factory=QueryUnderstandingSettings
    )
    generation: GenerationSettings = Field(default_factory=GenerationSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    profile_name: str = ""
    profile_path: str = ""
    profile_hash: str = ""

    @model_validator(mode="after")
    def apply_root_rules(self) -> Self:
        configured_milvus_dimension = int(self.storage.milvus_dimension or 0)
        embedding_dimension = int(self.models.embedding_dimension)
        if configured_milvus_dimension and configured_milvus_dimension != embedding_dimension:
            raise ValueError(
                "storage.milvus_dimension must match models.embedding_dimension so the vector "
                "store schema matches the active embedding model."
            )
        self.storage.milvus_dimension = embedding_dimension
        if not self.storage.artifact_manifest_path:
            self.storage.artifact_manifest_path = os.path.join(
                self.storage.index_cache_dir,
                "artifact_manifest.json",
            )
        if not self.storage.build_job_store_path:
            self.storage.build_job_store_path = os.path.join(
                os.path.dirname(self.storage.artifact_manifest_path),
                "build_jobs.json",
            )
        return self

    def to_domain_dict(self) -> Dict[str, Dict[str, Any]]:
        return {
            section_name: getattr(self, section_name).model_dump(mode="python")
            for section_name in SECTION_ORDER
        }

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = self.to_domain_dict()
        if self.profile_name:
            payload["profile_name"] = self.profile_name
        if self.profile_path:
            payload["profile_path"] = self.profile_path
        if self.profile_hash:
            payload["profile_hash"] = self.profile_hash
        if payload["models"].get("api_key"):
            payload["models"]["api_key"] = "***"
        if payload["storage"].get("neo4j_password"):
            payload["storage"]["neo4j_password"] = "***"
        if payload["api"].get("access_token"):
            payload["api"]["access_token"] = "***"
        if payload["observability"].get("query_trace_fingerprint_salt"):
            payload["observability"]["query_trace_fingerprint_salt"] = "***"
        return payload

    def with_overrides(self, overrides: Mapping[str, Any]) -> "GraphRAGConfig":
        from .assembly import apply_overrides, build_config_from_domain_dict

        merged = self.to_domain_dict()
        apply_overrides(merged, overrides)
        config = build_config_from_domain_dict(
            merged,
            source_kind="overrides",
            source="GraphRAGConfig.with_overrides",
        )
        config.profile_name = self.profile_name
        config.profile_path = self.profile_path
        config.profile_hash = self.profile_hash
        return config

    @classmethod
    def from_dict(cls, config_dict: Mapping[str, Any]) -> "GraphRAGConfig":
        if isinstance(config_dict, cls):
            return config_dict
        from .assembly import apply_overrides, build_config_from_domain_dict

        merged = cls().to_domain_dict()
        apply_overrides(merged, config_dict)
        return build_config_from_domain_dict(
            merged,
            source_kind="overrides",
            source="GraphRAGConfig.from_dict",
        )
```

- [ ] **Step 6: Keep section metadata constants**

Replace `dataclass_fields` usage with Pydantic field metadata:

```python
SECTION_TYPES = {
    "storage": StorageSettings,
    "models": ModelSettings,
    "retrieval": RetrievalSettings,
    "query_understanding": QueryUnderstandingSettings,
    "generation": GenerationSettings,
    "graph": GraphSettings,
    "observability": ObservabilitySettings,
    "api": ApiSettings,
}
SECTION_ORDER = tuple(SECTION_TYPES.keys())
SECTION_FIELD_NAMES = {
    section_name: tuple(section_type.model_fields)
    for section_name, section_type in SECTION_TYPES.items()
}
```

- [ ] **Step 7: Run the narrow tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py -q
```

Expected: FAIL only on loader/env/profile tests that still use old section loaders. Default construction and `GraphRAGConfig.from_dict` should be close to passing after this task.

- [ ] **Step 8: Commit**

```powershell
git add rag_modules/configuration/models.py
git commit -m "feat: make configuration models schema-driven"
```

---

### Task 4: Add Strict Environment Override Parsing

**Files:**
- Modify: `rag_modules/configuration/env.py`

- [ ] **Step 1: Replace env conversion helpers with explicit mapping**

Keep `EnvConfigSource.environ` and `get_first`. Add these types and helpers to `env.py`:

```python
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping

from .validation import raise_parser_error

EnvValueKind = Literal["str", "int", "float", "bool", "json_dict"]


@dataclass(frozen=True, slots=True)
class EnvFieldSpec:
    names: tuple[str, ...]
    path: tuple[str, ...]
    value_kind: EnvValueKind

    @property
    def dotted_path(self) -> str:
        return ".".join(self.path)
```

Update `EnvConfigSource`:

```python
@dataclass(slots=True)
class EnvConfigSource:
    """Typed access helpers over environment variables."""

    environ: Mapping[str, str | None]

    def get_first(self, *names: str) -> str | None:
        match = self.get_first_with_name(*names)
        if match is None:
            return None
        return match[1]

    def get_first_with_name(self, *names: str) -> tuple[str, str] | None:
        for name in names:
            value = self.environ.get(name)
            if value not in (None, ""):
                return name, str(value)
        return None
```

- [ ] **Step 2: Define env mappings**

Add `ENV_FIELD_SPECS` with every supported runtime env var:

```python
ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    EnvFieldSpec(("NEO4J_URI",), ("storage", "neo4j_uri"), "str"),
    EnvFieldSpec(("NEO4J_USER",), ("storage", "neo4j_user"), "str"),
    EnvFieldSpec(("NEO4J_PASSWORD",), ("storage", "neo4j_password"), "str"),
    EnvFieldSpec(("NEO4J_DATABASE",), ("storage", "neo4j_database"), "str"),
    EnvFieldSpec(("MILVUS_HOST",), ("storage", "milvus_host"), "str"),
    EnvFieldSpec(("MILVUS_PORT",), ("storage", "milvus_port"), "int"),
    EnvFieldSpec(("MILVUS_COLLECTION_NAME",), ("storage", "milvus_collection_name"), "str"),
    EnvFieldSpec(("MILVUS_DIMENSION",), ("storage", "milvus_dimension"), "int"),
    EnvFieldSpec(("ENABLE_INDEX_CACHE",), ("storage", "enable_index_cache"), "bool"),
    EnvFieldSpec(("INDEX_CACHE_DIR",), ("storage", "index_cache_dir"), "str"),
    EnvFieldSpec(("ARTIFACT_MANIFEST_PATH",), ("storage", "artifact_manifest_path"), "str"),
    EnvFieldSpec(("MILVUS_BLUE_GREEN_ENABLED",), ("storage", "milvus_blue_green_enabled"), "bool"),
    EnvFieldSpec(
        ("MILVUS_COLLECTION_ALIAS_SUFFIX",),
        ("storage", "milvus_collection_alias_suffix"),
        "str",
    ),
    EnvFieldSpec(("BUILD_JOB_STORE_PATH",), ("storage", "build_job_store_path"), "str"),
    EnvFieldSpec(
        ("NEO4J_MAX_CONNECTION_POOL_SIZE",),
        ("storage", "neo4j_max_connection_pool_size"),
        "int",
    ),
    EnvFieldSpec(
        ("NEO4J_CONNECTION_ACQUISITION_TIMEOUT_SECONDS",),
        ("storage", "neo4j_connection_acquisition_timeout_seconds"),
        "float",
    ),
    EnvFieldSpec(
        ("NEO4J_MAX_CONNECTION_LIFETIME_SECONDS",),
        ("storage", "neo4j_max_connection_lifetime_seconds"),
        "float",
    ),
    EnvFieldSpec(
        ("NEO4J_CONNECTION_TIMEOUT_SECONDS",),
        ("storage", "neo4j_connection_timeout_seconds"),
        "float",
    ),
    EnvFieldSpec(
        ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"),
        ("models", "api_key"),
        "str",
    ),
    EnvFieldSpec(("LLM_BASE_URL",), ("models", "llm_base_url"), "str"),
    EnvFieldSpec(("EMBEDDING_BASE_URL",), ("models", "embedding_base_url"), "str"),
    EnvFieldSpec(("RERANK_BASE_URL",), ("models", "rerank_base_url"), "str"),
    EnvFieldSpec(("EMBEDDING_MODEL",), ("models", "embedding_model"), "str"),
    EnvFieldSpec(("LLM_MODEL",), ("models", "llm_model"), "str"),
    EnvFieldSpec(("RERANK_MODEL",), ("models", "rerank_model"), "str"),
    EnvFieldSpec(("EMBEDDING_DIMENSION",), ("models", "embedding_dimension"), "int"),
    EnvFieldSpec(("EMBEDDING_BATCH_SIZE",), ("models", "embedding_batch_size"), "int"),
    EnvFieldSpec(("ENABLE_RERANK",), ("models", "enable_rerank"), "bool"),
    EnvFieldSpec(("LLM_TIMEOUT_SECONDS",), ("models", "llm_timeout_seconds"), "int"),
    EnvFieldSpec(("EMBEDDING_TIMEOUT_SECONDS",), ("models", "embedding_timeout_seconds"), "int"),
    EnvFieldSpec(("RERANK_TIMEOUT_SECONDS",), ("models", "rerank_timeout_seconds"), "int"),
    EnvFieldSpec(("HTTP_POOL_CONNECTIONS",), ("models", "http_pool_connections"), "int"),
    EnvFieldSpec(("HTTP_POOL_MAXSIZE",), ("models", "http_pool_maxsize"), "int"),
    EnvFieldSpec(
        ("CIRCUIT_BREAKER_FAILURE_THRESHOLD",),
        ("models", "circuit_breaker_failure_threshold"),
        "int",
    ),
    EnvFieldSpec(
        ("CIRCUIT_BREAKER_RECOVERY_SECONDS",),
        ("models", "circuit_breaker_recovery_seconds"),
        "float",
    ),
    EnvFieldSpec(
        ("LLM_INPUT_COST_PER_MILLION_TOKENS",),
        ("models", "llm_input_cost_per_million_tokens"),
        "float",
    ),
    EnvFieldSpec(
        ("LLM_OUTPUT_COST_PER_MILLION_TOKENS",),
        ("models", "llm_output_cost_per_million_tokens"),
        "float",
    ),
    EnvFieldSpec(("TOP_K",), ("retrieval", "top_k"), "int"),
    EnvFieldSpec(("VECTOR_SEARCH_EF",), ("retrieval", "vector_search_ef"), "int"),
    EnvFieldSpec(("VECTOR_SEARCH_MAX_K",), ("retrieval", "vector_search_max_k"), "int"),
    EnvFieldSpec(("RRF_K",), ("retrieval", "rrf_k"), "int"),
    EnvFieldSpec(
        ("HYBRID_DEFAULT_CANDIDATE_MULTIPLIER",),
        ("retrieval", "hybrid_default_candidate_multiplier"),
        "int",
    ),
    EnvFieldSpec(
        ("HYBRID_DEFAULT_CANDIDATE_MIN_CANDIDATES",),
        ("retrieval", "hybrid_default_candidate_min_candidates"),
        "int",
    ),
    EnvFieldSpec(
        ("HYBRID_CONSTRAINT_CANDIDATE_MULTIPLIER",),
        ("retrieval", "hybrid_constraint_candidate_multiplier"),
        "int",
    ),
    EnvFieldSpec(
        ("HYBRID_CONSTRAINT_CANDIDATE_MIN_CANDIDATES",),
        ("retrieval", "hybrid_constraint_candidate_min_candidates"),
        "int",
    ),
    EnvFieldSpec(
        ("ROUTER_COMBINED_CANDIDATE_MULTIPLIER",),
        ("retrieval", "router_combined_candidate_multiplier"),
        "int",
    ),
    EnvFieldSpec(
        ("ROUTER_COMBINED_CANDIDATE_MIN_CANDIDATES",),
        ("retrieval", "router_combined_candidate_min_candidates"),
        "int",
    ),
    EnvFieldSpec(
        ("ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MULTIPLIER",),
        ("retrieval", "router_graph_supplement_candidate_multiplier"),
        "int",
    ),
    EnvFieldSpec(
        ("ROUTER_GRAPH_SUPPLEMENT_CANDIDATE_MIN_CANDIDATES",),
        ("retrieval", "router_graph_supplement_candidate_min_candidates"),
        "int",
    ),
    EnvFieldSpec(
        ("RETRIEVAL_PRESERVE_GRAPH_EVIDENCE",),
        ("retrieval", "retrieval_preserve_graph_evidence"),
        "bool",
    ),
    EnvFieldSpec(
        ("ENABLE_PARENT_DOC_RETRIEVAL",),
        ("retrieval", "enable_parent_doc_retrieval"),
        "bool",
    ),
    EnvFieldSpec(("PARENT_DOC_TOP_N",), ("retrieval", "parent_doc_top_n"), "int"),
    EnvFieldSpec(("PARENT_DOC_MAX_CHARS",), ("retrieval", "parent_doc_max_chars"), "int"),
    EnvFieldSpec(
        ("RETRIEVAL_CANDIDATE_SOURCE_FAILURE_THRESHOLD",),
        ("retrieval", "candidate_source_failure_threshold"),
        "int",
    ),
    EnvFieldSpec(
        ("RETRIEVAL_CANDIDATE_SOURCE_RECOVERY_SECONDS",),
        ("retrieval", "candidate_source_recovery_seconds"),
        "float",
    ),
    EnvFieldSpec(
        ("RETRIEVAL_CANDIDATE_SOURCE_DEGRADATION_STRATEGY",),
        ("retrieval", "candidate_source_degradation_strategy"),
        "str",
    ),
    EnvFieldSpec(("QUERY_PLAN_CACHE_SIZE",), ("query_understanding", "planner", "cache_size"), "int"),
    EnvFieldSpec(
        ("FAST_RULE_QUERY_PLANNING",),
        ("query_understanding", "planner", "fast_rule_planning"),
        "bool",
    ),
    EnvFieldSpec(
        ("QUERY_PLANNER_LLM_TEMPERATURE",),
        ("query_understanding", "planner", "llm_temperature"),
        "float",
    ),
    EnvFieldSpec(
        ("QUERY_PLANNER_LLM_MAX_TOKENS",),
        ("query_understanding", "planner", "llm_max_tokens"),
        "int",
    ),
    EnvFieldSpec(("TEMPERATURE",), ("generation", "temperature"), "float"),
    EnvFieldSpec(("MAX_TOKENS",), ("generation", "max_tokens"), "int"),
    EnvFieldSpec(
        ("GENERATION_TIMEOUT_SECONDS",),
        ("generation", "generation_timeout_seconds"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_STREAM_TIMEOUT_SECONDS",),
        ("generation", "generation_stream_timeout_seconds"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_LATENCY_BUDGET_SECONDS",),
        ("generation", "generation_latency_budget_seconds"),
        "int",
    ),
    EnvFieldSpec(("GENERATION_PLAN_MAX_TOKENS",), ("generation", "generation_plan_max_tokens"), "int"),
    EnvFieldSpec(
        ("GENERATION_COMPOSE_MAX_TOKENS",),
        ("generation", "generation_compose_max_tokens"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_DIRECT_MAX_TOKENS",),
        ("generation", "generation_direct_max_tokens"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_PLAN_TEMPERATURE",),
        ("generation", "generation_plan_temperature"),
        "float",
    ),
    EnvFieldSpec(("GENERATION_PLANNER_MODE",), ("generation", "generation_planner_mode"), "str"),
    EnvFieldSpec(("GENERATION_MAX_RETRIES",), ("generation", "generation_max_retries"), "int"),
    EnvFieldSpec(
        ("GENERATION_REQUEST_RETRIES",),
        ("generation", "generation_request_retries"),
        "int",
    ),
    EnvFieldSpec(("GENERATION_STREAM_RETRIES",), ("generation", "generation_stream_retries"), "int"),
    EnvFieldSpec(
        ("GENERATION_EVIDENCE_MAX_CHARS",),
        ("generation", "generation_evidence_max_chars"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_ENABLE_TWO_STAGE",),
        ("generation", "generation_enable_two_stage"),
        "bool",
    ),
    EnvFieldSpec(
        ("GENERATION_TWO_STAGE_COMPLEXITY_THRESHOLD",),
        ("generation", "generation_two_stage_complexity_threshold"),
        "float",
    ),
    EnvFieldSpec(
        ("GENERATION_TWO_STAGE_RELATIONSHIP_THRESHOLD",),
        ("generation", "generation_two_stage_relationship_threshold"),
        "float",
    ),
    EnvFieldSpec(
        ("GENERATION_DIRECT_MAX_EVIDENCE_ITEMS",),
        ("generation", "generation_direct_max_evidence_items"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_TWO_STAGE_MAX_EVIDENCE_ITEMS",),
        ("generation", "generation_two_stage_max_evidence_items"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_PLAN_MAX_EVIDENCE_ITEMS",),
        ("generation", "generation_plan_max_evidence_items"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_MAX_GRAPH_PATHS_PER_ITEM",),
        ("generation", "generation_max_graph_paths_per_item"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_MAX_EVIDENCE_UNITS_PER_ITEM",),
        ("generation", "generation_max_evidence_units_per_item"),
        "int",
    ),
    EnvFieldSpec(
        ("GENERATION_INCLUDE_DOCUMENT_EVIDENCE",),
        ("generation", "generation_include_document_evidence"),
        "bool",
    ),
    EnvFieldSpec(
        ("GENERATION_COMPOSE_INCLUDE_CONTENT",),
        ("generation", "generation_compose_include_content"),
        "bool",
    ),
    EnvFieldSpec(
        ("GENERATION_FALLBACK_ON_TIMEOUT",),
        ("generation", "generation_fallback_on_timeout"),
        "bool",
    ),
    EnvFieldSpec(
        ("ENABLE_SEMANTIC_GRAPH_SCHEMA",),
        ("graph", "enable_semantic_graph_schema"),
        "bool",
    ),
    EnvFieldSpec(("CHUNK_SIZE",), ("graph", "chunk_size"), "int"),
    EnvFieldSpec(("CHUNK_OVERLAP",), ("graph", "chunk_overlap"), "int"),
    EnvFieldSpec(("MAX_GRAPH_DEPTH",), ("graph", "max_graph_depth"), "int"),
    EnvFieldSpec(("GRAPH_RANK_BASE_WEIGHT",), ("graph", "graph_rank_base_weight"), "float"),
    EnvFieldSpec(
        ("GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",),
        ("graph", "graph_rank_semantic_relation_weight"),
        "float",
    ),
    EnvFieldSpec(
        ("GRAPH_RANK_EVIDENCE_UNIT_WEIGHT",),
        ("graph", "graph_rank_evidence_unit_weight"),
        "float",
    ),
    EnvFieldSpec(
        ("GRAPH_RANK_RELATIONSHIP_WEIGHT",),
        ("graph", "graph_rank_relationship_weight"),
        "float",
    ),
    EnvFieldSpec(
        ("GRAPH_RANK_RECIPE_PRESENCE_WEIGHT",),
        ("graph", "graph_rank_recipe_presence_weight"),
        "float",
    ),
    EnvFieldSpec(
        ("GRAPH_RANK_QUERY_OVERLAP_WEIGHT",),
        ("graph", "graph_rank_query_overlap_weight"),
        "float",
    ),
    EnvFieldSpec(
        ("ENTITY_LINKER_LIMIT_PER_ENTITY",),
        ("graph", "entity_linker_limit_per_entity"),
        "int",
    ),
    EnvFieldSpec(
        ("ENTITY_LINKER_MIN_CONFIDENCE",),
        ("graph", "entity_linker_min_confidence"),
        "float",
    ),
    EnvFieldSpec(
        ("ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",),
        ("graph", "entity_linker_max_same_name_candidates"),
        "int",
    ),
    EnvFieldSpec(
        ("ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",),
        ("graph", "entity_linker_query_type_label_priorities"),
        "json_dict",
    ),
    EnvFieldSpec(
        ("ENTITY_LINKER_RELATION_LABEL_PRIORITIES",),
        ("graph", "entity_linker_relation_label_priorities"),
        "json_dict",
    ),
    EnvFieldSpec(("ENABLE_QUERY_TRACING",), ("observability", "enable_query_tracing"), "bool"),
    EnvFieldSpec(("QUERY_TRACE_PATH",), ("observability", "query_trace_path"), "str"),
    EnvFieldSpec(
        ("QUERY_TRACE_ASYNC_ENABLED",),
        ("observability", "query_trace_async_enabled"),
        "bool",
    ),
    EnvFieldSpec(
        ("QUERY_TRACE_MAX_QUEUE_SIZE",),
        ("observability", "query_trace_max_queue_size"),
        "int",
    ),
    EnvFieldSpec(
        ("QUERY_TRACE_FINGERPRINT_SALT",),
        ("observability", "query_trace_fingerprint_salt"),
        "str",
    ),
    EnvFieldSpec(("ENABLE_OPENTELEMETRY",), ("observability", "enable_opentelemetry"), "bool"),
    EnvFieldSpec(("OTEL_SERVICE_NAME",), ("observability", "otel_service_name"), "str"),
    EnvFieldSpec(
        ("OTEL_EXPORTER_OTLP_ENDPOINT",),
        ("observability", "otel_exporter_otlp_endpoint"),
        "str",
    ),
    EnvFieldSpec(("OTEL_TRACE_SAMPLE_RATIO",), ("observability", "otel_trace_sample_ratio"), "float"),
    EnvFieldSpec(("ENABLE_PROMETHEUS",), ("observability", "enable_prometheus"), "bool"),
    EnvFieldSpec(("PROMETHEUS_METRICS_PUBLIC",), ("observability", "prometheus_public"), "bool"),
    EnvFieldSpec(("API_AUTH_ENABLED",), ("api", "auth_enabled"), "bool"),
    EnvFieldSpec(("API_ACCESS_TOKEN", "GRAPH_RAG_API_TOKEN"), ("api", "access_token"), "str"),
    EnvFieldSpec(("API_DOCS_ENABLED",), ("api", "docs_enabled"), "bool"),
    EnvFieldSpec(("API_OPENAPI_ENABLED",), ("api", "openapi_enabled"), "bool"),
    EnvFieldSpec(("API_DOCS_PUBLIC",), ("api", "docs_public"), "bool"),
    EnvFieldSpec(("API_OPENAPI_PUBLIC",), ("api", "openapi_public"), "bool"),
    EnvFieldSpec(("API_MAX_REQUEST_BODY_BYTES",), ("api", "max_request_body_bytes"), "int"),
    EnvFieldSpec(("API_MAX_CONCURRENT_ANSWERS",), ("api", "max_concurrent_answers"), "int"),
    EnvFieldSpec(
        ("API_ANSWER_ACQUIRE_TIMEOUT_SECONDS",),
        ("api", "answer_acquire_timeout_seconds"),
        "float",
    ),
    EnvFieldSpec(("API_STREAM_EXECUTOR_MAX_WORKERS",), ("api", "stream_executor_max_workers"), "int"),
    EnvFieldSpec(("API_STREAM_QUEUE_MAX_SIZE",), ("api", "stream_queue_max_size"), "int"),
    EnvFieldSpec(
        ("SERVING_HOT_REFRESH_ENABLED",),
        ("api", "serving_hot_refresh_enabled"),
        "bool",
    ),
    EnvFieldSpec(
        ("SERVING_HOT_REFRESH_INTERVAL_SECONDS",),
        ("api", "serving_hot_refresh_interval_seconds"),
        "float",
    ),
)
```

Place these query semantic entries in `ENV_FIELD_SPECS` after the planner entries and before the generation entries:

```python
EnvFieldSpec(
    ("QUERY_SEMANTIC_RELATION_INTENSITY_REFERENCE_RATIO",),
    ("query_understanding", "semantics", "scoring", "relation_intensity_reference_ratio"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMPLEXITY_RELATION_HIT_WEIGHT",),
    ("query_understanding", "semantics", "scoring", "complexity_relation_hit_weight"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMPLEXITY_CONSTRAINT_HIT_WEIGHT",),
    ("query_understanding", "semantics", "scoring", "complexity_constraint_hit_weight"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMPLEXITY_STRUCTURAL_HIT_WEIGHT",),
    ("query_understanding", "semantics", "scoring", "complexity_structural_hit_weight"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMPLEXITY_LENGTH_WEIGHT",),
    ("query_understanding", "semantics", "scoring", "complexity_length_weight"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMPLEXITY_LENGTH_NORM_CHARS",),
    ("query_understanding", "semantics", "scoring", "complexity_length_norm_chars"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_REASONING_COMPLEXITY_THRESHOLD",),
    ("query_understanding", "semantics", "scoring", "reasoning_complexity_threshold"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_REASONING_RELATIONSHIP_THRESHOLD",),
    ("query_understanding", "semantics", "scoring", "reasoning_relationship_threshold"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_BASE",),
    ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_base"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_RELATION_HIT_INTENSITY_BOOST_STEP",),
    ("query_understanding", "semantics", "scoring", "relation_hit_intensity_boost_step"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_BASE",),
    ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_base"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_RELATION_HIT_COMPLEXITY_BOOST_STEP",),
    ("query_understanding", "semantics", "scoring", "relation_hit_complexity_boost_step"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SOURCE_ENTITY_LIMIT",),
    ("query_understanding", "semantics", "extraction", "source_entity_limit"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ENTITY_KEYWORD_LIMIT",),
    ("query_understanding", "semantics", "extraction", "entity_keyword_limit"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PROFILE_ENTITY_KEYWORD_LIMIT",),
    (
        "query_understanding",
        "semantics",
        "extraction",
        "semantic_profile_entity_keyword_limit",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_TOPIC_KEYWORD_LIMIT",),
    ("query_understanding", "semantics", "extraction", "topic_keyword_limit"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_START",),
    (
        "query_understanding",
        "semantics",
        "extraction",
        "semantic_profile_topic_keyword_start",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PROFILE_TOPIC_KEYWORD_LIMIT",),
    (
        "query_understanding",
        "semantics",
        "extraction",
        "semantic_profile_topic_keyword_limit",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_TARGET_ENTITY_LIMIT",),
    ("query_understanding", "semantics", "extraction", "target_entity_limit"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_HIGH_RELATIONSHIP_ROUTING_THRESHOLD",),
    ("query_understanding", "semantics", "routing", "high_relationship_routing_threshold"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_MULTI_HOP_HINT_ENTITY_COUNT",),
    ("query_understanding", "semantics", "routing", "multi_hop_hint_entity_count"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_MULTI_HOP_HINT_RELATIONSHIP_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "routing",
        "multi_hop_hint_relationship_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMBINED_STRATEGY_RELATIONSHIP_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "routing",
        "combined_strategy_relationship_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_COMBINED_STRATEGY_COMPLEXITY_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "routing",
        "combined_strategy_complexity_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SOURCE_ENTITY_SEED_RELATIONSHIP_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "routing",
        "source_entity_seed_relationship_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SOURCE_ENTITY_BACKFILL_RELATIONSHIP_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "routing",
        "source_entity_backfill_relationship_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_RULE_FALLBACK_CONFIDENCE",),
    ("query_understanding", "semantics", "routing", "rule_fallback_confidence"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ENTITY_RELATION_MAX_DEPTH",),
    ("query_understanding", "semantics", "traversal", "entity_relation_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PATH_FINDING_MAX_DEPTH",),
    ("query_understanding", "semantics", "traversal", "path_finding_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_MAX_DEPTH",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "path_finding_high_intensity_max_depth",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PATH_FINDING_HIGH_INTENSITY_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "path_finding_high_intensity_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SUBGRAPH_MAX_DEPTH",),
    ("query_understanding", "semantics", "traversal", "subgraph_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_MAX_DEPTH",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "subgraph_high_intensity_max_depth",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SUBGRAPH_HIGH_INTENSITY_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "subgraph_high_intensity_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_CLUSTERING_MAX_DEPTH",),
    ("query_understanding", "semantics", "traversal", "clustering_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_DEFAULT_MAX_DEPTH",),
    ("query_understanding", "semantics", "traversal", "default_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_MAX_DEPTH",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "default_high_intensity_max_depth",
    ),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_DEFAULT_HIGH_INTENSITY_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "traversal",
        "default_high_intensity_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ENTITY_RELATION_MAX_NODES",),
    ("query_understanding", "semantics", "traversal", "entity_relation_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_PATH_FINDING_MAX_NODES",),
    ("query_understanding", "semantics", "traversal", "path_finding_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_SUBGRAPH_MAX_NODES",),
    ("query_understanding", "semantics", "traversal", "subgraph_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_CLUSTERING_MAX_NODES",),
    ("query_understanding", "semantics", "traversal", "clustering_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_DEFAULT_MAX_NODES",),
    ("query_understanding", "semantics", "traversal", "default_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_GRAPH_QUERY_MAX_DEPTH_CAP",),
    ("query_understanding", "semantics", "traversal", "graph_query_max_depth_cap"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_GRAPH_QUERY_FALLBACK_NAME_CHARS",),
    ("query_understanding", "semantics", "traversal", "graph_query_fallback_name_chars"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_SUBGRAPH_THRESHOLD",),
    ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_subgraph_threshold"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MULTI_HOP_THRESHOLD",),
    ("query_understanding", "semantics", "adaptive_traversal", "subgraph_multi_hop_threshold"),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MULTI_HOP_THRESHOLD",),
    (
        "query_understanding",
        "semantics",
        "adaptive_traversal",
        "entity_relation_multi_hop_threshold",
    ),
    "float",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_DEPTH",),
    ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_SUBGRAPH_MAX_NODES",),
    ("query_understanding", "semantics", "adaptive_traversal", "subgraph_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_DEPTH",),
    ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_MULTI_HOP_MAX_NODES",),
    ("query_understanding", "semantics", "adaptive_traversal", "multi_hop_max_nodes"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_DEPTH",),
    ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_depth"),
    "int",
),
EnvFieldSpec(
    ("QUERY_SEMANTIC_ADAPTIVE_ENTITY_RELATION_MAX_NODES",),
    ("query_understanding", "semantics", "adaptive_traversal", "entity_relation_max_nodes"),
    "int",
),
```

- [ ] **Step 3: Add strict parsers**

Add:

```python
TRUE_VALUES = {"1", "true", "yes", "y", "on"}
FALSE_VALUES = {"0", "false", "no", "n", "off"}


def _parse_bool(raw: str, *, env_name: str, path: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise_parser_error(
        source_kind="environment",
        source=env_name,
        path=path,
        message="expected boolean",
    )


def _parse_json_dict(raw: str, *, env_name: str, path: str) -> Dict[str, list[str]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise_parser_error(
            source_kind="environment",
            source=env_name,
            path=path,
            message="expected JSON object",
        )
        raise AssertionError("unreachable") from exc
    if not isinstance(parsed, dict):
        raise_parser_error(
            source_kind="environment",
            source=env_name,
            path=path,
            message="expected JSON object",
        )
    normalized: Dict[str, list[str]] = {}
    for key, items in parsed.items():
        if not isinstance(key, str) or not isinstance(items, list):
            raise_parser_error(
                source_kind="environment",
                source=env_name,
                path=path,
                message="expected JSON object with string keys and string-list values",
            )
        normalized_items: list[str] = []
        for item in items:
            if not isinstance(item, str):
                raise_parser_error(
                    source_kind="environment",
                    source=env_name,
                    path=path,
                    message="expected JSON object with string-list values",
                )
            stripped = item.strip()
            if stripped:
                normalized_items.append(stripped)
        normalized[key] = normalized_items
    return normalized
```

Add `_parse_value`:

```python
def _parse_value(spec: EnvFieldSpec, env_name: str, raw: str) -> Any:
    path = spec.dotted_path
    if spec.value_kind == "str":
        return raw
    if spec.value_kind == "int":
        try:
            return int(raw)
        except ValueError as exc:
            raise_parser_error(
                source_kind="environment",
                source=env_name,
                path=path,
                message="expected integer",
            )
            raise AssertionError("unreachable") from exc
    if spec.value_kind == "float":
        try:
            return float(raw)
        except ValueError as exc:
            raise_parser_error(
                source_kind="environment",
                source=env_name,
                path=path,
                message="expected number",
            )
            raise AssertionError("unreachable") from exc
    if spec.value_kind == "bool":
        return _parse_bool(raw, env_name=env_name, path=path)
    if spec.value_kind == "json_dict":
        return _parse_json_dict(raw, env_name=env_name, path=path)
    raise AssertionError(f"Unsupported environment value kind: {spec.value_kind}")
```

- [ ] **Step 4: Add nested payload builder**

Add:

```python
def _assign_path(payload: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = payload
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def build_env_overrides(source: EnvConfigSource) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for spec in ENV_FIELD_SPECS:
        match = source.get_first_with_name(*spec.names)
        if match is None:
            continue
        env_name, raw = match
        _assign_path(payload, spec.path, _parse_value(spec, env_name, raw))
    return payload
```

Keep:

```python
def default_env_source() -> EnvConfigSource:
    return EnvConfigSource(environ=os.environ)
```

Export:

```python
__all__ = ["EnvConfigSource", "EnvFieldSpec", "build_env_overrides", "default_env_source"]
```

- [ ] **Step 5: Run env diagnostics tests**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_invalid_environment_int_reports_variable_and_field_path tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_invalid_environment_bool_reports_variable_and_field_path tests/test_configuration_section_loaders.py::ConfigurationSectionLoaderTests::test_invalid_environment_json_reports_variable_and_field_path -q
```

Expected: FAIL until `loader.py` uses `build_env_overrides`.

- [ ] **Step 6: Commit**

```powershell
git add rag_modules/configuration/env.py
git commit -m "feat: parse configuration environment overrides strictly"
```

---

### Task 5: Replace Assembly And Loader Pipeline

**Files:**
- Modify: `rag_modules/configuration/assembly.py`
- Modify: `rag_modules/configuration/loader.py`

- [ ] **Step 1: Make override merge preserve unknowns for schema validation**

Replace `apply_overrides` internals in `assembly.py` with:

```python
def _merge_nested_mapping(target: Dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        current = target.get(key_text)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge_nested_mapping(current, value)
        else:
            target[key_text] = dict(value) if isinstance(value, Mapping) else value


def apply_overrides(
    domain_payload: Dict[str, Any],
    overrides: Mapping[str, Any],
) -> None:
    _merge_nested_mapping(domain_payload, overrides)
```

Replace `build_config_from_domain_dict` with:

```python
def build_config_from_domain_dict(
    domain_payload: Mapping[str, Any],
    *,
    source_kind: str = "configuration",
    source: str = "",
) -> GraphRAGConfig:
    try:
        return GraphRAGConfig.model_validate(dict(domain_payload))
    except ValidationError as exc:
        raise_validation_error(exc, source_kind=source_kind, source=source)
        raise AssertionError("unreachable") from exc
```

Update imports:

```python
from pydantic import ValidationError

from .models import GraphRAGConfig
from .validation import raise_validation_error
```

- [ ] **Step 2: Simplify loader to one pipeline**

Replace `_load_domain_payload` in `loader.py` with:

```python
def _default_domain_payload() -> dict[str, dict[str, Any]]:
    return GraphRAGConfig().to_domain_dict()
```

Update imports:

```python
from .env import EnvConfigSource, build_env_overrides, default_env_source
```

Remove imports from `.query_understanding_loader` and `.section_loaders`.

Replace the middle of `load_config` after env source resolution with:

```python
    domain_payload = _default_domain_payload()
    resolved_profile = load_profile(
        profile=profile or env_source.get_first("GRAPH_RAG_PROFILE", "CONFIG_PROFILE"),
        profile_path=profile_path
        or env_source.get_first(
            "GRAPH_RAG_PROFILE_PATH",
            "CONFIG_PROFILE_PATH",
        ),
        profiles_dir=profiles_dir
        or env_source.get_first(
            "GRAPH_RAG_PROFILES_DIR",
            "CONFIG_PROFILES_DIR",
        ),
    )
    if resolved_profile.overrides:
        apply_overrides(domain_payload, resolved_profile.overrides)

    env_overrides = build_env_overrides(env_source)
    if env_overrides:
        apply_overrides(domain_payload, env_overrides)

    if overrides:
        apply_overrides(domain_payload, overrides)

    config = build_config_from_domain_dict(
        domain_payload,
        source_kind="configuration",
        source=resolved_profile.path or "runtime",
    )
    config.profile_name = resolved_profile.name
    config.profile_path = resolved_profile.path
    config.profile_hash = resolved_profile.profile_hash
    return config
```

- [ ] **Step 3: Run the env override tests**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py -q
```

Expected: env override tests pass or fail with only missing semantic env mappings. If semantic mappings are missing, add the exact missing `QUERY_SEMANTIC_*` specs to `ENV_FIELD_SPECS` before continuing.

- [ ] **Step 4: Run defaults tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py -q
```

Expected: default config tests pass. The dimension mismatch test should raise `ConfigurationError`.

- [ ] **Step 5: Commit**

```powershell
git add rag_modules/configuration/assembly.py rag_modules/configuration/loader.py
git commit -m "feat: load configuration through unified schema pipeline"
```

---

### Task 6: Validate Profile Files At Read Time

**Files:**
- Modify: `rag_modules/configuration/profiles.py`

- [ ] **Step 1: Add profile payload validation**

In `profiles.py`, add imports:

```python
from pydantic import ValidationError

from .assembly import apply_overrides
from .models import GraphRAGConfig
from .validation import raise_validation_error
```

Add:

```python
def _validate_profile_payload(path: Path, payload: Mapping[str, Any]) -> None:
    merged = GraphRAGConfig().to_domain_dict()
    apply_overrides(merged, payload)
    try:
        GraphRAGConfig.model_validate(merged)
    except ValidationError as exc:
        raise_validation_error(exc, source_kind="profile", source=str(path))
```

Update `_read_profile_file`:

```python
def _read_profile_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        payload = tomllib.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Profile at {path} must decode to a TOML table.")
    result = dict(payload)
    _validate_profile_payload(path, result)
    return result
```

- [ ] **Step 2: Run profile diagnostics tests**

Run:

```powershell
python -m pytest tests/test_configuration_profiles.py -q
```

Expected: profile tests pass. If Pydantic reports root-level model validator errors at an empty path for dimension mismatch, update `GraphRAGConfig.apply_root_rules` to include both field paths in the ValueError text.

- [ ] **Step 3: Commit**

```powershell
git add rag_modules/configuration/profiles.py
git commit -m "feat: validate configuration profiles during load"
```

---

### Task 7: Retire Section Loader Casting

**Files:**
- Modify: `rag_modules/configuration/sections/common.py`
- Modify: `rag_modules/configuration/sections/storage.py`
- Modify: `rag_modules/configuration/sections/models.py`
- Modify: `rag_modules/configuration/sections/retrieval.py`
- Modify: `rag_modules/configuration/sections/generation.py`
- Modify: `rag_modules/configuration/sections/graph.py`
- Modify: `rag_modules/configuration/sections/observability.py`
- Modify: `rag_modules/configuration/sections/api.py`
- Modify: `rag_modules/configuration/query_understanding_loader.py`

- [ ] **Step 1: Add schema-backed section helper**

Replace `sections/common.py` with:

```python
"""Shared helpers for schema-backed configuration section loaders."""

from __future__ import annotations

from typing import Any, Mapping

from ..assembly import apply_overrides, build_config_from_domain_dict
from ..env import EnvConfigSource, build_env_overrides
from ..models import GraphRAGConfig


def load_section_from_schema(
    section_name: str,
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
):
    payload = GraphRAGConfig().to_domain_dict()
    if defaults:
        apply_overrides(payload, {section_name: dict(defaults)})
    env_overrides = build_env_overrides(source)
    if env_overrides:
        apply_overrides(payload, env_overrides)
    config = build_config_from_domain_dict(
        payload,
        source_kind="environment",
        source=section_name,
    )
    return getattr(config, section_name)


__all__ = ["load_section_from_schema"]
```

- [ ] **Step 2: Replace each section loader with a thin wrapper**

For `storage.py`:

```python
"""Storage configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import StorageSettings
from .common import load_section_from_schema


def load_storage_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> StorageSettings:
    return load_section_from_schema("storage", source, defaults)


__all__ = ["load_storage_settings"]
```

Replace `models.py` with:

```python
"""Model provider configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ModelSettings
from .common import load_section_from_schema


def load_model_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ModelSettings:
    return load_section_from_schema("models", source, defaults)


__all__ = ["load_model_settings"]
```

Replace `retrieval.py` with:

```python
"""Retrieval configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import RetrievalSettings
from .common import load_section_from_schema


def load_retrieval_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> RetrievalSettings:
    return load_section_from_schema("retrieval", source, defaults)


__all__ = ["load_retrieval_settings"]
```

Replace `generation.py` with:

```python
"""Generation configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import GenerationSettings
from .common import load_section_from_schema


def load_generation_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GenerationSettings:
    return load_section_from_schema("generation", source, defaults)


__all__ = ["load_generation_settings"]
```

Replace `graph.py` with:

```python
"""Graph configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import GraphSettings
from .common import load_section_from_schema


def load_graph_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GraphSettings:
    return load_section_from_schema("graph", source, defaults)


__all__ = ["load_graph_settings"]
```

Replace `observability.py` with:

```python
"""Observability configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ObservabilitySettings
from .common import load_section_from_schema


def load_observability_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ObservabilitySettings:
    return load_section_from_schema("observability", source, defaults)


__all__ = ["load_observability_settings"]
```

Replace `api.py` with:

```python
"""API configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ApiSettings
from .common import load_section_from_schema


def load_api_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ApiSettings:
    return load_section_from_schema("api", source, defaults)


__all__ = ["load_api_settings"]
```

- [ ] **Step 3: Replace query-understanding loader**

Replace `query_understanding_loader.py` with:

```python
"""Dedicated loader for query-understanding configuration sections."""

from __future__ import annotations

from typing import Any, Mapping

from .env import EnvConfigSource
from .models import QueryUnderstandingSettings
from .sections.common import load_section_from_schema


def load_query_understanding_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QueryUnderstandingSettings:
    return load_section_from_schema("query_understanding", source, defaults)


__all__ = ["load_query_understanding_settings"]
```

- [ ] **Step 4: Run section loader tests**

Run:

```powershell
python -m pytest tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py -q
```

Expected: pass. If query-understanding env tests fail, add the missing env specs to `ENV_FIELD_SPECS`.

- [ ] **Step 5: Commit**

```powershell
git add rag_modules/configuration/sections rag_modules/configuration/query_understanding_loader.py
git commit -m "refactor: route section loaders through config schema"
```

---

### Task 8: Preserve Public Boundary And Metadata Behavior

**Files:**
- Modify: `rag_modules/configuration/models.py`
- Modify: `rag_modules/configuration/__init__.py`
- Modify tests only if current expectations need stricter error assertions.

- [ ] **Step 1: Run focused compatibility tests**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py -q
```

Expected: pass.

- [ ] **Step 2: Fix any compatibility breaks with targeted code**

If callers expect `to_dict` masking, keep the existing masking code in `GraphRAGConfig.to_dict`.

If callers expect profile metadata preservation, keep this code in `with_overrides`:

```python
        config.profile_name = self.profile_name
        config.profile_path = self.profile_path
        config.profile_hash = self.profile_hash
```

If callers expect `GraphRAGConfig.from_dict` to ignore ambient environment, keep this base:

```python
        merged = cls().to_domain_dict()
```

- [ ] **Step 3: Run public boundary tests**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py tests/test_entrypoints.py -q
```

Expected: pass.

- [ ] **Step 4: Commit**

```powershell
git add rag_modules/configuration tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py
git commit -m "test: preserve configuration public boundary"
```

---

### Task 9: Final Verification

**Files:**
- No planned code edits.

- [ ] **Step 1: Run narrow configuration suite**

Run:

```powershell
python -m pytest tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py -q
```

Expected: pass.

- [ ] **Step 2: Run boundary and entrypoint suite**

Run:

```powershell
python -m pytest tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py tests/test_entrypoints.py -q
```

Expected: pass.

- [ ] **Step 3: Run formatting/lint check**

Run:

```powershell
pre-commit run --all-files
```

Expected: pass. If Ruff modifies files, inspect `git diff`, rerun the focused tests from Steps 1 and 2, and commit the formatting changes.

- [ ] **Step 4: Run release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: pass.

- [ ] **Step 5: Inspect final diff**

Run:

```powershell
git status --short
git diff --stat HEAD
```

Expected: only intended configuration schema, validation, loader, and test files are changed.

- [ ] **Step 6: Final commit if needed**

If any verified changes remain unstaged after hooks:

```powershell
git add rag_modules/configuration tests/test_configuration_defaults.py tests/test_configuration_profiles.py tests/test_configuration_section_loaders.py tests/test_query_understanding_config.py
git commit -m "chore: finalize configuration schema validation"
```
