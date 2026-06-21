"""
Small DashScope HTTP clients for embedding and reranking.
"""

import logging
from typing import List, Sequence

import requests

from .infra.resilience import CircuitBreaker, build_pooled_requests_session

logger = logging.getLogger(__name__)


class DashScopeEmbeddingClient:
    """LangChain-like embedding client backed by DashScope multimodal embedding."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str,
        dimension: int = 1024,
        batch_size: int = 10,
        timeout: int = 60,
        session: requests.Session | None = None,
        http_pool_connections: int = 10,
        http_pool_maxsize: int = 20,
        circuit_breaker: CircuitBreaker | None = None,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
    ):
        if not api_key:
            raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.dimension = dimension
        self.batch_size = batch_size
        self.timeout = timeout
        self.session = session or build_pooled_requests_session(
            pool_connections=http_pool_connections,
            pool_maxsize=http_pool_maxsize,
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_timeout_seconds=circuit_breaker_recovery_seconds,
        )

    def embed_query(self, text: str) -> List[float]:
        vectors = self.embed_documents([text])
        return vectors[0] if vectors else []

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [str(text or "") for text in texts[start : start + self.batch_size]]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        payload = {
            "model": self.model_name,
            "input": {
                "contents": [{"text": text} for text in texts],
            },
            "parameters": {
                "dimension": self.dimension,
            },
        }
        data = self.circuit_breaker.call(self._post_json, payload)

        embeddings = data.get("output", {}).get("embeddings", [])
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Embedding response count mismatch: expected {len(texts)}, got {len(embeddings)}"
            )

        vectors = []
        for item in embeddings:
            vector = item.get("embedding")
            if not vector:
                raise ValueError(f"Missing embedding in DashScope response: {item}")
            vectors.append(vector)
        return vectors

    def _post_json(self, payload: dict) -> dict:
        response = self.session.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.session.close()


class DashScopeRerankClient:
    """DashScope text rerank client."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout: int = 60,
        session: requests.Session | None = None,
        http_pool_connections: int = 10,
        http_pool_maxsize: int = 20,
        circuit_breaker: CircuitBreaker | None = None,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
    ):
        if not api_key:
            raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout
        self.session = session or build_pooled_requests_session(
            pool_connections=http_pool_connections,
            pool_maxsize=http_pool_maxsize,
        )
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_timeout_seconds=circuit_breaker_recovery_seconds,
        )

    def rerank(self, query: str, documents: Sequence[str], top_n: int) -> List[int]:
        if not documents:
            return []

        payload = {
            "model": self.model_name,
            "input": {
                "query": {"text": query},
                "documents": [{"text": document} for document in documents],
            },
            "parameters": {
                "top_n": min(top_n, len(documents)),
            },
        }
        data = self.circuit_breaker.call(self._post_json, payload)

        results = data.get("output", {}).get("results", [])
        ordered = []
        for item in results:
            index = item.get("index")
            if index is None:
                continue
            ordered.append(int(index))
        return ordered

    def _post_json(self, payload: dict) -> dict:
        response = self.session.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.session.close()
