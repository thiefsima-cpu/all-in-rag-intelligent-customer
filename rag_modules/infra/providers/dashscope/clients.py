"""
Small DashScope HTTP clients for embedding and reranking.
"""

import logging
from typing import List, Sequence

import requests

from ....contracts import RequestControl
from ....kernel.json_types import JsonObject, coerce_json_object
from ...resilience import CircuitBreaker, build_pooled_requests_session

logger = logging.getLogger(__name__)


def _json_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


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

    def embed_query(self, text: str, *, timeout_seconds: float | None = None) -> List[float]:
        vectors = self.embed_documents([text], timeout_seconds=timeout_seconds)
        return vectors[0] if vectors else []

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> List[List[float]]:
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [str(text or "") for text in texts[start : start + self.batch_size]]
            vectors.extend(self._embed_batch(batch, timeout_seconds=timeout_seconds))
        return vectors

    def _embed_batch(
        self,
        texts: Sequence[str],
        *,
        timeout_seconds: float | None = None,
    ) -> List[List[float]]:
        payload = {
            "model": self.model_name,
            "input": {
                "contents": [{"text": text} for text in texts],
            },
            "parameters": {
                "dimension": self.dimension,
            },
        }
        data = self.circuit_breaker.call(
            self._post_json,
            payload,
            timeout_seconds=timeout_seconds,
        )

        output = coerce_json_object(data.get("output"))
        embeddings = _json_list(output.get("embeddings"))
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Embedding response count mismatch: expected {len(texts)}, got {len(embeddings)}"
            )

        vectors: List[List[float]] = []
        for item in embeddings:
            embedding_item = coerce_json_object(item)
            vector_payload = _json_list(embedding_item.get("embedding"))
            if not vector_payload:
                raise ValueError(f"Missing embedding in DashScope response: {item}")
            vector: List[float] = []
            for component in vector_payload:
                if not isinstance(component, (int, float, str)):
                    raise ValueError(f"Invalid embedding component in DashScope response: {item}")
                vector.append(float(component))
            vectors.append(vector)
        return vectors

    def _post_json(self, payload: dict, *, timeout_seconds: float | None = None) -> JsonObject:
        response = self.session.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout if timeout_seconds is None else timeout_seconds,
        )
        response.raise_for_status()
        return coerce_json_object(response.json())

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

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
        *,
        control: RequestControl | None = None,
        timeout_seconds: float | None = None,
    ) -> List[int]:
        if not documents:
            return []
        if control is not None:
            control.raise_if_cancelled()

        is_qwen3_text_reranker = self.model_name.casefold() == "qwen3-rerank"
        if is_qwen3_text_reranker:
            payload = {
                "model": self.model_name,
                "query": query,
                "documents": list(documents),
                "top_n": min(top_n, len(documents)),
            }
        else:
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
        effective_timeout = control.remaining_seconds() if control is not None else timeout_seconds
        data = self.circuit_breaker.call(
            self._post_json,
            payload,
            timeout_seconds=effective_timeout,
        )
        if control is not None:
            control.raise_if_cancelled()

        if is_qwen3_text_reranker:
            results = _json_list(data.get("results"))
        else:
            output = coerce_json_object(data.get("output"))
            results = _json_list(output.get("results"))
        ordered: List[int] = []
        for item in results:
            result_item = coerce_json_object(item)
            index = result_item.get("index")
            if index is None:
                continue
            if not isinstance(index, (int, float, str)):
                raise ValueError(f"Invalid rerank index in DashScope response: {item}")
            ordered.append(int(index))
        return ordered

    def _post_json(self, payload: dict, *, timeout_seconds: float | None = None) -> JsonObject:
        response = self.session.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout if timeout_seconds is None else timeout_seconds,
        )
        response.raise_for_status()
        return coerce_json_object(response.json())

    def close(self) -> None:
        self.session.close()
