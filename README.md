# Lark Agent

Lark Agent is an enterprise agent assistant for Lark/Feishu. It answers company knowledge questions, queries business data through MCP tools, searches public web information, keeps multi-turn context, and ingests documents into a searchable knowledge base.

RAG is one capability in this project, not the whole product. The assistant decides when to answer directly, when to retrieve from the knowledge base, when to call business database tools, and when to search the web.

## What This Project Provides

- **Agent assistant runtime**: LangGraph + Function Calling loop with configurable tool rounds, final-round forced answer, and source-aware finalization.
- **Knowledge base tool**: hybrid retrieval with dense vector search, BM25, RRF fusion, rerank, parent-child context expansion, and source citations.
- **Business database MCP**: reusable MCP service exposing fixed business operations such as inventory lookup, batch inventory lookup, order status, and product lookup.
- **Search/web MCP**: reusable MCP service for public web search and webpage reading.
- **Runtime skills**: Markdown skill files that are injected into the current agent turn only when the user request matches the workflow.
- **Lark channel**: private chat, group mention handling, message deduplication, fast acknowledgement, feedback entry, and group file download.
- **Document ingestion**: Lark docs, PDF, Word, PPT, Excel, images, JSON, Markdown, and plain text can be converted, cleaned, chunked, embedded, and written to Qdrant.
- **Conversation memory**: short rewrite history, answer context window, optional summaries, TTL/LRU cleanup, and optional SQLite persistence.
- **Redis-ready guards**: business query rate limiting can use Redis for cross-process consistency.
- **Evaluation**: Ragas-based evaluation for answer faithfulness, relevance, correctness, and retrieval quality.
- **Optional HTTP API**: FastAPI endpoints for recall, embedding, and document conversion.

## Why This Design

The project is designed for an enterprise assistant that needs both knowledge answers and operational data lookup without turning every request into a blind RAG flow.

- **Cleaner agent behavior**: tool selection is handled by Function Calling, while local code still controls which tools are visible in each runtime context.
- **Reusable business tools**: business database access is packaged as MCP, so the same tools can be reused by other agents and projects.
- **Lower tool confusion**: only two external MCP groups are planned: business database and search/web.
- **No model-generated SQL**: the agent passes structured business parameters to fixed MCP tools; SQL or database query templates stay outside the agent prompt.
- **Safer business data access**: business database tools are available only in private Lark chats for configured users. Group mentions never expose them.
- **Cost and load control**: business database calls are guarded by a maximum time window, per-user rate limit, and maximum returned rows.
- **Skill-based workflow guidance**: business database calling rules live in Markdown under `app/assistant/skills`, so clarification rules and answer policy can evolve without rewriting the main graph.
- **No long-lived prompt pollution**: runtime skills are injected only for the current request when keywords or identifiers match, and are not stored in conversation memory.
- **Ingestion remains first-class**: the knowledge pipeline is preserved under `knowledge/ingestion`, so new documents can still enter the knowledge base.

## Architecture

```text
Lark messages / HTTP calls
  -> app/channels/lark or app/api
  -> app/assistant
       -> runtime skill activation
       -> get_current_time
       -> search_knowledge
       -> business database MCP
       -> search/web MCP
  -> answer with sources and feedback entry

ops/scripts
  -> knowledge/ingestion
  -> MinIO raw/markdown/chunk objects
  -> Qdrant dense and sparse payloads

knowledge/evaluation
  -> app/assistant + knowledge/retrieval
```

The repository is organized into five project domains:

| Directory | Responsibility |
| --- | --- |
| `app/` | Lark channel, HTTP API, agent runtime, runtime skills, tools, memory, and answer formatting |
| `knowledge/` | Document ingestion, cleaning, chunking, retrieval, and evaluation |
| `infrastructure/` | Configuration, model clients, object/vector storage, MCP clients and servers |
| `ops/` | Operational scripts and project assets |
| `tests/` | Cross-module tests and architecture boundary tests |

## Agent Tools

| Tool | Source | Purpose |
| --- | --- | --- |
| `get_current_time` | local agent tool | Provides a time baseline for relative-date questions |
| `search_knowledge` | `knowledge/retrieval` | Retrieves company knowledge |
| `inventory_lookup` | business database MCP | Queries current inventory for one SKU |
| `inventory_batch_lookup` | business database MCP | Queries inventory for several SKUs |
| `order_status` | business database MCP | Queries order status and milestones |
| `product_lookup` | business database MCP | Finds products by name, SKU, keyword, or category |
| `web_search` / `web_fetch` | search/web MCP | Searches public information and reads webpage text |

Runtime identity, retrievers, MCP clients, and connection details are injected through code. They are not model arguments.

## Runtime Skills

Runtime skills live under [app/assistant/skills](app/assistant/skills/README.md). The current skill is:

- [business_database_mcp.md](app/assistant/skills/business_database_mcp.md): how the assistant should prepare before calling business database MCP tools.

Activation flow:

```text
user message
  -> keyword / SKU / order-number detection
  -> private chat + allowed user check
  -> inject Markdown skill into this agent run
  -> run Function Calling loop
  -> discard skill context after the turn
```

The skill tells the assistant when to clarify missing SKU, order number, warehouse, product, or date parameters. Hard limits remain in code:

- Private chat only.
- User allowlist from `BUSINESS_DB_MCP_ALLOWED_USERS`.
- Maximum query window, default 30 days.
- Per-user rate limit, default 3 business calls per 60 seconds.
- Optional Redis-backed rate limiting through `BUSINESS_DB_QUERY_GUARD_REDIS_URL`.

## Configuration

Create local configuration files:

```powershell
Copy-Item .env.example .env
Copy-Item infrastructure/conf/config_local.yaml.example infrastructure/conf/config_local.yaml
```

Fill real values only in local files such as `.env` and `infrastructure/conf/config_local.yaml`. Repository files should contain only variable names, placeholders, and examples.

Common configuration groups:

- Lark application credentials.
- LLM, embedding, rerank, and optional OCR/VLM services.
- MinIO and Qdrant.
- Agent tool rounds, retrieval thresholds, and Lark worker concurrency.
- Business database MCP and search/web MCP.
- Runtime skill switches.
- Optional SQLite conversation memory persistence.

See [infrastructure/conf/README.md](infrastructure/conf/README.md) for the environment variable list.

## Start Dependencies

Use local MinIO and Qdrant:

```powershell
docker compose up -d
```

You can also point `.env` to existing services.

## Start The Lark Agent

```powershell
python -m app.channels.lark.bot
```

The Lark channel uses a long connection to receive events, so the bot process does not require a public inbound callback endpoint.

## Ingest Documents

Upload local files or directories:

```powershell
python -m ops.scripts.upload_files --path <file-or-directory>
```

Download files from a Lark group:

```powershell
python -m app.channels.lark.download --chat-id <chat-id> --target minio
```

Run the ingestion pipeline:

```powershell
python -m knowledge.ingestion.orchestrator.knowledge_pipeline
```

Write chunks to Qdrant:

```powershell
python -m ops.scripts.chunk_minio_to_qdrant --collection <collection> --prefix <chunk-prefix>
```

Check retrieval from the command line:

```powershell
python -m ops.scripts.recall_cli "<question>" --collection <collection>
```

## Run MCP Services

This repository provides two focused MCP services:

- **Business database MCP**: `inventory_lookup`, `inventory_batch_lookup`, `order_status`, and `product_lookup`.
- **Search/web MCP**: `web_search` and `web_fetch`.

```powershell
python -m infrastructure.mcp.servers.business_db
python -m infrastructure.mcp.servers.web_search
```

MCP URLs, host, port, path, auth, backend connection, and tool allowlists are all configured through environment variables. See [infrastructure/mcp/README.md](infrastructure/mcp/README.md).

## Optional HTTP API

The Lark Agent does not depend on this API, but other systems can use it for recall, embedding, or document conversion:

```powershell
uvicorn app.api.main:app --port <port>
```

## Evaluation

Run Ragas evaluation with a local test set:

```powershell
python -m knowledge.evaluation.run_eval --testset <testset-path> --collection <collection>
```

Example format and metric notes are in [knowledge/evaluation/README.md](knowledge/evaluation/README.md). Real business questions and evaluation outputs should not be committed.

## Testing

```powershell
python -m pytest -q
```

For Windows environments where the default pytest temp directory has permission issues, use a workspace-local base temp:

```powershell
python -m pytest -q --basetemp .pytest_tmp
```

The test suite covers agent tool loops, runtime skill activation, conversation memory, LLM tool-call payloads, document conversion, cleaning, chunking, retrieval, MCP services, business query guards, and architecture boundaries.

## Project Layout

```text
lark-agent/
├── app/
│   ├── assistant/          Agent runtime, tools, runtime skills, memory, prompts
│   ├── channels/lark/      Lark event handling, replies, feedback, file download
│   └── api/                Optional FastAPI endpoints
├── knowledge/
│   ├── ingestion/          Conversion, cleaning, chunking, ingestion orchestration
│   ├── retrieval/          Hybrid recall, filters, rerank, result parsing
│   ├── evaluation/         Ragas evaluation
│   └── utils/              Shared knowledge-processing utilities
├── infrastructure/
│   ├── conf/               Config loading and environment interpolation
│   ├── db/                 MinIO and Qdrant clients
│   ├── model/              LLM, embedding, rerank, OCR clients
│   └── mcp/                MCP services, clients, auth, and config helpers
├── ops/
│   ├── scripts/            Operational command entry points
│   └── docs/               Screenshots and project assets
└── tests/                  Cross-module tests
```

More detailed module notes:

- [app](app/README.md)
- [knowledge](knowledge/README.md)
- [infrastructure](infrastructure/README.md)
- [ops](ops/README.md)
- [tests](tests/README.md)

## Data And Security Boundaries

- Company documents are stored in MinIO; retrieval payloads and vectors are stored in Qdrant.
- Conversation memory is isolated by session and can use in-memory storage or SQLite persistence.
- Business database MCP accepts explicit business parameters and does not expose arbitrary SQL generation.
- Business database MCP tools are exposed only in authorized private chats.
- Web page reading rejects local/private network addresses, credential-bearing URLs, and non-text responses.
- Real connection values and credentials are injected by environment variables and ignored local files.

## Screenshots

Knowledge answers include source paths and feedback controls:

![QA with sources](ops/docs/screenshots/qa-with-sources.jpg)

Questions that do not need tools can be answered directly:

![Direct answer](ops/docs/screenshots/chitchat-handling.png)

## License

[MIT](LICENSE)

