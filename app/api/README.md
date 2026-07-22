# API

`app/api` 保存可选 FastAPI 接口，供需要通过 HTTP 调用召回、向量化或文档转换能力的外部系统使用。

飞书 bot 主链路不依赖这个 API，而是在进程内直接调用 assistant 和 retrieval。

## 启动

```powershell
uvicorn app.api.main:app --port <port>
```

## 路由

| 前缀 | 来源 | 作用 |
| --- | --- | --- |
| `/recall` | `routers/recall.py` | 混合知识库检索 |
| `/embed` | `routers/embedding.py` | 文本向量化 |
| `/convert` | `routers/convert.py` | 配置开启时提供文件转 Markdown |
| `/health` | `main.py` | 健康检查 |

## 结构

- `main.py`：应用入口和 router 挂载。
- `routers/`：接口实现。
- `schemas/`：Pydantic 请求和响应模型。
