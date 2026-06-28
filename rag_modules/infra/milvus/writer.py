"""Milvus vector write operations."""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from ...safe_logging import log_failure
from ...text_document import TextDocument
from .contracts import MilvusOperationHost

logger = logging.getLogger(__name__)


class _MilvusWriterOperations(MilvusOperationHost):
    def _safe_truncate(self, text: str, max_length: int) -> str:
        """
        安全截取字符串，处理None值

        Args:
            text: 输入文本
            max_length: 最大长度

        Returns:
            截取后的字符串
        """
        if text is None:
            return ""
        return str(text)[:max_length]

    def build_vector_index(
        self,
        chunks: List[TextDocument],
        *,
        collection_name: Optional[str] = None,
    ) -> bool:
        """
        构建向量索引

        Args:
            chunks: 文档块列表

        Returns:
            是否构建成功
        """
        logger.info(f"正在构建Milvus向量索引，文档数量: {len(chunks)}...")

        if not chunks:
            raise ValueError("文档块列表不能为空")

        try:
            target_collection = (
                collection_name or self.build_collection_name or self.collection_name
            )
            self.collection_name = target_collection
            self.build_collection_name = target_collection
            # 1. 创建集合（如果schema不兼容则强制重新创建）
            if not self.create_collection(
                force_recreate=True,
                collection_name=target_collection,
            ):
                return False

            # 2. 准备数据
            logger.info("正在生成向量embeddings...")
            texts = [chunk.page_content for chunk in chunks]
            vectors = self.embeddings.embed_documents(texts)

            # 3. 准备插入数据
            entities = []
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                entity = {
                    "id": self._safe_truncate(chunk.metadata.get("chunk_id", f"chunk_{i}"), 150),
                    "vector": vector,
                    "text": self._safe_truncate(chunk.page_content, 15000),
                    "node_id": self._safe_truncate(chunk.metadata.get("node_id", ""), 100),
                    "recipe_name": self._safe_truncate(chunk.metadata.get("recipe_name", ""), 300),
                    "node_type": self._safe_truncate(chunk.metadata.get("node_type", ""), 100),
                    "category": self._safe_truncate(chunk.metadata.get("category", ""), 100),
                    "cuisine_type": self._safe_truncate(
                        chunk.metadata.get("cuisine_type", ""), 200
                    ),
                    "difficulty": int(chunk.metadata.get("difficulty", 0)),
                    "doc_type": self._safe_truncate(chunk.metadata.get("doc_type", ""), 50),
                    "chunk_id": self._safe_truncate(
                        chunk.metadata.get("chunk_id", f"chunk_{i}"), 150
                    ),
                    "parent_id": self._safe_truncate(chunk.metadata.get("parent_id", ""), 100),
                }
                entities.append(entity)

            # 4. 批量插入数据
            logger.info("正在插入向量数据...")
            batch_size = 100
            for i in range(0, len(entities), batch_size):
                batch = entities[i : i + batch_size]
                self.client.insert(collection_name=target_collection, data=batch)
                logger.info(f"已插入 {min(i + batch_size, len(entities))}/{len(entities)} 条数据")

            self.client.flush(collection_name=target_collection)

            # 5. 创建索引
            if not self.create_index(collection_name=target_collection):
                return False

            # 6. 加载集合到内存
            self.client.load_collection(target_collection)
            logger.info("集合已加载到内存")

            # 7. 等待索引构建完成
            logger.info("等待索引构建完成...")
            time.sleep(2)

            logger.info(f"向量索引构建完成，包含 {len(chunks)} 个向量")
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

    def add_documents(self, new_chunks: List[TextDocument]) -> bool:
        """
        向现有索引添加新文档

        Args:
            new_chunks: 新的文档块列表

        Returns:
            是否添加成功
        """
        if not self.collection_created:
            raise ValueError("请先构建向量索引")

        logger.info(f"正在添加 {len(new_chunks)} 个新文档到索引...")

        try:
            # 生成向量
            texts = [chunk.page_content for chunk in new_chunks]
            vectors = self.embeddings.embed_documents(texts)

            # 准备插入数据
            entities = []
            for i, (chunk, vector) in enumerate(zip(new_chunks, vectors)):
                entity = {
                    "id": self._safe_truncate(
                        chunk.metadata.get("chunk_id", f"new_chunk_{i}_{int(time.time())}"), 150
                    ),
                    "vector": vector,
                    "text": self._safe_truncate(chunk.page_content, 15000),
                    "node_id": self._safe_truncate(chunk.metadata.get("node_id", ""), 100),
                    "recipe_name": self._safe_truncate(chunk.metadata.get("recipe_name", ""), 300),
                    "node_type": self._safe_truncate(chunk.metadata.get("node_type", ""), 100),
                    "category": self._safe_truncate(chunk.metadata.get("category", ""), 100),
                    "cuisine_type": self._safe_truncate(
                        chunk.metadata.get("cuisine_type", ""), 200
                    ),
                    "difficulty": int(chunk.metadata.get("difficulty", 0)),
                    "doc_type": self._safe_truncate(chunk.metadata.get("doc_type", ""), 50),
                    "chunk_id": self._safe_truncate(
                        chunk.metadata.get("chunk_id", f"new_chunk_{i}_{int(time.time())}"), 150
                    ),
                    "parent_id": self._safe_truncate(chunk.metadata.get("parent_id", ""), 100),
                }
                entities.append(entity)

            # 插入数据
            self.client.insert(collection_name=self.collection_name, data=entities)

            logger.info("新文档添加完成")
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
