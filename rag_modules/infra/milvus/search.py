"""Milvus vector search operations."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ...runtime_contracts import EmbeddingClientPort

logger = logging.getLogger(__name__)


class _MilvusSearchOperations:
    client: Any
    collection_created: bool
    collection_name: str
    embeddings: EmbeddingClientPort
    vector_search_ef: int
    vector_search_max_k: int

    def similarity_search(
        self, query: str, k: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        相似度搜索

        Args:
            query: 查询文本
            k: 返回结果数量
            filters: 过滤条件

        Returns:
            搜索结果列表
        """
        if not self.collection_created:
            raise ValueError("请先构建或加载向量索引")

        try:
            requested_k = max(1, int(k or 1))
            if self.vector_search_max_k:
                requested_k = min(requested_k, max(1, int(self.vector_search_max_k)))
            search_ef = max(int(self.vector_search_ef or 64), requested_k)

            # 生成查询向量
            query_vector = self.embeddings.embed_query(query)

            # 构建过滤表达式
            filter_expr = ""
            if filters:
                filter_conditions = []
                for key, value in filters.items():
                    if isinstance(value, str):
                        filter_conditions.append(f'{key} == "{value}"')
                    elif isinstance(value, (int, float)):
                        filter_conditions.append(f"{key} == {value}")
                    elif isinstance(value, list):
                        # 支持IN操作
                        if all(isinstance(v, str) for v in value):
                            value_str = '", "'.join(value)
                            filter_conditions.append(f'{key} in ["{value_str}"]')
                        else:
                            value_str = ", ".join(map(str, value))
                            filter_conditions.append(f"{key} in [{value_str}]")

                if filter_conditions:
                    filter_expr = " and ".join(filter_conditions)

            # 执行搜索 - 修复参数传递
            search_params = {"metric_type": "COSINE", "params": {"ef": search_ef}}

            # 构建搜索参数，避免重复传递
            search_kwargs = {
                "collection_name": self.collection_name,
                "data": [query_vector],
                "anns_field": "vector",
                "limit": requested_k,
                "output_fields": [
                    "text",
                    "node_id",
                    "recipe_name",
                    "node_type",
                    "category",
                    "cuisine_type",
                    "difficulty",
                    "doc_type",
                    "chunk_id",
                    "parent_id",
                ],
                "search_params": search_params,
            }

            # 只在有过滤条件时添加filter参数
            if filter_expr:
                search_kwargs["filter"] = filter_expr

            results = self.client.search(**search_kwargs)

            # 处理结果
            formatted_results = []
            if results and len(results) > 0:
                for hit in results[0]:  # results[0]因为我们只发送了一个查询向量
                    result = {
                        "id": hit["id"],
                        "score": hit["distance"],  # 注意：在COSINE距离中，值越大相似度越高
                        "text": hit["entity"]["text"],
                        "metadata": {
                            "node_id": hit["entity"]["node_id"],
                            "recipe_name": hit["entity"]["recipe_name"],
                            "node_type": hit["entity"]["node_type"],
                            "category": hit["entity"]["category"],
                            "cuisine_type": hit["entity"]["cuisine_type"],
                            "difficulty": hit["entity"]["difficulty"],
                            "doc_type": hit["entity"]["doc_type"],
                            "chunk_id": hit["entity"]["chunk_id"],
                            "parent_id": hit["entity"]["parent_id"],
                        },
                    }
                    formatted_results.append(result)

            return formatted_results

        except Exception as e:
            logger.error(f"相似度搜索失败: {e}")
            return []
