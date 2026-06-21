"""Milvus client and collection operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pymilvus import MilvusClient

from ...dashscope_clients import DashScopeEmbeddingClient

logger = logging.getLogger(__name__)


class _MilvusClientOperations:
    def _setup_client(self):
        """初始化Milvus客户端"""
        try:
            self.client = MilvusClient(
                uri=f"http://{self.host}:{self.port}"
            )
            logger.info(f"已连接到Milvus服务器: {self.host}:{self.port}")
            
            # 测试连接
            collections = self.client.list_collections()
            logger.info(f"连接成功，当前集合: {collections}")
            
        except Exception as e:
            logger.error(f"连接Milvus失败: {e}")
            raise

    def _setup_embeddings(self):
        """初始化嵌入模型"""
        logger.info(f"正在初始化嵌入模型: {self.model_name}")
        
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
            circuit_breaker_failure_threshold=(
                self.circuit_breaker_failure_threshold
            ),
            circuit_breaker_recovery_seconds=(
                self.circuit_breaker_recovery_seconds
            ),
        )
        
        logger.info("嵌入模型初始化完成")

    def get_collection_stats(
        self,
        collection_name: Optional[str] = None,
    ) -> Dict[str, Any]:
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
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"获取集合统计信息失败: {e}")
            return {"error": str(e)}

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
                logger.info(f"集合 {target_collection} 已删除")
                if target_collection == self.collection_name:
                    self.collection_created = False
                return True
            else:
                logger.info(f"集合 {target_collection} 不存在")
                return True
                
        except Exception as e:
            logger.error(f"删除集合失败: {e}")
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
        except Exception as e:
            logger.error(f"检查集合存在性失败: {e}")
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
                logger.error(f"集合 {target_collection} 不存在")
                return False
            
            self.client.load_collection(load_target)
            self.collection_name = target_collection
            self.collection_created = True
            logger.info(f"集合 {target_collection} 已加载到内存")
            return True
            
        except Exception as e:
            logger.error(f"加载集合失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        embeddings = getattr(self, "embeddings", None)
        if embeddings and hasattr(embeddings, "close"):
            embeddings.close()
        if hasattr(self, 'client') and self.client:
            # Milvus客户端不需要显式关闭
            logger.info("Milvus连接已关闭")

    def __del__(self):
        """析构函数"""
        self.close()
