# Infrastructure

`infrastructure/` provides shared adapters for configuration, model clients, storage, and MCP connectivity. Upper layers depend on these public adapters instead of managing credentials, protocols, or connections directly.

## Modules

| Module | Responsibility |
| --- | --- |
| [`conf/`](conf/README.md) | Environment variables, YAML loading, interpolation, and logging setup |
| [`db/`](db/README.md) | MinIO and Qdrant clients |
| [`model/`](model/README.md) | LLM, embedding, rerank, and OCR clients |
| [`mcp/`](mcp/README.md) | Business database MCP, search/web MCP, clients, auth, and config helpers |
| `object_storage.py` | Common object-storage interface |
| `vector_store.py` | Common vector-store interface |

## Principles

- Real credentials and endpoints come from environment variables or ignored local files.
- MCP server host, port, path, auth, backend connection, and allowlists are environment-driven.
- Business logic should call infrastructure interfaces instead of duplicating connection code.
- MCP services are independent processes so other agents and projects can reuse them.

