# recall — 混合召回

RAG 的检索核心。dense 向量 + BM25 稀疏 → RRF 融合 → rerank 精排 → 父子召回 → 阈值过滤。

## 文件

| 文件 | 职责 |
|---|---|
| `hybrid_recall.py` | **入口**。`HybridRecaller.search(RecallRequest)`：编排整条召回链，含父子召回展开（`_expand_siblings`：命中某 chunk 时把同父标题路径下的兄弟 chunk 一起带出）。 |
| `query_encoder.py` | query 向量化（dense + sparse）。 |
| `rerank_stage.py` | cross-encoder 精排（远程 `qwen3-vl-rerank`，百炼等 OpenAI 兼容网关）。 |
| `postprocess.py` | 精排后处理：阈值过滤、每文档命中数上限。 |
| `filters.py` | 召回过滤条件构造（collection / doc / tag / tenant 等）。 |
| `result_parser.py` | Qdrant 命中 → `RecallHit`。 |
| `config.py` | 召回参数（top_k、rerank、阈值 min_score、parent_child 开关等）。 |
| `schemas.py` | `RecallRequest` / `RecallHit` / `RecallResult` 数据结构。 |

## 关键概念

- **breadcrumb**：切片时写入的标题路径（如 `报告 > 第四层 > L1`），父子召回靠它找兄弟节点。
- **阈值 min_score**（默认 0.68）：精排分低于此视为不相关、不返回，实现无关拒答。
