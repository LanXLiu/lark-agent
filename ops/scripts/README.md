# ops/scripts

项目运维命令集合。

| 命令 | 用途 |
|---|---|
| `python -m ops.scripts.upload_files --path <path>` | 上传本地文件或目录到 MinIO raw |
| `python -m knowledge.ingestion.orchestrator.knowledge_pipeline` | 转 Markdown 并切片 |
| `python -m ops.scripts.chunk_minio_to_qdrant --collection knowledgebase` | chunk 向量化并写入 Qdrant |
| `python -m ops.scripts.recall_cli "问题" --collection knowledgebase` | 命令行验证召回 |
| `python -m ops.scripts.init_qdrant_collections` | 初始化 collection |
| `python -m ops.scripts.delete_doc` | 按脚本参数删除指定文档向量 |

运行命令时工作目录应为项目根目录。
