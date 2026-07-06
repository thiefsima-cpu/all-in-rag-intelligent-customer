"""Models environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

MODELS_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec(
        ("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY"), ("models", "api_key"), "str"
    ),
    _spec("LLM_BASE_URL", ("models", "llm_base_url"), "str"),
    _spec("EMBEDDING_BASE_URL", ("models", "embedding_base_url"), "str"),
    _spec("RERANK_BASE_URL", ("models", "rerank_base_url"), "str"),
    _spec("EMBEDDING_MODEL", ("models", "embedding_model"), "str"),
    _spec("LLM_MODEL", ("models", "llm_model"), "str"),
    _spec("RERANK_MODEL", ("models", "rerank_model"), "str"),
    _spec("EMBEDDING_DIMENSION", ("models", "embedding_dimension"), "int"),
    _spec("EMBEDDING_BATCH_SIZE", ("models", "embedding_batch_size"), "int"),
    _spec("ENABLE_RERANK", ("models", "enable_rerank"), "bool"),
    _spec("LLM_TIMEOUT_SECONDS", ("models", "llm_timeout_seconds"), "int"),
    _spec("EMBEDDING_TIMEOUT_SECONDS", ("models", "embedding_timeout_seconds"), "int"),
    _spec("RERANK_TIMEOUT_SECONDS", ("models", "rerank_timeout_seconds"), "int"),
    _spec("HTTP_POOL_CONNECTIONS", ("models", "http_pool_connections"), "int"),
    _spec("HTTP_POOL_MAXSIZE", ("models", "http_pool_maxsize"), "int"),
    _spec(
        "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
        ("models", "circuit_breaker_failure_threshold"),
        "int",
    ),
    _spec(
        "CIRCUIT_BREAKER_RECOVERY_SECONDS",
        ("models", "circuit_breaker_recovery_seconds"),
        "float",
    ),
    _spec(
        "LLM_INPUT_COST_PER_MILLION_TOKENS",
        ("models", "llm_input_cost_per_million_tokens"),
        "float",
    ),
    _spec(
        "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
        ("models", "llm_output_cost_per_million_tokens"),
        "float",
    ),
)


__all__ = ["MODELS_ENV_FIELD_SPECS"]
