# api — HTTP 接口（可选）

FastAPI 服务，把召回 / 向量化 / 转换能力暴露为 HTTP，供外部系统调用。

> 飞书机器人**不走本模块**——它在进程内直接调用召回。api 仅供需要 HTTP 接入的外部调用方，按需单独启动。

## 启动

```bash
uvicorn api.main:app --port 8010
```

## 路由

| 前缀 | 来源 | 说明 |
|---|---|---|
| `/recall` | `routers/recall.py` | 混合召回检索 |
| `/embed` | `routers/embedding.py` | 文本向量化 |
| `/convert` | `routers/convert.py` | 文件转 markdown（仅当配置 `api_enable_convert` 开启时挂载） |
| `/health` | `main.py` | 健康检查 |

## 结构

- `main.py`：应用入口，挂载各 router。
- `routers/`：各接口的路由实现。
- `schemas/`：请求/响应的 pydantic 模型（recall / embedding / convert）。
