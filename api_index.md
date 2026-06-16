# API 参考

Base URL 默认为 `http://127.0.0.1:8000`（Android 客户端在 `app/build.gradle.kts` 的 `API_BASE_URL` 中单独配置）。除 SSE 聊天接口外，其余均为标准 JSON REST API。

## 目录

- [健康检查](#健康检查)
- [聊天 SSE](#聊天-sse)
- [商品详情](#商品详情)
- [购物车](#购物车)
- [静态资源](#静态资源)
- [数据模型](#数据模型)
- [Agent 工具](#agent-工具)
- [错误说明](#错误说明)

## 会话 ID 约定

- 客户端（Android）在本地生成 `conversation_id`（UUID），聊天与购物车请求均携带。
- 服务端 `get_or_create_id()` 接受客户端传入的 ID；若该 ID 尚无历史，则创建空会话。
- **SSE 流不会回传** `conversation_id`；客户端需自行持久化。
- 服务端会话历史、购物车、近期展示商品池均按此 ID 隔离，**进程内存存储**，重启后丢失。

---

## 健康检查

### `GET /health`

服务存活探针。

**响应 200**

```json
{"status": "ok"}
```

---

## 聊天 SSE

### `POST /api/chat`

发起一轮对话，响应为 **Server-Sent Events** 流（`text/event-stream`）。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户消息，至少 1 个字符 |
| `conversation_id` | string | 否 | 会话 ID；省略则服务端生成新 ID |

**请求示例**

```json
{
  "message": "推荐一款适合油皮的洗面奶",
  "conversation_id": "a1b2c3d4e5f6"
}
```

**curl 示例**

```bash
curl -N -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"200元以下的蓝牙耳机有哪些？"}'
```

### SSE 事件类型

每条 SSE 消息包含 `event` 与 `data` 字段。`data` 为 JSON 字符串。

#### `status` — 进度状态

Agent 执行检索或整理回复时推送。

```json
{
  "phase": "retrieving",
  "message": "正在检索商品...",
  "step": 1,
  "total_steps": 4
}
```

| `phase` 值 | 含义 |
|------------|------|
| `retrieving` | 向量检索中（step 1/4） |
| `filtering` | 库存/价格过滤中（step 2/4） |
| `composing` | 整理推荐结果（step 3/4） |
| `streaming` | 流式输出最终回复（可能是普通文本、推荐或对比） |
| `cart` | 购物车工具执行中（无 step 序号） |

购物车工具执行时 `message` 为「正在更新购物车...」或「正在读取近期商品...」（`list_recent_products`）。

#### `message_start` — 临时回复开始

服务端开始一次最终回复尝试时推送。客户端应按 `message_id` 创建或清空临时消息，并只接收相同 `attempt_id` 的后续 `block`。

```json
{
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "provisional": true
}
```

#### `message_reset` — 临时回复回滚

当前尝试的模型输出解析失败、需要重试或终止时推送。客户端应清空该 `message_id` 已展示的临时内容。

```json
{
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "reason": "retry"
}
```

#### `message_commit` — 临时回复提交

最终回复解析通过后推送。客户端应将该 `message_id` 的临时内容标记为正式内容；服务端也会在此时把已提交的商品卡片写入近期展示商品池。

```json
{
  "message_id": "asst-abc123",
  "attempt_id": "attempt-2"
}
```

#### `block` — 消息内容块

`data.type` 区分块类型：

**`text`** — 完整文本块

```json
{
  "type": "text",
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "block_id": "blk-001",
  "content": "你更看重控油还是保湿？"
}
```

**`text_delta`** — 流式文本增量

```json
{
  "type": "text_delta",
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "block_id": "blk-002",
  "content": "推荐"
}
```

**`product`** — 商品卡片

```json
{
  "type": "product",
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "block_id": "blk-003",
  "group": "防晒护肤",
  "product": {
    "product_id": "p_beauty_001",
    "title": "清爽防晒乳",
    "category": "美妆护肤",
    "price": 89.0,
    "brand": "示例品牌",
    "image_url": "/assets/beauty/images/p_beauty_001_live.jpg",
    "stock": 12,
    "stock_status": "in_stock",
    "highlights": ["轻薄不油腻"],
    "detail_url": "/api/products/p_beauty_001"
  }
}
```

> `product` block 在 provisional 阶段可先展示；只有收到对应 `message_commit` 后，服务端才会将该商品写入会话「近期展示商品池」。后续 Agent 加购与 REST 加购均依赖此池。

**推荐类回复的 block 顺序**（intro → 每个商品的 product + reason → outro）：

```text
block type=text      ← intro
block type=product   ← 商品 1
block type=text      ← 商品 1 推荐理由
block type=product   ← 商品 2
block type=text      ← 商品 2 推荐理由
block type=text      ← outro（可选）
```

流式场景下 intro/reason/outro 以 `text_delta` 增量推送；`product` 在解析到 `<ITEM>` 后立即整卡推送。

**`compare`** — 结构化对比表

```json
{
  "type": "compare",
  "message_id": "asst-abc123",
  "attempt_id": "attempt-1",
  "block_id": "blk-004",
  "compare": {
    "products": [
      {"product_id": "p1", "title": "商品 A"},
      {"product_id": "p2", "title": "商品 B"}
    ],
    "rows": [
      {
        "dimension": "价格",
        "values": {"p1": "¥199", "p2": "¥299"}
      }
    ]
  }
}
```

#### `cart` — 购物车快照

Agent 执行购物车工具成功后推送，结构与 [CartSnapshot](#cartsnapshot) 一致（含 `conversation_id`）。

#### `done` — 本轮结束

```json
{}
```

#### `error` — 错误

```json
{
  "message": "服务处理失败，请稍后重试。"
}
```

常见错误消息：

| 消息 | 场景 |
|------|------|
| `模型输出连续异常，已停止本轮回复，请稍后重试。` | Agent 恢复重试次数耗尽 |
| `服务处理失败，请稍后重试。` | 未预期服务端异常 |

### 客户端断开

客户端断开连接时，服务端取消 LLM 调用并停止推送，**不再发送 `done`**。最终回复只有在 `message_commit` 后写入会话历史；未提交的临时内容不会进入历史。

---

## 商品详情

### `GET /api/products/{product_id}`

查询单个商品详情。

**路径参数**

| 参数 | 说明 |
|------|------|
| `product_id` | 商品 ID，如 `p_food_001` |

**响应 200** — [ProductDetail](#productdetail)

**响应 404**

```json
{"detail": "商品不存在。"}
```

---

## 购物车

所有购物车接口通过 `conversation_id` 隔离会话。省略时服务端自动生成新 ID 并返回在响应体中。

### `GET /api/cart`

获取购物车快照。

**Query 参数**

| 参数 | 类型 | 必填 |
|------|------|------|
| `conversation_id` | string | 否 |

**响应 200** — [CartSnapshot](#cartsnapshot)

### `POST /api/cart/items`

添加商品到购物车。

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `conversation_id` | string | 否 | 会话 ID |
| `product_id` | string | 是 | 商品 ID |
| `quantity` | integer | 否 | 数量，默认 1，最小 1 |

**响应 200** — [CartSnapshot](#cartsnapshot)

**响应 404** — 商品不在近期展示池，或商品不存在

**响应 409** — 商品已下架或库存不足

**响应 422** — 数量参数非法（如 quantity < 1）

### `PATCH /api/cart/items/{product_id}`

修改购物车中某商品数量。

**路径参数**：`product_id`

**请求体**

| 字段 | 类型 | 必填 |
|------|------|------|
| `conversation_id` | string | 否 |
| `quantity` | integer | 是，≥ 1 |

**响应 200** — [CartSnapshot](#cartsnapshot)

**响应 404** — 购物车中不存在该商品

**响应 409** — 库存不足

**响应 422** — 数量非法

### `DELETE /api/cart/items/{product_id}`

从购物车删除指定商品。

**Query 参数**：`conversation_id`（可选）

**响应 200** — [CartSnapshot](#cartsnapshot)

**响应 404** — 购物车中不存在该商品

### `DELETE /api/cart`

清空购物车。

**Query 参数**：`conversation_id`（可选）

**响应 200** — [CartSnapshot](#cartsnapshot)

---

## 静态资源

### `GET /assets/{path}`

挂载 `ecommerce_agent_dataset/` 目录，提供商品图片等静态文件。

示例：`GET /assets/beauty/images/p_beauty_001_live.jpg`

---

## 数据模型

定义于 `server/schemas.py`。

### StockStatus

```text
"in_stock" | "low_stock" | "out_of_stock" | "inactive"
```

| 值 | 条件 |
|----|------|
| `in_stock` | 上架且库存 > 3 |
| `low_stock` | 上架且 1 ≤ 库存 ≤ 3 |
| `out_of_stock` | 库存 ≤ 0 |
| `inactive` | 已下架 |

### Product

商品卡片字段（推荐流、购物车条目基类）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `product_id` | string | 商品 ID |
| `title` | string | 标题 |
| `category` | string | 类目 |
| `price` | number | 当前价格 |
| `brand` | string \| null | 品牌 |
| `sub_category` | string \| null | 子类目 |
| `image_url` | string \| null | 图片 URL |
| `stock` | integer \| null | 库存 |
| `detail_url` | string \| null | 详情 API 路径 |
| `landing_url` | string \| null | 落地页链接 |
| `highlights` | string[] | 卖点摘要 |
| `stock_status` | StockStatus | 库存状态 |
| `unavailable_reason` | string \| null | 不可购买原因 |
| `group_label` | string \| null | 组合推荐分组标签 |

### ProductDetail

继承 `Product`，额外字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `description` | string | 商品描述 |
| `specs` | `{name, value}[]` | 规格列表 |
| `faq` | `{question, answer}[]` | 官方 FAQ |
| `review_summary` | ProductReviewSummary | 评价摘要 |

**ProductReviewSummary**

| 字段 | 类型 |
|------|------|
| `average_rating` | number \| null |
| `total_count` | integer |
| `highlights` | string[] |

### CartItem

继承 `Product`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `quantity` | integer | 数量，≥ 1 |
| `is_active` | boolean \| null | 是否仍上架 |
| `unavailable_reason` | string \| null | 不可用原因 |

### CartSnapshot

| 字段 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | string | 会话 ID |
| `items` | CartItem[] | 购物车条目 |
| `total_quantity` | integer | 商品总件数 |
| `total_price` | number | 合计金额 |
| `messages` | string[] | 业务提示：价格变动、自动移除下架/已删商品等 |

### ChatRequest

| 字段 | 类型 | 必填 |
|------|------|------|
| `message` | string | 是 |
| `conversation_id` | string \| null | 否 |

### AddCartItemRequest

| 字段 | 类型 | 必填 |
|------|------|------|
| `conversation_id` | string \| null | 否 |
| `product_id` | string | 是 |
| `quantity` | integer | 否，默认 1 |

### UpdateCartItemRequest

| 字段 | 类型 | 必填 |
|------|------|------|
| `conversation_id` | string \| null | 否 |
| `quantity` | integer | 是 |

---

## Agent 工具

以下工具由 LLM 在对话中调用，**不直接暴露为 HTTP 接口**。此处供联调与扩展参考。

### `retrieve_products`

根据一个或多个检索子需求召回商品。

**参数 `requests[]`**

| 字段 | 类型 | 说明 |
|------|------|------|
| `label` | string | 子需求名称（组合推荐分组） |
| `search_query` | string | 改写后的检索语句 |
| `category` | enum | `服饰运动` / `美妆护肤` / `数码电子` / `食品饮料` |
| `min_price` / `max_price` | number | 价格区间 |
| `must_have_terms` | string[] | 必须包含的属性 |
| `exclude_terms` | string[] | 需排除的属性 |
| `exclude_brands` | string[] | 需排除的品牌 |

**返回**：按 request 分组的 Top-K 商品列表。

### 购物车工具

| 工具名 | 说明 |
|--------|------|
| `add_to_cart` | 批量加购，参数 `product_ids[]`、`quantity` |
| `remove_from_cart` | 删除，支持 `product_id` / `cart_position` / `title_keyword` |
| `update_cart_item` | 改量，定位方式同上 + `quantity` |
| `view_cart` | 查看购物车 |
| `clear_cart` | 清空 |
| `list_recent_products` | 列出本会话近期展示商品（最多 20 个） |

---

## 错误说明

### HTTP 状态码

| 状态码 | 场景 |
|--------|------|
| 200 | 成功 |
| 404 | 商品不存在；加购时商品不在近期展示池；购物车条目不存在 |
| 409 | 商品已下架或库存不足 |
| 422 | 请求体验证失败（Pydantic）；购物车数量非法 |
| 500 | 未捕获服务端异常 |

### 运行时前置条件

| 错误 | 原因 | 处理 |
|------|------|------|
| `缺少 ARK_API_KEY` | 未配置 LLM Key | 在 `.env` 中设置 |
| `商品向量库为空` | ChromaDB 未索引 | 运行 `python ingest.py` |
| `未在数据集目录中找到商品 JSON` | 数据集缺失 | 确认 `ecommerce_agent_dataset/` 存在 |

---

## 交互示例

### 完整 SSE 会话（简化）

```text
event: status
data: {"phase":"retrieving","message":"正在检索商品...","step":1,"total_steps":4}

event: status
data: {"phase":"filtering","message":"正在筛选库存和价格...","step":2,"total_steps":4}

event: status
data: {"phase":"composing","message":"正在整理推荐...","step":3,"total_steps":4}

event: status
data: {"phase":"streaming","message":"正在输出回复...","step":null,"total_steps":null}

event: message_start
data: {"message_id":"asst-...","attempt_id":"attempt-1","provisional":true}

event: block
data: {"type":"text_delta","message_id":"asst-...","attempt_id":"attempt-1","block_id":"blk-1","content":"整体"}

event: block
data: {"type":"product","message_id":"asst-...","attempt_id":"attempt-1","block_id":"blk-2","product":{...}}

event: block
data: {"type":"text_delta","message_id":"asst-...","attempt_id":"attempt-1","block_id":"blk-3","content":"理由"}

event: message_commit
data: {"message_id":"asst-...","attempt_id":"attempt-1"}

event: done
data: {}
```

### REST 加购流程

```bash
# 1. 先通过聊天获得 conversation_id 并展示商品卡片
# 2. 加购
curl -X POST http://127.0.0.1:8000/api/cart/items \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"YOUR_CONV_ID","product_id":"p_food_001","quantity":1}'

# 3. 查看购物车
curl "http://127.0.0.1:8000/api/cart?conversation_id=YOUR_CONV_ID"
```
