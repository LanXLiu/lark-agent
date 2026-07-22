# Knowledge

`knowledge/` 包含知识库管线：文档入库、检索、评估和知识处理公共工具。

Agent 决定什么时候调用检索；本模块提供可被调用的入库和检索能力。

## 模块

| 模块 | 职责 |
| --- | --- |
| [`ingestion/`](ingestion/README.md) | 文档转换、清洗、切片、入库编排和向量写入 |
| [`retrieval/`](retrieval/README.md) | Dense + BM25 混合召回、RRF 融合、精排、过滤和父子召回 |
| [`evaluation/`](evaluation/README.md) | 使用 Ragas 评估回答和检索质量 |
| [`utils/`](utils/README.md) | 去重、层级解析、payload 构建、重试和稀疏向量工具 |

## 数据流

```text
文档
  -> knowledge/ingestion
  -> MinIO 原文 / Markdown / chunk 对象
  -> Qdrant dense 和 sparse payload

问题
  -> knowledge/retrieval
  -> RecallResult
  -> app/assistant

测试集
  -> knowledge/evaluation
  -> 质量指标
```

本模块不处理飞书消息，也不负责决定什么时候检索。Agent 路由位于 `app/assistant`。
