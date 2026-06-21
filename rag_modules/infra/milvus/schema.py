"""Milvus collection schema and index operations."""

from __future__ import annotations

import logging
from typing import Any, Optional

from pymilvus import CollectionSchema, DataType, FieldSchema

logger = logging.getLogger(__name__)


class _MilvusSchemaOperations:
    client: Any
    collection_created: bool
    collection_name: str
    dimension: int

    def _create_collection_schema(self) -> CollectionSchema:
        """
        创建集合模式

        Returns:
            集合模式对象
        """
        # 定义字段
        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=150, is_primary=True),
            FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self.dimension),
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=15000),
            FieldSchema(name="node_id", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="recipe_name", dtype=DataType.VARCHAR, max_length=300),
            FieldSchema(name="node_type", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=100),
            FieldSchema(name="cuisine_type", dtype=DataType.VARCHAR, max_length=200),
            FieldSchema(name="difficulty", dtype=DataType.INT64),
            FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=50),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=150),
            FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=100),
        ]

        # 创建集合模式
        schema = CollectionSchema(fields=fields, description="中式烹饪知识图谱向量集合")

        return schema

    def create_collection(
        self,
        force_recreate: bool = False,
        *,
        collection_name: Optional[str] = None,
    ) -> bool:
        """
        创建Milvus集合

        Args:
            force_recreate: 是否强制重新创建集合

        Returns:
            是否创建成功
        """
        try:
            target_collection = collection_name or self.collection_name
            # 检查集合是否存在
            if self.client.has_collection(target_collection):
                if force_recreate:
                    logger.info(f"删除已存在的集合: {target_collection}")
                    self.client.drop_collection(target_collection)
                else:
                    logger.info(f"集合 {target_collection} 已存在")
                    self.collection_created = True
                    return True

            # 创建集合
            schema = self._create_collection_schema()

            self.client.create_collection(
                collection_name=target_collection,
                schema=schema,
                metric_type="COSINE",  # 使用余弦相似度
                consistency_level="Strong",
            )

            logger.info(f"成功创建集合: {target_collection}")
            self.collection_name = target_collection
            self.collection_created = True

            return True

        except Exception as e:
            logger.error(f"创建集合失败: {e}")
            return False

    def create_index(self, *, collection_name: Optional[str] = None) -> bool:
        """
        创建向量索引

        Returns:
            是否创建成功
        """
        try:
            if not self.collection_created:
                raise ValueError("请先创建集合")

            # 使用prepare_index_params创建正确的IndexParams对象
            index_params = self.client.prepare_index_params()

            # 添加向量字段索引
            index_params.add_index(
                field_name="vector",
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )

            self.client.create_index(
                collection_name=collection_name or self.collection_name, index_params=index_params
            )

            logger.info("向量索引创建成功")
            return True

        except Exception as e:
            logger.error(f"创建索引失败: {e}")
            return False
