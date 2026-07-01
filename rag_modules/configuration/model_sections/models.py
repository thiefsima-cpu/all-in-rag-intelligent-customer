"""Model provider configuration section model."""

from __future__ import annotations

from pydantic import Field

from .base import ConfigSection


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
    embedding_dimension: int = Field(default=1024, ge=1)
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


__all__ = ["ModelSettings"]
