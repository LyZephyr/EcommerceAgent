# API Index

本文档索引当前项目的 HTTP API、SSE 事件、数据结构、Agent 工具和核心代码接口。

## HTTP API

服务入口：`server/main.py`

默认本地地址示例：`http://127.0.0.1:8000`

### `GET /health`

健康检查。

响应：

```json
{"status": "ok"}
```

### `POST /api/chat`

聊天接口，返回 Server-Sent Events。

请求模型：`schemas.ChatRequest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `message` | `string` | 是 | 用户消息，最小长度 1 |
| `conversation_id` | `string | null` | 否 | 会话 ID；为空时服务端会创建内存会话，但当前 SSE 不回传新 ID |

请求示例：

```json
{
  "conversation_id": "demo",
  "message": "推荐几款适合早餐的咖啡"
}
```

响应：`text/event-stream`

可能事件见 [SSE 事件](#sse-事件)。

### `GET /api/products/{product_id}`

读取商品详情。

响应模型：`schemas.ProductDetail`

错误：

| 状态码 | 条件 | 响应 detail |
| --- | --- | --- |
| `404` | 商品不存在 | `商品不存在。` |

### `GET /api/cart`

读取购物车快照。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | `string | null` | 否 | 会话 ID；为空时创建新内存会话 |

响应模型：`schemas.CartSnapshot`

### `POST /api/cart/items`

向购物车加商品。

请求模型：`schemas.AddCartItemRequest`

| 字段 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `conversation_id` | `string | null` | 否 | `null` | 会话 ID |
| `product_id` | `string` | 是 | 无 | 商品 ID |
| `quantity` | `integer` | 否 | `1` | 加购数量，最小 1 |

响应模型：`schemas.CartSnapshot`

业务约束：

- 商品必须在当前会话近期展示商品池中。
- 商品必须存在、上架且库存大于 0。
- 购物车中该商品最终数量不能超过库存。

错误：

| 状态码 | 条件 |
| --- | --- |
| `404` | 商品不存在，或商品不在当前会话近期展示商品池中 |
| `409` | 商品下架或库存不足 |
| `422` | 数量小于 1 |

### `PATCH /api/cart/items/{product_id}`

修改购物车商品数量。

请求模型：`schemas.UpdateCartItemRequest`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | `string | null` | 否 | 会话 ID |
| `quantity` | `integer` | 是 | 目标数量，最小 1 |

响应模型：`schemas.CartSnapshot`

错误：

| 状态码 | 条件 |
| --- | --- |
| `404` | 购物车中不存在该商品 |
| `409` | 商品下架或库存不足 |
| `422` | 数量小于 1 |

### `DELETE /api/cart/items/{product_id}`

删除购物车商品。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | `string | null` | 否 | 会话 ID |

响应模型：`schemas.CartSnapshot`

错误：

| 状态码 | 条件 |
| --- | --- |
| `404` | 购物车中不存在该商品 |

### `DELETE /api/cart`

清空购物车。

查询参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `conversation_id` | `string | null` | 否 | 会话 ID |

响应模型：`schemas.CartSnapshot`

### `GET /assets/{path}`

静态资源接口，由 `StaticFiles(directory=DATASET_DIR)` 挂载。

商品图片示例：

```text
/assets/food/images/p_food_001_live.jpg
```

## SSE 事件

SSE 映射位置：`server/sse/mapper.py`

每个事件由 `event` 和 JSON 字符串 `data` 组成。

### `status`

结构化进度。

```json
{
  "phase": "retrieving",
  "message": "正在检索商品...",
  "step": null,
  "total_steps": null
}
```

已使用的 phase 包括：

- `retrieving`
- `filtering`
- `cart`
- `composing`
- `streaming`

Android 初始本地状态还使用 `preparing`。

### `message_start`

一条 assistant 消息开始。

```json
{
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "provisional": true
}
```

### `message_reset`

当前 attempt 失败并清空重试。

```json
{
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "reason": "retry"
}
```

`reason` 可能是：

- `retry`：模型输出校验失败，清空当前 attempt 后重试。
- `error`：恢复次数耗尽，清空当前 attempt 后返回错误。
- `tool_call_after_text`：模型先输出了 provisional 正文、随后又生成工具调用；服务端清空 provisional 正文并改走工具流程。

### `message_commit`

assistant 消息成功提交。

```json
{
  "message_id": "asst-...",
  "attempt_id": "attempt-2"
}
```

`MessageCommitEvent.recent_products` 使用 `RecentProductEntry` typed contract。
`api.chat.iter_chat_sse_events()` 在处理该事件时会把本次成功推荐的商品记录到当前会话近期展示商品池；`sse.mapper` 只负责输出 `message_commit` SSE。

### `block`

消息内容块。`data.type` 决定具体 payload。

#### `type = "text_delta"`

流式文本增量。

```json
{
  "type": "text_delta",
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "block_id": "blk-1",
  "content": "推"
}
```

#### `type = "text"`

完整文本块。

```json
{
  "type": "text",
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "block_id": "blk-1",
  "content": "你更看重控油、保湿，还是温和不刺激？"
}
```

#### `type = "product"`

商品卡片块。

```json
{
  "type": "product",
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "block_id": "blk-2",
  "group": "早餐",
  "product": {
    "product_id": "p_food_001",
    "title": "三顿半 数字星球系列 超即溶精品咖啡1-6号 18颗装精品速溶咖啡",
    "category": "食品饮料",
    "price": 138.0,
    "brand": "三顿半",
    "sub_category": "咖啡",
    "image_url": "/assets/food/images/p_food_001_live.jpg",
    "stock": 2,
    "detail_url": "/api/products/p_food_001",
    "landing_url": null,
    "highlights": ["..."],
    "stock_status": "low_stock",
    "unavailable_reason": null,
    "group_label": "早餐"
  }
}
```

#### `type = "compare"`

结构化对比块。

```json
{
  "type": "compare",
  "message_id": "asst-...",
  "attempt_id": "attempt-1",
  "block_id": "blk-1",
  "compare": {
    "products": [
      {"product_id": "p1", "title": "商品 A"},
      {"product_id": "p2", "title": "商品 B"}
    ],
    "rows": [
      {
        "dimension": "适合人群",
        "values": {
          "p1": "日常通勤",
          "p2": "户外运动"
        }
      }
    ]
  }
}
```

### `cart`

购物车快照。

payload 与 `CartSnapshot` 相同。

### `done`

本轮 SSE 正常结束。

```json
{}
```

### `error`

本轮失败。

```json
{
  "message": "服务处理失败，请稍后重试。"
}
```

已定义通用错误消息：

- `模型输出连续异常，已停止本轮回复，请稍后重试。`
- `服务处理失败，请稍后重试。`

## Pydantic Schema

定义位置：`server/schemas.py`

### `ChatRequest`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `message` | `str` | `min_length=1` |
| `conversation_id` | `str | None` | 可空 |

### `Product`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `product_id` | `str` | 商品 ID |
| `title` | `str` | 标题 |
| `category` | `str` | 类目 |
| `price` | `float` | 当前价格 |
| `brand` | `str | None` | 品牌 |
| `sub_category` | `str | None` | 子类目 |
| `image_url` | `str | None` | 图片 URL，通常为 `/assets/...` |
| `stock` | `int | None` | 库存 |
| `detail_url` | `str | None` | 商品详情 API URL |
| `landing_url` | `str | None` | 原始落地页 URL |
| `highlights` | `list[str]` | 公开卖点 |
| `stock_status` | `StockStatus` | 库存状态 |
| `unavailable_reason` | `str | None` | 不可用原因 |
| `group_label` | `str | None` | 跨类目推荐分组 |

`StockStatus = Literal["in_stock", "low_stock", "out_of_stock", "inactive"]`

### `ProductDetail`

继承 `Product`，追加：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `description` | `str` | 商品完整说明 |
| `specs` | `list[dict[str, str]]` | SKU 规格汇总 |
| `faq` | `list[ProductFaq]` | 官方 FAQ，最多 5 条 |
| `review_summary` | `ProductReviewSummary` | 用户评价摘要 |

### `ProductFaq`

| 字段 | 类型 |
| --- | --- |
| `question` | `str` |
| `answer` | `str` |

### `ProductReviewSummary`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `average_rating` | `float | None` | 一位小数平均评分 |
| `total_count` | `int` | 评论总数 |
| `highlights` | `list[str]` | 前 3 条评论内容 |

### `CartItem`

继承 `Product`，追加：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `quantity` | `int` | `ge=1` |
| `is_active` | `bool | None` | 是否上架 |
| `unavailable_reason` | `str | None` | 商品不可用原因 |

### `CartSnapshot`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `conversation_id` | `str` | 会话 ID |
| `items` | `list[CartItem]` | 购物车明细 |
| `total_quantity` | `int` | 总件数 |
| `total_price` | `float` | 总价，两位小数 |
| `messages` | `list[str]` | 价格变化、下架移除等提示 |

### `AddCartItemRequest`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `conversation_id` | `str | None` | 可空 |
| `product_id` | `str` | 必填 |
| `quantity` | `int` | 默认 1，`ge=1` |

### `UpdateCartItemRequest`

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `conversation_id` | `str | None` | 可空 |
| `quantity` | `int` | `ge=1` |

## Agent 工具

工具定义位置：`server/tools/`

### `retrieve_products`

执行函数：`tools.retrieve_products.execute(arguments: dict) -> list[dict]`

参数：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `requests` | `array` | 是 | 1-4 个检索子需求 |

每个 request：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `label` | `string` | 是 | 子需求名称，如 `防晒护肤` |
| `search_query` | `string` | 是 | 改写后的正向检索语句 |
| `category` | `string` | 否 | `服饰运动`、`美妆护肤`、`数码电子`、`食品饮料` |
| `min_price` | `number` | 否 | 最低价格 |
| `max_price` | `number` | 否 | 最高价格 |
| `must_have_terms` | `array[string]` | 否 | 必须具备的属性关键词 |
| `exclude_terms` | `array[string]` | 否 | 需排除的属性短语 |
| `exclude_brands` | `array[string]` | 否 | 需排除的品牌 |

返回：

```json
[
  {
    "label": "早餐咖啡",
    "search_query": "咖啡 早餐 便携",
    "products": []
  }
]
```

### 购物车工具

执行函数：`tools.cart.execute(name: str, arguments: dict, conversation_id: str) -> dict`

| 工具名 | 说明 |
| --- | --- |
| `add_to_cart` | 把当前会话近期展示过的一个或多个商品加入购物车 |
| `list_recent_products` | 读取当前会话最近展示的最多 20 个商品 |
| `remove_from_cart` | 按商品 ID、购物车位置或标题关键词删除商品 |
| `update_cart_item` | 按商品 ID、购物车位置或标题关键词修改数量 |
| `view_cart` | 查看购物车 |
| `clear_cart` | 清空购物车 |

通用返回：

```json
{
  "success": true,
  "message": "已将「商品」加入购物车，每款数量 1 件。当前共 1 件，合计 ¥12.00。",
  "cart": {}
}
```

错误返回：

```json
{
  "success": false,
  "message": "你想操作购物车里的哪一款？请说明第几个商品或商品名。"
}
```

## 核心 Python 接口

### 应用与路由

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| `main.py` | `create_app() -> FastAPI` | 创建应用并注册中间件、静态资源、路由 |
| `api.__init__` | `include_api_routes(app)` | 注册 chat/products/cart router |
| `api.chat` | `iter_chat_sse_events(conversation_id, message, is_disconnected=...)` | Agent 事件到 SSE dict 的异步迭代器 |

### 商品与索引

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| `product_store.py` | `initialize_database()` | 创建数据库和表 |
| `product_store.py` | `load_dataset_to_mysql(dataset_dir=None) -> int` | 数据集 upsert 到 MySQL |
| `product_store.py` | `upsert_products(records)` | 批量幂等写入商品 |
| `product_store.py` | `get_products_by_ids(product_ids) -> list[dict]` | 按传入顺序读取商品 |
| `product_store.py` | `get_product_by_id(product_id) -> dict | None` | 读取单个商品 |
| `product_store.py` | `get_product_detail(product_id) -> dict | None` | 构造公开详情 |
| `product_store.py` | `list_active_products() -> list[dict]` | 读取上架商品 |
| `product_store.py` | `get_products_updated_after(updated_after) -> list[dict]` | 读取增量商品 |
| `product_store.py` | `get_sync_state(name) -> datetime | None` | 读取同步水位 |
| `product_store.py` | `set_sync_state(name, last_sync_at)` | 写入同步水位 |
| `ingest.py` | `load_products(dataset_dir) -> list[dict]` | 扫描数据集 JSON |
| `ingest.py` | `build_embedding_text(product) -> str` | 构造紧凑向量文本 |
| `ingest.py` | `build_full_document(product) -> str` | 构造完整商品文档 |
| `ingest.py` | `ingest(dataset_dir=None, reset=True) -> int` | 从 MySQL 构建或更新 Chroma 索引 |
| `chroma_sync.py` | `sync_once() -> dict` | 执行一轮 MySQL -> Chroma 增量同步 |
| `chroma_sync.py` | `run_periodic_sync(interval_seconds=180, max_runs=None)` | 周期同步任务 |
| `embedding.py` | `get_embedding_function()` | 返回全局 SentenceTransformer embedding function |

### 检索与商品展示

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| `retriever.py` | `retrieve(query, top_k=5, intent=None) -> list[dict]` | Chroma 召回、rerank、MySQL hydrate 和过滤 |
| `catalog.product_presenter` | `product_availability(product) -> tuple[str, str | None]` | 计算库存状态 |
| `catalog.product_presenter` | `product_card_payload(product, group_label=None) -> dict` | 构造商品卡片公开字段 |
| `catalog.product_presenter` | `build_product_detail(product) -> dict` | 构造详情页公开字段 |

### 会话与购物车

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| `conversation.py` | `get_or_create_id(conversation_id) -> str` | 获取或创建内存会话 |
| `conversation.py` | `get_history(conversation_id) -> list[dict]` | 读取历史 |
| `conversation.py` | `append(conversation_id, message)` | 写入历史并保留最近 10 轮 |
| `cart_store.py` | `record_recent_product(conversation_id, product)` | 记录成功展示商品 |
| `cart_store.py` | `list_recent_products(conversation_id) -> list[dict]` | 读取近期展示商品 |
| `cart_store.py` | `add_item(conversation_id, product_id, quantity=1) -> dict` | 加购 |
| `cart_store.py` | `update_item(conversation_id, product_id, quantity) -> dict` | 改量 |
| `cart_store.py` | `remove_item(conversation_id, product_id) -> dict` | 删除 |
| `cart_store.py` | `clear_cart(conversation_id) -> dict` | 清空 |
| `cart_store.py` | `snapshot(conversation_id) -> dict` | 当前购物车快照 |

### Agent 与 SSE

| 模块 | 接口 | 说明 |
| --- | --- | --- |
| `agent.orchestrate` | `run_turn(conversation_id, user_message)` | 执行一轮 Agent 对话并 yield 内部事件 |
| `agent.orchestrate` | `build_initial_state(conversation_id, user_message)` | 构造单轮 Agent 初始状态 |
| `agent.runtime` | `model_step(state)` | 执行一次模型流式输出或工具调用判定 |
| `agent.runtime` | `tool_step(state)` | 执行当前 pending tool calls |
| `agent.tool_runtime` | `execute_tool_calls(state, emit=...)` | 解析和执行工具调用，整理候选商品和购物车事件 |
| `agent.tool_runtime` | `parse_tool_arguments(tool_call)` | 校验并解析工具 JSON 参数 |
| `agent.streaming` | `StreamingFinalEmitter` | 流式解析最终回复并发出 block 事件 |
| `agent.parsing.final` | `parse_final_response(text, candidate_ids, candidate_groups=None)` | 解析普通文本、推荐和对比标记 |
| `agent.emitters` | `events_from_parsed_response(...)` | 解析结果转 block 事件 |
| `sse.mapper` | `map_agent_event(event, conversation_id)` | 内部事件转 SSE dict，不写业务状态 |
| `sse.mapper` | `map_done_event()` | 构造 done SSE |
| `sse.mapper` | `map_error_event(message)` | 构造 error SSE |

### Agent typed contracts

定义位置：`server/agent/contracts.py`

| 类 | 说明 |
| --- | --- |
| `CandidateProduct` | Agent 内部候选商品封装 |
| `CandidateGroup` | retrieve_products 返回的候选分组 |
| `ToolCall` | 模型工具调用的内部表示 |
| `RecentProductEntry` | 成功 commit 后可记录到近期展示池的商品 |
| `TurnBudget` | 单轮模型 step、工具 step、迁移次数和 force-final 状态预算 |
| `AgentState` | Agent 运行时共享状态 |

### Agent 事件 dataclass

定义位置：`server/agent/events.py`

| 类 | 说明 |
| --- | --- |
| `StructuredStatusEvent` | 阶段状态 |
| `CartEvent` | 购物车快照 |
| `BlockTextEvent` | 完整文本块 |
| `BlockTextDeltaEvent` | 文本增量块 |
| `BlockProductEvent` | 商品卡片块 |
| `BlockCompareEvent` | 对比表块 |
| `MessageStartEvent` | assistant 消息开始 |
| `MessageResetEvent` | attempt 重置 |
| `MessageCommitEvent` | assistant 消息提交，包含 `list[RecentProductEntry]` |
| `RecommendationItem` | 推荐条目解析结果 |
| `ParsedRecommendation` | 推荐块解析结果 |
| `ParsedFinalResponse` | 最终回复解析结果 |

### 错误类型

定义位置：`server/agent/errors.py`

| 类 | 说明 |
| --- | --- |
| `RecoverableAgentError` | 可反馈给 LLM 修正的边界错误 |
| `AgentRecoveryExhausted` | 恢复次数耗尽后的终止错误 |
| `RecoveryState` | 记录同类错误和总错误恢复次数 |

## Android 接口索引

### `ChatService`

位置：`client-android/app/src/main/java/.../data/api/ChatApiService.kt`

| 方法 | 说明 |
| --- | --- |
| `streamChat(message, conversationId): Flow<ChatEvent>` | 发起 SSE 聊天 |
| `getCart(conversationId): Cart` | 获取购物车 |
| `getProductDetail(productId): ProductDetail` | 获取商品详情 |
| `addCartItem(conversationId, productId, quantity)` | 加购 |
| `updateCartItem(conversationId, productId, quantity)` | 改量 |
| `removeCartItem(conversationId, productId)` | 删除购物车商品 |
| `clearCart(conversationId)` | 清空购物车 |

实现类：`ChatApiService`

### `ChatEvent`

位置：`data/api/ChatEvent.kt`

| 事件类 | 对应服务端事件 |
| --- | --- |
| `StructuredStatus` | `status` |
| `CartUpdated` | `cart` |
| `MessageStart` | `message_start` |
| `MessageReset` | `message_reset` |
| `MessageCommit` | `message_commit` |
| `BlockText` | `block type=text` |
| `BlockTextDelta` | `block type=text_delta` |
| `BlockProduct` | `block type=product` |
| `BlockCompare` | `block type=compare` |
| `Done` | `done` |
| `Error` | `error` |

### `ChatViewModel`

位置：`viewmodel/ChatViewModel.kt`

公开操作：

| 方法 | 说明 |
| --- | --- |
| `sendMessage(text)` | 发送用户消息并消费 SSE |
| `refreshCart()` | 刷新购物车 |
| `openProductDetail(product)` | 打开商品详情 |
| `dismissProductDetail()` | 关闭详情 |
| `addToCart(product)` | 加购商品 |
| `incrementCartItem(productId)` | 数量加一 |
| `decrementCartItem(productId)` | 数量减一，减到 0 时删除 |
| `updateCartItem(productId, quantity)` | 设置数量 |
| `removeCartItem(productId)` | 删除商品 |
| `clearCart()` | 清空购物车 |
| `cancelResponse()` | 取消当前 SSE 回复 |

### Android 数据模型

| 文件 | 类型 |
| --- | --- |
| `data/model/Product.kt` | `Product`、`ProductSpec`、`ProductFaq`、`ReviewSummary`、`ProductDetail` |
| `data/model/Cart.kt` | `CartItem`、`Cart` |
| `data/model/CompareTable.kt` | `CompareProduct`、`CompareRow`、`CompareTable` |
| `data/model/Message.kt` | `MessageBlock`、`Message`、`StreamingStatus` |

## CLI 脚本

### `server/product_store.py`

加载数据集到 MySQL：

```bash
cd server
python product_store.py
```

### `server/ingest.py`

构建 ChromaDB 索引：

```bash
cd server
python ingest.py
python ingest.py --dataset-dir ../ecommerce_agent_dataset
python ingest.py --upsert
```

### `server/chroma_sync.py`

手动执行或循环执行增量同步：

```bash
cd server
python chroma_sync.py
python chroma_sync.py --loop
```

### `eval/run_retrieval_eval.py`

评估检索链路：

```bash
cd eval
python run_retrieval_eval.py --top-k 5 --with-intent
python run_retrieval_eval.py --top-k 5 --no-intent
python run_retrieval_eval.py --limit 10
```

### `eval/run_saved_intent_vector_eval.py`

复用保存的意图和检索文本评估：

```bash
cd eval
python run_saved_intent_vector_eval.py --source-report reports/retrieval_eval_top5_with_intent.json
python run_saved_intent_vector_eval.py --source-report reports/retrieval_eval_top5_with_intent.json --vector-only
```
