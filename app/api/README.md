# API

`app/api` contains optional FastAPI endpoints for systems that need HTTP access to recall, embedding, or document conversion.

The Lark bot path does not depend on this API. It calls the assistant and retrieval stack in-process.

## Start

```powershell
uvicorn app.api.main:app --port <port>
```

## Routes

| Prefix | Source | Purpose |
| --- | --- | --- |
| `/recall` | `routers/recall.py` | Hybrid knowledge retrieval |
| `/embed` | `routers/embedding.py` | Text embedding |
| `/convert` | `routers/convert.py` | File-to-Markdown conversion when enabled by config |
| `/health` | `main.py` | Health check |

## Structure

- `main.py`: application entry and router mounting.
- `routers/`: endpoint implementations.
- `schemas/`: Pydantic request and response models.

