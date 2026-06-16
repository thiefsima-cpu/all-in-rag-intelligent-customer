"""Compatibility re-export for BM25 retrieval adapter."""

from .adapters.bm25_retriever import BM25Retriever, tokenize_chinese

__all__ = ["BM25Retriever", "tokenize_chinese"]
