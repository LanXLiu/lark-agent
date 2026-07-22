# knowledge/utils

知识入库与检索共享的纯处理能力。

| 文件 | 职责 |
|---|---|
| `chunk_dedup.py` | 文档内 chunk 去重与合并 |
| `lsh_deduplication.py` | LSH 近似去重 |
| `markdown_hierarchy.py` | Markdown 标题层级处理 |
| `payload_builder.py` | 构造 Qdrant payload 和 point |
| `sparse_embedder.py` | BM25 稀疏向量 |
| `collection_router.py` | collection 路由 |
| `retry.py` | 通用退避重试 |

本目录不负责连接外部服务，连接配置由 `infrastructure` 提供。
