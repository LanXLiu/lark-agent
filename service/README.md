# service — 业务编排

粘合「接入通道」和「RAG 核心」的一层。channel 调 service，service 在进程内直接调用召回引擎，无 HTTP 中转。问答由 `service/agent` 用 LangGraph 编排的 **Agent 工具调用循环（Function Calling）** 驱动。

## 文件

| 文件 | 职责 |
|---|---|
| `agent/graph.py` | **Agent 编排（LangGraph）**。`AgentService.answer()` 跑一张图：`agent`（调 LLM，带 tools）⇄ `execute`（执行 LLM 决定调用的工具）循环 → `finalize`（组装 `QaAnswer`）。LLM 通过原生 Function Calling 自主判断闲聊/是否检索/调几次/换 query/带父子上下文，无前置意图分类。工具轮上限 `RAG_MAX_TOOL_ROUNDS`，末轮 `tool_choice=none` 强制作答；拒答带高分兜底（≥ `RAG_RECALL_QUALITY_MIN` 即作答）。 |
| `agent/tools/` | **工具层（注册表分层）**：`base`（Tool 抽象 + OpenAI schema 生成）、`registry`（`@register_tool` 收集 + 按名分发执行 + 身份注入；内部工具不进 LLM 的 schema）、`search`（search_knowledge，纯召回，`include_context` 映射父子召回）、`clock`（get_current_time）、`web_search`（Tavily 联网，**内部工具**，不给 LLM 平级选，仅在知识库召回不足时由代码降级调用）。新增工具即插即用，不动主图。 |
| `qa_service.py` | **问答工具集**：`QaAnswer` 返回结构、`build_user_prompt`（片段 + 上下文拼 prompt）、`format_answer_with_sources`（答案 + 「文档 › 小标题」/「来源：联网搜索」）、`NO_ANSWER_MARK` / `NO_RECALL_REPLY`（拒答标记与兜底话术）。 |
| `memory.py` | **对话记忆层**（token 预算窗口 + 摘要 + flush 抽事实）。跨通道通用：保留最近对话全文，累计 token 超阈值即把最早的老对话增量压缩成摘要，压缩前先 flush 抽取关键事实并入摘要防丢；`get_for_rewrite`（短历史）与 `get_for_answer`（摘要 + 预算内全文）两个视图；按 `chat:user` 分桶，带 TTL / LRU 上界 / 线程锁；可选 SQLite 持久化（见 `memory_store.py`）。 |
| `memory_store.py` | **对话记忆 SQLite 持久化**（可选，`MEMORY_PERSIST_PATH` 非空时启用）。标准库 `sqlite3`，单文件、零依赖、零运维；启动读回未过期会话、写入落盘，用 wall-clock 时间戳判过期——重启/崩溃不丢多轮上下文。失败只记日志不影响主问答。 |
| `llm_client.py` | LLM 客户端 `BailianChatClient`：`.complete()`（单轮，对话摘要用）与 `.chat(messages, tools, tool_choice)`（多轮 + 原生工具调用，Agent 用，返回含 `tool_calls` 的完整 message）。纯标准库 HTTP，带 429/5xx 退避重试。 |

## 关键返回

`AgentService.answer(question, rewrite_history=..., answer_context=..., user_open_id=..., chat_id=...)` 返回 `QaAnswer`：`answer`（答案）、`hits`（知识库召回片段，供拼来源）、`web_sources`（联网来源）、`no_answer`（是否拒答）、各阶段耗时等——供上层记日志和拼来源。

## 为什么用 Agent 工具调用（而非固定图）

固定直线（改写→召回→生成）每步写死，遇到「先查时间再检索」「一条消息半闲聊半提问」这类需求无法自然处理。Agent 模式把「要不要检索、检索什么、够不够、要不要再搜」的判断权交给 LLM 的 Function Calling：闲聊不调工具直接答，知识问题自主调 `search_knowledge`（可多轮换 query），涉及相对时间先调 `get_current_time`。为控成本/防绕圈，工具轮次设上限并在末轮强制作答；为防「有高分命中却因 LLM 完美主义拒答」，`finalize` 加召回分数阈值兜底。

**降级联网（CRAG 式外部补充）**：`finalize` 判定知识库召回不足（top 分数 < 阈值）且 `RAG_ENABLE_WEB_SEARCH` 开启时，不直接拒答，而由代码降级调用 `web_search`（Tavily）联网查公开知识，再让 LLM 基于联网结果生成答案、标注「来源：联网搜索」并声明「非公司内部规定」。web_search 是内部工具（不进 LLM 的 tool schema），只走降级触发而非 LLM 平级自选——保证「知识库优先、外部兜底」。未配 `TAVILY_API_KEY` 时优雅降级为不可用。

## 记忆为什么分两种视图

改写（指代消解）只需要最近 1-2 轮——「它 / 那个」几乎总指刚说过的东西，带太长反而把检索词带偏；生成答案则用「摘要 + 预算内全文」以求连贯。二者需求不同，故 `memory.py` 提供 `get_for_rewrite`（短）和 `get_for_answer`（摘要 + 预算内全文）两个视图。参数（改写轮数 / 是否开摘要 / 摘要触发 token 阈值 / 摘要 token 上限 / TTL / 会话上限 / SQLite 持久化路径 `MEMORY_PERSIST_PATH`）经 `MEMORY_*` 环境变量配置。

## 记忆为什么摘要前先 flush

摘要是「整段压缩」，容易把具体数字、日期、结论等硬信息糊掉。故在压缩前先做一次 flush：让 LLM 从「将被摘掉的老轮次」里抽取关键事实清单，并入摘要，确保后续追问仍能用到这些确定信息。flush 失败（LLM 不可用等）时直接跳过，不影响摘要主流程。

## 记忆为什么用 SQLite 而非 Redis 持久化

对话记忆本是进程内短期缓存，重启即失。若需「重启/崩溃不丢多轮上下文」，用标准库 `sqlite3`（单文件、零依赖、零运维）即可，无需引入 Redis 那类要独立部署运维的服务——单实例、十余人规模下 SQLite 足够。多实例共享才需要外部存储，届时对外接口不变、仅换 store 后端。

