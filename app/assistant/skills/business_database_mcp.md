---
name: business_database_mcp
version: "0.1"
summary: "Guides the agent before it calls business database MCP tools."
---

# Business Database MCP Skill

This skill is attached only for the current user request when the message looks like a business database query and the runtime context allows business database MCP tools.

It follows the financial_rag-style idea that clarification is an explicit workflow step. Missing business context should be handled before the agent continues to tool execution.

## Scope

Use this skill when the user asks about:

- Inventory, available stock, sellable quantity, warehouse stock, or SKU stock.
- Order status, shipment state, delivery progress, logistics, or order tracking.
- Product, SKU, model, category, or product metadata lookup.

Do not use this skill when the user asks about:

- Company policies, processes, documents, FAQs, or knowledge-base questions.
- Public market, news, or web information.
- Group-chat questions. Business database MCP tools must not be exposed in group chats.

## Runtime Workflow

Before tool exposure:

- Confirm the current chat is a private chat.
- Confirm the current user is allowed by runtime configuration.
- Detect whether the request clearly belongs to one supported business database tool.
- Check whether required parameters are present in the user message or trusted conversation state.
- If required parameters are missing, ask one concise clarification question and do not expose the business database MCP tools.

Before tool call:

- Never invent required identifiers such as SKU, order number, warehouse code, customer name, or date range.
- Prefer exact identifiers over broad keywords.
- Use structured MCP arguments only.
- Never generate SQL.
- Keep the requested date range within the configured maximum window.
- Let code guards enforce permission, group-chat blocking, rate limit, date-window checks, and parameter legality.

After tool call:

- Answer from returned rows only.
- If rows are empty, say no matching business data was found and mention the exact filter used.
- If the result looks ambiguous, ask the user to narrow the identifier, warehouse, customer, or date range.
- Do not expose internal API URLs, environment variable names, or backend implementation details to end users.

## Hard Constraints

- `no_sql_generation`: true
- `max_window_days`: 30
- `rate_limit`: 3 calls per 60 seconds
- Hard guard environment:
  - `BUSINESS_DB_MCP_ALLOWED_USERS`
  - `BUSINESS_DB_QUERY_MAX_WINDOW_DAYS`
  - `BUSINESS_DB_QUERY_RATE_LIMIT_COUNT`
  - `BUSINESS_DB_QUERY_RATE_LIMIT_WINDOW_SECONDS`
- Never guess:
  - `sku`
  - `skus`
  - `order_no`
  - `warehouse_code`
  - `customer_name`
  - `start_date`
  - `end_date`

## Clarification Style

- Ask at most one question per turn.
- Ask for the most discriminating missing field first.
- Keep the question concise.

Examples:

- Missing `sku`: 请提供要查询的商品编码或 SKU。
- Missing `order_no`: 请提供订单号，我再帮你查询订单状态。
- Missing `date_range`: 请补充要查询的开始日期和结束日期，时间跨度最多 30 天。
- Too broad product keyword: 这个商品描述比较宽泛，请补充更具体的产品名称、SKU 或分类。

## Tool Selection

Priority:

1. `order_status`
2. `inventory_batch_lookup`
3. `inventory_lookup`
4. `product_lookup`

Tie breaking:

- If an exact order number is present and the user asks about shipping, delivery, status, or progress, choose `order_status`.
- If two or more SKU-like identifiers are present and the user asks about stock, choose `inventory_batch_lookup`.
- If one SKU-like identifier is present and the user asks about stock, choose `inventory_lookup`.
- If the user asks what a product is, whether it exists, or asks by product name/category without stock intent, choose `product_lookup`.

## Tool: inventory_lookup

Purpose: Query current inventory for one SKU, optionally in one warehouse.

Intent keywords:

- 库存
- 现货
- 可售
- 仓库
- stock
- inventory

Required fields:

- `sku`

Optional fields:

- `warehouse_code`

Clarification:

- Missing `sku`: 请提供要查询的商品编码或 SKU。
- Ambiguous warehouse: 是否需要指定仓库？如果不指定，我会按默认仓库范围查询。

Constraints:

- Do not call this tool with only a product category.
- Do not convert a vague product name into a fake SKU.
- If the user provides a product name instead of SKU, prefer `product_lookup` first unless the name is exact enough.

Good examples:

- User: 查一下 SKU-10086 的库存
  Arguments: `{"sku": "SKU-10086"}`
- User: 华东仓 SKU-9A12 还有多少现货
  Arguments: `{"sku": "SKU-9A12", "warehouse_code": "华东仓"}`

Clarify examples:

- User: 帮我查一下库存
  Ask: 请提供要查询的商品编码或 SKU。
- User: 这个产品还有货吗
  Ask: 请提供具体产品名称、商品编码或 SKU。

## Tool: inventory_batch_lookup

Purpose: Query current inventory for several SKU codes.

Intent keywords:

- 批量库存
- 多个 SKU
- 这些 SKU
- batch inventory

Required fields:

- `skus`

Optional fields:

- `warehouse_code`

Parameter rules:

- `skus` must contain 2 to 50 items.

Clarification:

- Missing `skus`: 请提供要批量查询的 SKU 列表。
- Not enough SKUs: 批量库存查询至少需要 2 个 SKU；如果只查一个，我会按单个库存查询处理。

Constraints:

- Keep user-provided SKU order when building arguments.
- Do not split natural-language product descriptions into invented SKU values.

## Tool: order_status

Purpose: Query the current state and milestones of an order.

Intent keywords:

- 订单
- 发货
- 物流
- 签收
- 状态
- order
- shipment
- delivery

Required fields:

- `order_no`

Clarification:

- Missing `order_no`: 请提供订单号，我再帮你查询订单状态。

Constraints:

- Use this tool only with an exact order number.
- If the user asks by customer/date instead of order number, ask for the order number in this first version.
- Do not infer an order number from nearby unrelated digits.

Good examples:

- User: 订单 SO20260722001 发货了吗
  Arguments: `{"order_no": "SO20260722001"}`

Clarify examples:

- User: 帮我看下这个客户的订单到哪了
  Ask: 请提供订单号，我再帮你查询订单状态。

## Tool: product_lookup

Purpose: Find products by name, SKU, or keyword.

Intent keywords:

- 商品
- 产品
- SKU
- 型号
- 类目
- product

Required fields:

- `keyword`

Optional fields:

- `category`

Clarification:

- Missing `keyword`: 请提供产品名称、SKU、型号或更具体的关键词。
- Too broad `keyword`: 这个产品关键词比较宽泛，请补充更具体的名称、SKU、型号或分类。

Constraints:

- Do not call this tool with generic words like 商品, 产品, 东西, 配件 as the only keyword.
- If the user ultimately wants stock and `product_lookup` finds one exact SKU, the agent may call `inventory_lookup` next.

Good examples:

- User: 查一下 A100-黑色 这个产品
  Arguments: `{"keyword": "A100-黑色"}`
- User: 找一下耗材类里的热敏纸
  Arguments: `{"keyword": "热敏纸", "category": "耗材"}`

Clarify examples:

- User: 帮我查个产品
  Ask: 请提供产品名称、SKU、型号或更具体的关键词。

## Answer Policy

Include:

- The key identifier used in the query.
- Important returned fields such as quantity, warehouse, status, timestamp, or product name when present.
- A short note when filters were applied.

Avoid:

- Claiming data exists when the MCP returned no rows.
- Explaining internal guard logic unless the user needs to adjust the request.
- Mentioning that tools were hidden because of permission checks.

