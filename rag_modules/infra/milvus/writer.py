"""Milvus vector write operations."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import List, Optional

from ...kernel.documents import TextDocument
from ...safe_logging import log_failure
from .contracts import MilvusOperationHost

logger = logging.getLogger(__name__)


class _MilvusWriterOperations(MilvusOperationHost):
    def _safe_truncate(self, text: object, max_length: int) -> str:
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

    def _vector_entity(
        self,
        chunk: TextDocument,
        vector: object,
        index: int,
        *,
        default_chunk_id: str | None = None,
    ) -> dict[str, object]:
        metadata = chunk.metadata or {}
        entity_id = metadata.get("entity_id") or metadata.get("node_id") or ""
        entity_name = metadata.get("entity_name") or ""
        entity_type = metadata.get("entity_type") or metadata.get("node_type", "")
        raw_attributes = metadata.get("attributes")
        reserved_fields = {
            "entity_id",
            "entity_name",
            "entity_type",
            "domain",
            "attributes",
            "node_id",
            "node_type",
            "doc_type",
            "chunk_id",
            "parent_id",
        }
        attributes = {
            str(key): value for key, value in metadata.items() if key not in reserved_fields
        }
        if isinstance(raw_attributes, Mapping):
            attributes.update({str(key): value for key, value in raw_attributes.items()})
        chunk_id = chunk.metadata.get("chunk_id") or default_chunk_id or f"chunk_{index}"
        return {
            "id": self._safe_truncate(chunk_id, 150),
            "vector": vector,
            "text": self._safe_truncate(chunk.page_content, 15000),
            "entity_id": self._safe_truncate(entity_id, 150),
            "entity_name": self._safe_truncate(entity_name, 300),
            "entity_type": self._safe_truncate(entity_type, 100),
            "domain": self._safe_truncate(self.domain_name, 100),
            "attributes": attributes,
            "node_id": self._safe_truncate(entity_id, 100),
            "node_type": self._safe_truncate(entity_type, 100),
            "doc_type": self._safe_truncate(chunk.metadata.get("doc_type", ""), 50),
            "chunk_id": self._safe_truncate(chunk_id, 150),
            "parent_id": self._safe_truncate(chunk.metadata.get("parent_id", ""), 100),
        }

    def _insert_vector_batches(
        self,
        collection_name: str,
        entities: list[dict[str, object]],
    ) -> None:
        batch_size = 100
        for i in range(0, len(entities), batch_size):
            batch = entities[i : i + batch_size]
            self.client.insert(collection_name=collection_name, data=batch)
            logger.info(f"已插入 {min(i + batch_size, len(entities))}/{len(entities)} 条数据")

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
            entities = [
                self._vector_entity(chunk, vector, index)
                for index, (chunk, vector) in enumerate(zip(chunks, vectors))
            ]

            # 4. 批量插入数据
            logger.info("正在插入向量数据...")
            self._insert_vector_batches(target_collection, entities)

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
            entities = [
                self._vector_entity(
                    chunk,
                    vector,
                    i,
                    default_chunk_id=f"new_chunk_{i}_{int(time.time())}",
                )
                for i, (chunk, vector) in enumerate(zip(new_chunks, vectors))
            ]

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
