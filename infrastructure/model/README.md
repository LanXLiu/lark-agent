# infrastructure/model

模型服务客户端，统一封装 embedding、rerank、OCR 和通用模型调用。

| 文件 | 职责 |
|---|---|
| `embedding_client.py` | dense embedding |
| `rerank_client.py` | 检索结果精排 |
| `ocr_client.py` | OCR 调用 |
| `llm_client.py` | 通用模型客户端 |
| `base.py` | 基础请求与响应抽象 |
| `schemas/` | 模型响应结构 |

模型地址、密钥和名称从 `infrastructure/conf/config_local.yaml` 与环境变量读取。
