# lark-rag

飞书 / Lark 知识库 RAG 机器人：把企业文档（飞书云文档 / PDF / Word / PPT / Excel / 图片）转成 Markdown、清洗、切片、向量化入库，并通过**飞书机器人**提供带引用来源的知识库问答。

机器人进程内直接调用召回引擎，单进程即可完成「收消息 → 召回 → 生成 → 回复」，无需额外的召回服务。

## 设计理念

```
接入通道 channels/        →   业务编排 service/        →   RAG 引擎
  lark（飞书机器人）             agent（Agent 工具调用）      recall / chunker / model / db ...
  (企微 / web 可扩展)
```

- **RAG 引擎**是稳定的核心（召回、入库、模型、存储）；
- **飞书是一个可插拔的接入通道**，以后加企微 / 网页只需在 `channels/` 下新增，不动核心；
- **service 层**把通道和引擎粘合：问答编排在进程内直接调用召回，无网络中转。

## 两条数据流

**入库流**（文档进知识库）：
```
飞书群文档 → channels/lark/download（docx 取飞书原生 markdown）→ MinIO raw/
          → orchestrator 管线：转换 → 清洗 → 切片（带 breadcrumb）→ MinIO chunk/
          → 向量化（dense embedding + BM25）→ 写入 Qdrant
```

**问答流**（用户提问）：
```
私聊直接发问题 / 群里 @机器人 → channels/lark/bot（收消息 / 去重 / 快速 ack / 贴 OK 表情）
            → 入有界队列削峰 → 固定 worker 用单例 Agent 服务处理
            → service/agent：基于 LangGraph 的 Agent 工具调用循环（Function Calling）
                ① LLM 自主判断：闲聊 / 问机器人自身 → 不调工具、直接作答
                ② 知识类问题 → LLM 自主调用工具（原生 Function Calling）：
                     · search_knowledge（混合召回 + rerank + 父子召回；父子召回由 LLM 按需开关）
                     · get_current_time（涉及「最新/本月」等相对时间时先取时间基准）
                ③ LLM 自主决定：结果不够 → 换 query 再检索（工具轮上限可配）
                ④ 生成：依据检索片段作答；无相关内容则拒答（分数阈值兜底：有高分命中即作答）
                ⑤ 降级联网（可选，默认开）：知识库召回不足时降级调 web_search（Tavily）
                     用公开资料作答、标注「来源：联网搜索」，并声明「非公司内部规定」
                （对话记忆：service/memory token 预算窗口 + 摘要，多轮改写由 LLM 看历史自行完成）
            → 回复：答案 + 引用来源（知识库「文档 › 小标题」/ 联网「来源：联网搜索」）+ 👍/👎 反馈按钮
            → 落 qa_trace 日志
```

## 目录结构

```text
lark-rag/
├── channels/                 接入通道
│   └── lark/                 飞书机器人通道
│       ├── bot.py            长连接入口（收消息、分发、RAG 触发、卡片回调）
│       ├── lark_api.py       飞书 OpenAPI 封装（发消息 / 表情 / 原生 markdown / 导出）
│       ├── download.py       下载群文档 / 附件 → MinIO
│       ├── lark_markdown.py  飞书原生 markdown 清洗（反转义 + HTML 表格转 md）
│       ├── feedback.py       👍/👎 反馈卡片 + 落盘
│       ├── source_names.py   飞书 ID → 群名 / 文档名（带缓存）
│       ├── observability.py  问答结构化日志（QaTrace）
│       └── minio_uploader.py / lark_config.py / relay.py / send_message.py
├── service/                  业务编排
│   ├── agent/                Agent 工具调用层：LangGraph 编排 Function Calling
│   │   ├── graph.py         Agent 状态图 + AgentService：agent ⇄ execute 工具循环 → finalize
│   │   └── tools/           工具层（注册表分层）：base / registry / search_knowledge / get_current_time / web_search（降级联网，内部工具）
│   ├── qa_service.py         问答编排工具：QaAnswer、prompt 构造、来源拼装
│   ├── memory.py             对话记忆（token 预算窗口 + 摘要 + flush 抽事实，跨通道通用）
│   ├── memory_store.py       对话记忆 SQLite 持久化（可选，重启不失忆）
│   └── llm_client.py         LLM 客户端（complete + 支持工具调用的 chat，带退避重试）
├── recall/                   混合召回（dense+BM25 RRF → rerank → 父子召回 → 阈值过滤）
├── chunker/                  切片（markdown_structure 等，带 breadcrumb 层级；表格按行原子化）
├── converter/                各格式转换器（docx / excel / pdf / pptx / image / json）
├── file_to_markdown/         转 Markdown 核心（VLM / OCR / 表格渲染 / 后处理）
├── cleans/                   清洗管线
├── orchestrator/             入库管线编排（raw → md → chunk → qdrant，三态机 + 断点续传）
├── model/                    embedding / rerank / llm / ocr 客户端
├── db/                       minio / qdrant 连接
├── utils/                    sparse 向量 / payload 构造 / breadcrumb / LSH 去重 / 退避重试
├── api/                      HTTP 接口（recall / embed / convert / health，可选起）
├── conf/                     配置（config_local.yaml 本地含密钥，已 gitignore）
├── scripts/                  recall_cli / qa_stats / upload_files / chunk_minio_to_qdrant / init_collections
├── docker-compose.yml        一键起 MinIO / Qdrant
├── requirements.txt
└── .env.example              飞书凭证 / 密钥等环境变量模板
```

## 模型与存储

| 用途 | 用什么 |
|---|---|
| 问答生成 + Agent 工具调用 + 对话摘要 | `deepseek-v4-pro`（百炼） |
| embedding（dense） | `text-embedding-v3`（百炼，1024 维） |
| sparse | BM25（`Qdrant/bm25`，本地 fastembed） |
| rerank | `qwen3-vl-rerank`（百炼） |
| 向量库 / 对象存储 | Qdrant / MinIO |

LLM / embedding / rerank 均通过 OpenAI 兼容接口远程调用（百炼，或 Xinference / Ollama / vLLM 等自建网关），在 `conf/config_local.yaml` 的 `MODELS` 段配置 `url` / `api_key` / `model`。sparse 向量用本地 fastembed BM25（轻量，无需 GPU）。

## 核心特性

- **多入口接入**：私聊直接发问题即答（一对一无需 @）；群聊需 @机器人才触发（避免刷屏）；消息去重防重复回复；
- **Agent 工具调用（LangGraph + Function Calling）**：问答由 LangGraph 编排的 Agent 思考-行动循环驱动——LLM 通过原生 Function Calling **自主判断**是否闲聊（不调工具直接答）、是否检索、调几次、要不要换 query 再搜、要不要带父子上下文，而非固定直线流程；工具以注册表分层组织（`service/agent/tools/`），新增工具即插即用；
- **无前置分类，混合消息友好**：不用独立分类器预判意图——闲聊 / 问机器人自身由 LLM 自主判断（不调工具直接答），「既有闲聊又有知识问题」的消息也能分别处理；工具轮次有上限（`RAG_MAX_TOOL_ROUNDS`）防绕圈；
- **混合召回**：dense + BM25 → RRF 融合 → cross-encoder 精排 → 阈值（0.68）过滤；
- **父子召回**：问父标题（如「第四层架构」）自动带出其下子层（L1~L5）；由 LLM 按问题类型自主开关（`include_context` 工具参数）；
- **拒答 + 高分兜底**：检索片段不相关时拒答、不显示来源；但只要召回存在高分命中（≥ 0.68）即基于现有内容作答，避免「搜到高分却拒答」；
- **降级联网搜索（CRAG 式外部补充）**：知识库召回不足时，可降级调 web_search（Tavily）联网查公开知识，答案标注「来源：联网搜索」并声明「非公司内部规定」，划清内外知识边界；由 `RAG_ENABLE_WEB_SEARCH` 开关控制、未配 `TAVILY_API_KEY` 时优雅降级——兼顾知识覆盖与数据主权；
- **带定位的引用来源**：回复附「文档 › 小标题」的来源，去重截断，一眼定位又不臃肿；
- **多轮对话记忆**：token 预算窗口（保留最近对话全文，累计 token 超阈值即把最早的老对话增量摘要）+ 摘要，在有限 token 内支持长对话；**摘要前先 flush 抽取关键事实**（数字/日期/结论）并入摘要，防压缩丢硬信息；改写用短历史做指代消解、生成用「摘要 + 预算内全文」保连贯，按用户在群内隔离，带 TTL / LRU 上界；**可选 SQLite 持久化**（`MEMORY_PERSIST_PATH`）——重启/崩溃不丢多轮上下文，零依赖零运维；
- **飞书原生 markdown 入库**：云文档直接取飞书 markdown（标题 / 表格结构保真），优于有损的 docx 转换；
- **表格原子化切片**：markdown 管道表格（`| 列 | 列 |`）按「表头 + 每行」拆成独立 chunk，每行渲染成「字段：值」（如「姓名：张三 状态：已审批」）——单行脱离表格仍带列含义、便于精准检索，大表格也不会被从中间切断（`table_pipe_atomic` 可配）；
- **👍/👎 反馈**：群聊多人各记一份，落盘供统计；
- **可观测**：每次问答记 qa_trace，`scripts/qa_stats` 出报表；
- **并发兜底**：有界队列 + 固定 worker 削峰，过载时优雅拒绝而非拖垮进程；单例图服务跨线程复用（`RAG_WORKER_COUNT` / `RAG_QUEUE_MAXSIZE` 可配）；
- **容错**：打百炼的调用带 429/5xx 指数退避重试、向量库抖动自动重试、召回失败重试、摘要/联网失败兜底、message_id 去重防重复回复。

## 快速开始

### 1. 安装

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux/macOS 用 source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 起依赖服务

需要可访问的 MinIO / Qdrant。本地开发可用自带的 compose 一键起：

```bash
docker compose up -d
```

### 3. 配置

- **环境变量**：复制 `.env.example` 为 `.env`，填入飞书凭证（`LARK_APP_ID` / `LARK_APP_SECRET`）、百炼 key（`BAILIAN_API_KEY`）、以及 Qdrant / MinIO 的连接信息。
- **核心配置**：复制 `conf/config_local.yaml.example` 为 `conf/config_local.yaml`。文件里的密钥 / 主机 / 端口写成 `${VAR}` 占位符，运行时从环境变量注入——**仓库里不出现任何明文密钥**；敏感项缺失会直接报错。

### 4. 运行

**启动飞书机器人（单进程问答）：**
```bash
python -m channels.lark.bot
```

**下载群文档到 MinIO：**
```bash
python -m channels.lark.download --chat-id <oc_xxx> --target minio
```

**上传本地/服务器文件到 MinIO（不经飞书，适合服务器批量灌库）：**
```bash
python -m scripts.upload_files --path ./docs                        # 递归上传整个目录
python -m scripts.upload_files --path ./a.pdf --collection knowledgebase
python -m scripts.upload_files --path ./docs --dry-run              # 只看将上传什么
```
文件落到 `raw/<collection>/upload/...`，之后与飞书来的文件走完全相同的入库流程。

**入库（切片 + 向量化）：**
```bash
python -m orchestrator.knowledge_pipeline                                                   # 转换 + 切片到 MinIO
python -m scripts.chunk_minio_to_qdrant --collection knowledgebase --prefix chunk/...        # 向量化入 Qdrant
```

**验证召回：**
```bash
python -m scripts.recall_cli "你的问题" --collection knowledgebase
```

**可选：单独起 HTTP API（给外部调用）：**
```bash
uvicorn api.main:app --port 8010
```

## 部署到服务器

机器人通过飞书长连接（websocket）主动连接飞书开放平台接收事件，**不需要公网入站端口、不依赖内网穿透**，因此直接部署在任意能出网的服务器上即可。

```bash
# 1. 拉代码、装依赖
git clone <your-repo-url> && cd lark-rag
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 起依赖服务（或指向已有的 Qdrant/MinIO）
docker compose up -d

# 3. 配置：填 .env 与 conf/config_local.yaml（把各 ${VAR} 指向服务器上的实例地址）
cp .env.example .env && cp conf/config_local.yaml.example conf/config_local.yaml

# 4. 常驻运行（示例：systemd / supervisor / nohup 任选其一）
nohup python -m channels.lark.bot > logs/bot.log 2>&1 &
```

生产环境建议用 `systemd` 或 `supervisor` 托管进程（自动拉起 + 日志轮转），并把 `.env` 权限设为仅属主可读。

## 许可证

[MIT](LICENSE)
