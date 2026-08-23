"""Canonical Milvus index construction module."""

from __future__ import annotations

from .blue_green import _MilvusBlueGreenOperations
from .client import _MilvusClientOperations
from .ports import EmbeddingClientPort
from .schema import _MilvusSchemaOperations
from .search import _MilvusSearchOperations
from .writer import _MilvusWriterOperations


class MilvusIndexConstructionModule(
    _MilvusBlueGreenOperations,
    _MilvusSearchOperations,
    _MilvusWriterOperations,
    _MilvusSchemaOperations,
    _MilvusClientOperations,
):
    """Milvus index construction module for vector writes, reads, and publish flow."""

    def __init__(
        self,
        *,
        embedding_client: EmbeddingClientPort,
        domain_name: str,
        host: str = "localhost",
        port: int = 19530,
        collection_name: str = "knowledge",
        dimension: int = 512,
        vector_search_ef: int = 128,
        vector_search_max_k: int = 50,
        blue_green_enabled: bool = True,
        collection_alias_suffix: str = "__active",
    ):
        """
        初始化Milvus索引构建模块

        Args:
            host: Milvus服务器地址
            port: Milvus服务器端口
            collection_name: 集合名称
            dimension: 向量维度
            model_name: 嵌入模型名称
        """
        self.host = host
        self.port = port
        self.base_collection_name = collection_name
        self.collection_name = collection_name
        self.collection_alias = f"{collection_name}{collection_alias_suffix}"
        self.domain_name = str(domain_name or "").strip()
        if not self.domain_name:
            raise ValueError("Milvus domain_name must be provided by application composition.")
        self.blue_green_enabled = bool(blue_green_enabled)
        self.active_collection_name = ""
        self.active_collection_slot = ""
        self.build_collection_name = ""
        self.dimension = dimension
        self.vector_search_ef = vector_search_ef
        self.vector_search_max_k = vector_search_max_k
        self.embedding_client = embedding_client

        self.collection_created = False

        self._setup_client()
        self._setup_embeddings()
