"""Milvus client and collection operations."""

from __future__ import annotations

import logging
from typing import Optional

from pymilvus import MilvusClient

from ...dashscope_clients import DashScopeEmbeddingClient
from ...runtime.json_types import JsonObject, coerce_json_object
from ...safe_logging import log_failure
from .contracts import MilvusOperationHost

logger = logging.getLogger(__name__)


class _MilvusClientOperations(MilvusOperationHost):
    def _setup_client(self):
        """初始化Milvus客户端"""
        try:
            self.client = MilvusClient(uri=f"http://{self.host}:{self.port}")
            logger.info("Milvus connection established")

            # 测试连接
            collections = self.client.list_collections()
            logger.info("Milvus collections listed: count=%s", len(collections))

        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            raise

    def _setup_embeddings(self):
        """初始化嵌入模型"""
        logger.info("Initializing embedding model")

        embedding_client = getattr(self, "embedding_client", None)
        if embedding_client is not None:
            self.embeddings = embedding_client
            logger.info("Embedding client injected through provider port.")
            return

        self.embeddings = DashScopeEmbeddingClient(
            api_key=self.api_key,
            model_name=self.model_name,
            base_url=self.embedding_base_url,
            dimension=self.dimension,
            batch_size=self.embedding_batch_size,
            timeout=self.embedding_timeout_seconds,
            http_pool_connections=self.http_pool_connections,
            http_pool_maxsize=self.http_pool_maxsize,
            circuit_breaker_failure_threshold=(self.circuit_breaker_failure_threshold),
            circuit_breaker_recovery_seconds=(self.circuit_breaker_recovery_seconds),
        )

        logger.info("嵌入模型初始化完成")

    def get_collection_stats(
        self,
        collection_name: Optional[str] = None,
    ) -> JsonObject:
        """
        获取集合统计信息

        Returns:
            统计信息字典
        """
        try:
            if not self.collection_created:
                return {"error": "集合未创建"}

            target_collection = collection_name or self.collection_name
            stats_target = (
                self.alias_target()
                if target_collection == self.collection_alias
                else target_collection
            )
            stats = self.client.get_collection_stats(stats_target)
            return {
                "collection_name": target_collection,
                "active_collection_name": self.active_collection_name,
                "collection_slot": self.active_collection_slot,
                "row_count": stats.get("row_count", 0),
                "index_building_progress": stats.get("index_building_progress", 0),
                "stats": coerce_json_object(stats),
            }

        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            return {"error": "MILVUS_STATS_UNAVAILABLE"}

    def delete_collection(self, collection_name: Optional[str] = None) -> bool:
        """
        删除集合

        Returns:
            是否删除成功
        """
        try:
            target_collection = collection_name or self.collection_name
            if self.client.has_collection(target_collection):
                self.client.drop_collection(target_collection)
                logger.info("Milvus collection deleted")
                if target_collection == self.collection_name:
                    self.collection_created = False
                return True
            else:
                logger.info("Milvus collection not found")
                return True

        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            return False

    def has_collection(self, collection_name: Optional[str] = None) -> bool:
        """
        检查集合是否存在

        Returns:
            集合是否存在
        """
        try:
            target_collection = collection_name or self.collection_name
            if target_collection == self.collection_alias:
                return bool(self.alias_target())
            return self.client.has_collection(target_collection)
        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            return False

    def load_collection(self, collection_name: Optional[str] = None) -> bool:
        """
        加载集合到内存

        Returns:
            是否加载成功
        """
        try:
            target_collection = collection_name or self.collection_name
            load_target = (
                self.alias_target()
                if target_collection == self.collection_alias
                else target_collection
            )
            if not load_target or not self.client.has_collection(load_target):
                logger.error("Milvus collection not found")
                return False

            self.client.load_collection(load_target)
            self.collection_name = target_collection
            self.collection_created = True
            logger.info("Milvus collection loaded")
            return True

        except Exception as exc:
            log_failure(
                logger,
                logging.ERROR,
                "milvus_operation_failed",
                code="MILVUS_OPERATION_FAILED",
                error=exc,
            )
            return False

    def close(self):
        """关闭连接"""
        embeddings = getattr(self, "embeddings", None)
        if embeddings and hasattr(embeddings, "close"):
            embeddings.close()
        if hasattr(self, "client") and self.client:
            # Milvus客户端不需要显式关闭
            logger.info("Milvus连接已关闭")

    def __del__(self):
        """析构函数"""
        self.close()
