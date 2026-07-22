# Assistant Runtime

`app/assistant` contains the Lark Agent runtime. It connects channels, conversation memory, runtime skills, tools, and answer formatting. The main orchestration is implemented with LangGraph and Function Calling in `agent/graph.py`.

## Files

| Path | Responsibility |
| --- | --- |
| `factory.py` | Runtime assembly entry. Creates the LLM client, retriever, and `AgentService`. |
| `agent/graph.py` | Agent loop: LLM with tools, tool execution, final answer assembly, web fallback, and tool-round limits. |
| `agent/tools/` | Tool abstraction, registry, knowledge search, clock, MCP proxies, web search, and business query guards. |
| `skills/` | Markdown runtime skills and activation logic. Current skill guides business database MCP calls. |
| `qa_service.py` | Shared answer structure, source formatting, and no-answer helpers. |
| `memory.py` | Conversation memory windows for rewrite and answer context, with summary support. |
| `memory_store.py` | Optional SQLite persistence for conversation memory. |
| `llm_client.py` | Chat client with tool-call support and retry handling. |
| `prompts/` | System prompts and prompt builders. |

## Agent Flow

```text
question
  -> build ToolContext
  -> attach runtime skill for this turn when activation rules match
  -> LLM decides whether to call tools
  -> execute selected tools
  -> repeat until no tool call or max rounds
  -> finalize answer and sources
```

The assistant does not run a large fixed intent-classification stage before every request. Function Calling handles most routing, while local code controls tool visibility and hard constraints.

## Runtime Skills

Runtime skills are Markdown files under `skills/`. They are product behavior guides, not secret configuration.

`skills/business_database_mcp.md` describes how the assistant should prepare before calling business database MCP tools:

- Which user requests are inventory, order, or product lookup workflows.
- Which fields must be clarified before tool execution.
- Which identifiers must never be guessed.
- How to answer after the MCP returns rows.
- How to handle empty or ambiguous results.

`skills/business_database.py` decides whether to attach the skill for the current turn. It checks:

- Business keywords such as inventory, stock, order, shipment, product, SKU, and their Chinese equivalents.
- SKU-like or order-number-like identifiers.
- Private Lark chat context.
- User allowlist from environment variables.

The rendered skill is inserted as a temporary system message for one agent run. It is not written to conversation memory, so later turns receive it only if they independently match the activation rules.

## Business Database Tool Boundaries

Business database MCP tools are visible only when the current request is an authorized private-chat request. The assistant sends structured parameters to fixed MCP tools and does not generate SQL.

Before a business database MCP call is sent, `agent/tools/business_guards.py` checks:

- Query time window, default 30 days.
- Per-user rate limit, default 3 calls per 60 seconds.
- Optional Redis-backed rate limiting.
- Basic date-range validity.

These checks remain in code even when the Markdown skill asks the assistant to clarify first.

## Memory

Conversation memory has separate views:

- Rewrite context: short recent history for resolving references such as "that one" or "the previous document".
- Answer context: summary plus recent turns for coherent multi-turn answers.

Runtime skills are intentionally excluded from memory to avoid long-term prompt drift.

