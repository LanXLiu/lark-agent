# knowledge/ingestion

知识入库总域。支持飞书文档、PDF、Word、PPT、Excel、图片、JSON、Markdown 和文本文件。

```text
raw 文件
  -> file_to_markdown / converter
  -> cleans
  -> chunker
  -> orchestrator
  -> MinIO markdown/chunk + Qdrant
```

## 目录

| 目录 | 职责 |
|---|---|
| [`file_to_markdown/`](file_to_markdown/README.md) | 各格式转 Markdown、OCR、VLM、表格渲染 |
| [`converter/`](converter/README.md) | 按文件类型分发转换器 |
| [`cleans/`](cleans/README.md) | Markdown 清洗管线 |
| [`chunker/`](chunker/README.md) | 结构化切片、breadcrumb 和表格原子化 |
| [`orchestrator/`](orchestrator/README.md) | 断点续传、阶段编排和向量写入 |

## 运行

```bash
python -m knowledge.ingestion.orchestrator.knowledge_pipeline
python -m ops.scripts.chunk_minio_to_qdrant --collection knowledgebase --prefix chunk/...
```

公开入口为 `KnowledgeBasePipeline`，可通过 `from knowledge.ingestion import KnowledgeBasePipeline` 使用。
