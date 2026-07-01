"""BM25 keyword retriever (jieba tokenization + Chinese stopwords)."""

from __future__ import annotations

import logging
import os
import warnings
from typing import List, Optional

with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message="pkg_resources is deprecated as an API.*",
        category=UserWarning,
        module=r"jieba\._compat",
    )
    import jieba
from rank_bm25 import BM25Okapi

from ...contracts import EvidenceDocument
from ...safe_logging import log_failure
from ...text_document import TextDocument

logger = logging.getLogger(__name__)

_CHINESE_STOPWORDS = set(
    """
    的 了 和 是 在 我 你 他 她 它 我们 你们 他们
    一个 一种 这个 那个 哪些 什么 怎么 如何 为什么
    请问 请 帮我 帮忙 可以 需要 应该 还有 同时 并且
    吗 呢 吧 呀 哦
    """.split()
)

_CUSTOM_DICT_LOADED = False


def load_custom_dict(dict_path: str = "storage/jieba_dict.txt") -> None:
    """Load a jieba custom dictionary if it exists."""
    global _CUSTOM_DICT_LOADED
    if _CUSTOM_DICT_LOADED:
        return
    if os.path.isfile(dict_path):
        jieba.load_userdict(dict_path)
        logger.info("Loaded jieba custom dictionary")
    _CUSTOM_DICT_LOADED = True


def tokenize_chinese(text: str) -> List[str]:
    """Tokenize Chinese text and filter low-signal tokens."""
    if not text:
        return []
    tokens = jieba.lcut(text)
    return [
        token
        for token in tokens
        if token.strip() and token not in _CHINESE_STOPWORDS and not token.isspace()
    ]


class BM25Retriever:
    """Standalone BM25 retriever over an internal text-document corpus."""

    def __init__(self) -> None:
        self.bm25: Optional[BM25Okapi] = None
        self.corpus_docs: List[TextDocument] = []

    @property
    def ready(self) -> bool:
        return self.bm25 is not None and bool(self.corpus_docs)

    def build(self, chunks: List[TextDocument]) -> None:
        load_custom_dict()
        self.corpus_docs = list(chunks)
        tokenized = [tokenize_chinese(document.content) for document in chunks]
        self.bm25 = BM25Okapi(tokenized)
        avg_tokens = sum(len(tokens) for tokens in tokenized) / max(1, len(tokenized))
        logger.info("BM25 index built: documents=%d avg_tokens=%.1f", len(chunks), avg_tokens)

    def search(self, query: str, top_k: int = 5) -> List[EvidenceDocument]:
        if not self.ready:
            logger.warning("BM25 index is not initialized.")
            return []

        tokenized_query = tokenize_chinese(query)
        if not tokenized_query:
            return []

        bm25 = self.bm25
        if bm25 is None:
            return []
        scores = bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)[
            :top_k
        ]

        docs: List[EvidenceDocument] = []
        for idx in top_indices:
            score = float(scores[idx])
            if score <= 0:
                continue
            src = self.corpus_docs[idx]
            metadata = dict(src.metadata or {})
            recipe_name = str(metadata.get("recipe_name") or metadata.get("name") or "")
            metadata.update(
                {
                    "recipe_name": recipe_name,
                    "search_method": "bm25",
                    "search_type": "bm25",
                    "bm25_score": score,
                    "score": score,
                    "source": "bm25",
                }
            )
            docs.append(
                EvidenceDocument(
                    content=src.content,
                    node_id=str(
                        metadata.get("node_id")
                        or metadata.get("parent_id")
                        or metadata.get("recipe_id")
                        or ""
                    ),
                    recipe_name=recipe_name,
                    node_type=str(metadata.get("node_type") or metadata.get("entity_type") or ""),
                    score=score,
                    search_type="bm25",
                    search_method="bm25",
                    retrieval_level=str(metadata.get("retrieval_level") or "chunk"),
                    doc_id=str(metadata.get("doc_id") or ""),
                    recipe_id=str(metadata.get("recipe_id") or metadata.get("node_id") or ""),
                    source="bm25",
                    metadata=metadata,
                )
            )

        logger.info("BM25 search complete: returned=%d", len(docs))
        return docs

    def to_cache_dict(self) -> dict:
        tokenized = [tokenize_chinese(document.content) for document in self.corpus_docs]
        return {
            "tokenized_corpus": tokenized,
            "corpus_docs": [
                {"page_content": document.content, "metadata": document.metadata}
                for document in self.corpus_docs
            ],
        }

    def from_cache_dict(self, data: dict) -> bool:
        try:
            tokenized = data["tokenized_corpus"]
            corpus_docs = data["corpus_docs"]
            if not isinstance(tokenized, list) or not isinstance(corpus_docs, list):
                return False
            if len(tokenized) != len(corpus_docs) or not corpus_docs:
                return False
            self.corpus_docs = [
                TextDocument(
                    content=str(item["page_content"]),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in corpus_docs
            ]
            normalized_tokens = [
                [str(token) for token in row] for row in tokenized if isinstance(row, list)
            ]
            if len(normalized_tokens) != len(self.corpus_docs):
                return False
            self.bm25 = BM25Okapi(normalized_tokens)
            return True
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "retrieval_operation_failed",
                code="RETRIEVAL_FAILED",
                error=exc,
            )
            return False
