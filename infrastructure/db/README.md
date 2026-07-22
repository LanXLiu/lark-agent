# infrastructure/db

数据存储客户端实现。

| 文件 | 职责 |
|---|---|
| `minio.py` | MinIO 配置、客户端、上传下载和对象列表 |
| `qdrant.py` | Qdrant 配置、collection 管理、检索和 upsert |

业务入口优先使用 `infrastructure.object_storage` 和 `infrastructure.vector_store`，避免调用方依赖内部文件布局。
