"""
Small DashScope HTTP clients for embedding and reranking.
"""

import logging
from typing import List, Sequence

import requests

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
    ):
        if not api_key:
            raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.dimension = dimension
        self.batch_size = batch_size
        self.timeout = timeout

    def embed_query(self, text: str) -> List[float]:
        vectors = self.embed_documents([text])
        return vectors[0] if vectors else []

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = [str(text or "") for text in texts[start:start + self.batch_size]]
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
        response = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

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


class DashScopeRerankClient:
    """DashScope text rerank client."""

    def __init__(
        self,
        api_key: str,
        model_name: str,
        base_url: str,
        timeout: int = 60,
    ):
        if not api_key:
            raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self.timeout = timeout

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
        response = requests.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        results = data.get("output", {}).get("results", [])
        ordered = []
        for item in results:
            index = item.get("index")
            if index is None:
                continue
            ordered.append(int(index))
        return ordered
