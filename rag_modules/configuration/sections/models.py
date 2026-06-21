"""Model provider configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ModelSettings
from .common import mapping_defaults


def load_model_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ModelSettings:
    model_defaults = mapping_defaults(defaults)
    api_key = source.get_first("DASHSCOPE_API_KEY", "OPENAI_API_KEY", "MOONSHOT_API_KEY") or str(
        model_defaults.get("api_key", "")
    )
    return ModelSettings(
        api_key=api_key,
        llm_base_url=source.get_str(
            "LLM_BASE_URL",
            str(
                model_defaults.get(
                    "llm_base_url",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
            ),
        ),
        embedding_base_url=source.get_str(
            "EMBEDDING_BASE_URL",
            str(
                model_defaults.get(
                    "embedding_base_url",
                    "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                )
            ),
        ),
        rerank_base_url=source.get_str(
            "RERANK_BASE_URL",
            str(
                model_defaults.get(
                    "rerank_base_url",
                    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
                )
            ),
        ),
        embedding_model=source.get_str(
            "EMBEDDING_MODEL",
            str(model_defaults.get("embedding_model", "qwen3-vl-embedding")),
        ),
        llm_model=source.get_str("LLM_MODEL", str(model_defaults.get("llm_model", "qwen3.7-plus"))),
        rerank_model=source.get_str(
            "RERANK_MODEL",
            str(model_defaults.get("rerank_model", "qwen3-vl-rerank")),
        ),
        embedding_dimension=source.get_int(
            "EMBEDDING_DIMENSION",
            int(model_defaults.get("embedding_dimension", 1024)),
        ),
        embedding_batch_size=source.get_int(
            "EMBEDDING_BATCH_SIZE",
            int(model_defaults.get("embedding_batch_size", 10)),
        ),
        enable_rerank=source.get_bool(
            "ENABLE_RERANK",
            bool(model_defaults.get("enable_rerank", True)),
        ),
        llm_timeout_seconds=source.get_int(
            "LLM_TIMEOUT_SECONDS",
            int(model_defaults.get("llm_timeout_seconds", 20)),
        ),
        embedding_timeout_seconds=source.get_int(
            "EMBEDDING_TIMEOUT_SECONDS",
            int(model_defaults.get("embedding_timeout_seconds", 60)),
        ),
        rerank_timeout_seconds=source.get_int(
            "RERANK_TIMEOUT_SECONDS",
            int(model_defaults.get("rerank_timeout_seconds", 20)),
        ),
        http_pool_connections=max(
            1,
            source.get_int(
                "HTTP_POOL_CONNECTIONS",
                int(model_defaults.get("http_pool_connections", 10)),
            ),
        ),
        http_pool_maxsize=max(
            1,
            source.get_int(
                "HTTP_POOL_MAXSIZE",
                int(model_defaults.get("http_pool_maxsize", 20)),
            ),
        ),
        circuit_breaker_failure_threshold=max(
            1,
            source.get_int(
                "CIRCUIT_BREAKER_FAILURE_THRESHOLD",
                int(model_defaults.get("circuit_breaker_failure_threshold", 5)),
            ),
        ),
        circuit_breaker_recovery_seconds=source.get_float(
            "CIRCUIT_BREAKER_RECOVERY_SECONDS",
            float(model_defaults.get("circuit_breaker_recovery_seconds", 30.0)),
        ),
        llm_input_cost_per_million_tokens=max(
            0.0,
            source.get_float(
                "LLM_INPUT_COST_PER_MILLION_TOKENS",
                float(
                    model_defaults.get(
                        "llm_input_cost_per_million_tokens",
                        0.0,
                    )
                ),
            ),
        ),
        llm_output_cost_per_million_tokens=max(
            0.0,
            source.get_float(
                "LLM_OUTPUT_COST_PER_MILLION_TOKENS",
                float(
                    model_defaults.get(
                        "llm_output_cost_per_million_tokens",
                        0.0,
                    )
                ),
            ),
        ),
    )


__all__ = ["load_model_settings"]
