# orchestrator — 入库管线编排

把「原始文件 → markdown → chunk → 向量库」串成可断点续传的管线。带三态机（待处理/成功/失败）和 JSONL 元数据记录。

## 文件

| 文件 | 职责 |
|---|---|
| `knowledge_pipeline.py` | **入库管线入口**。扫 MinIO raw → 转 markdown → 切片 → 写回 MinIO chunk。`python -m orchestrator.knowledge_pipeline` 运行。 |
| `raw_to_markdown.py` | raw 文件 → markdown（调 `converter` / `file_to_markdown`）。 |
| `markdown_to_chunk.py` | markdown → chunk（调 `chunker`，带 breadcrumb）。 |
| `chunk_to_qdrant.py` | chunk → 向量化 → 写 Qdrant。 |
| `pipeline_stages.py` / `pipeline_common.py` | 各阶段封装 + 共享的存储/键构造/元数据工具。 |

## 说明

切片（写 MinIO chunk）与向量化（写 Qdrant）是两个阶段。若只想把已切好的 chunk 直接向量化入库，用 `scripts/chunk_minio_to_qdrant.py`（直接扫 MinIO chunk 前缀 → 向量化 → upsert），可绕过分阶段的元数据依赖。
