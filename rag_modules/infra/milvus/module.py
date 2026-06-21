"""Canonical Milvus index construction module."""

from __future__ import annotations

from ...runtime_contracts import EmbeddingClientPort
from .blue_green import _MilvusBlueGreenOperations
from .client import _MilvusClientOperations
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

    def __init__(self, 
                 host: str = "localhost", 
                 port: int = 19530,
                 collection_name: str = "cooking_knowledge",
                 dimension: int = 512,
                 model_name: str = "qwen3-vl-embedding",
                 api_key: str = "",
                 embedding_base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/multimodal-embedding/multimodal-embedding",
                 embedding_batch_size: int = 10,
                 embedding_timeout_seconds: int = 60,
                 http_pool_connections: int = 10,
                 http_pool_maxsize: int = 20,
                 circuit_breaker_failure_threshold: int = 5,
                 circuit_breaker_recovery_seconds: float = 30.0,
                 vector_search_ef: int = 128,
                 vector_search_max_k: int = 50,
                 blue_green_enabled: bool = True,
                 collection_alias_suffix: str = "__active",
                 embedding_client: EmbeddingClientPort | None = None):
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
        self.blue_green_enabled = bool(blue_green_enabled)
        self.active_collection_name = ""
        self.active_collection_slot = ""
        self.build_collection_name = ""
        self.dimension = dimension
        self.model_name = model_name
        self.api_key = api_key
        self.embedding_base_url = embedding_base_url
        self.embedding_batch_size = embedding_batch_size
        self.embedding_timeout_seconds = embedding_timeout_seconds
        self.http_pool_connections = http_pool_connections
        self.http_pool_maxsize = http_pool_maxsize
        self.circuit_breaker_failure_threshold = circuit_breaker_failure_threshold
        self.circuit_breaker_recovery_seconds = circuit_breaker_recovery_seconds
        self.vector_search_ef = vector_search_ef
        self.vector_search_max_k = vector_search_max_k
        self.embedding_client = embedding_client
        
        self.client = None
        self.embeddings = None
        self.collection_created = False
        
        self._setup_client()
        self._setup_embeddings()
