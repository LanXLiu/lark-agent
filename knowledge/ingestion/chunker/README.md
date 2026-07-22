# knowledge/ingestion/chunker — 切片

把 markdown 切成适合检索的 chunk。默认策略 `markdown_structure`：按标题层级切，并给每块打上 breadcrumb（标题路径）和 level，供父子召回使用。

## 文件

| 文件 | 职责 |
|---|---|
| `chunker_factory.py` | 按策略名创建 chunker。 |
| `base.py` | chunker 基类 / 通用接口。 |
| `markdown_structure_chunker.py` | **默认策略**。按 `#`/`##`/`###` 标题结构切，保留层级；表格可整块成 chunk。 |
| `recursive_chunker.py` | 递归按长度切（chunk_size + overlap）。 |
| `semantic_chunker.py` | 语义切分（按语义边界）。 |
| `text_chunker.py` | 纯文本切分。 |
| `doc_type_detector.py` | 识别文档类型，辅助选策略。 |

## 关键产物

每个 chunk 带 `breadcrumb`（如 `报告 > 第四层 > L1`）和 `level`。这两个字段一路传到 Qdrant payload，是父子召回能工作的前提。切片策略参数在 `infrastructure/conf/config_local.yaml` 的 `chunker` 段。
