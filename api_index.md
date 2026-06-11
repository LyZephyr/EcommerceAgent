# API 接口索引

## 后端 HTTP API

### GET /health

健康检查。

**响应**：

```json
{"status": "ok"}
```

---

### POST /api/chat

流式对话接口，返回 SSE 事件流。

**请求体**：

```json
{
  "message": "推荐一款适合油皮的洗面奶",
  "conversation_id": "optional-uuid"
}
```

**请求字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `message` | `string` | 用户输入 |
| `conversation_id` | `string?` | 会话 ID；缺省时创建新会话 |

**SSE 事件类型**：

服务端只发送块式事件：`block`、`status`、`cart`、`error`、`done`。

| event | data 结构 | 说明 |
|-------|-----------|------|
| `status` | `{"phase": "retrieving", "message": "正在检索商品...", "step": 1, "total_steps": 4}` | 临时等待态；客户端不应写入消息块 |
| `block` | `{"type": "text", "message_id": "asst-...", "block_id": "blk-1", "content": "整体建议..."}` | 完整文本块；非 streaming 或缓冲解析场景使用 |
| `block` | `{"type": "text_delta", "message_id": "asst-...", "block_id": "blk-1", "content": "整"}` | 真 streaming 文本增量；隐藏 `<R>/<ITEM>/<REASON>` 标签不会出现在增量中 |
| `block` | `{"type": "product", "message_id": "asst-...", "block_id": "blk-2", "product": {...}, "group": "防晒护肤"}` | 商品块，按推荐文本顺序插入 |
| `block` | `{"type": "compare", "message_id": "asst-...", "block_id": "blk-1", "compare": {...}}` | 结构化对比块 |
| `cart` | `{"conversation_id": "...", "items": [...], "total_quantity": 2, "total_price": 198.0, "messages": []}` | 自然语言购物车工具成功执行后同步当前购物车快照 |
| `error` | `{"message": "..."}` | Agent 重试耗尽或服务端处理失败时发送，随后仍会发送 `done` |
| `done` | `{}` | 流结束标记 |

推荐块顺序由服务端保证：`INTRO text` -> `product A` -> `reason A text` -> `product B` -> `reason B text` -> `OUTRO text`。
推荐链路的最终回复使用 LLM streaming completion。服务端增量解析固定推荐标签：进入 `INTRO` / `REASON` / `OUTRO` 后发送 `text_delta`，识别 `ITEM` 开始标签后先发送对应商品块，再发送该商品理由增量。`<C>` 对比标记会缓冲到闭合后一次性解析并发送完整 compare block。

---

### GET /api/products/{product_id}

公共商品详情接口，不绑定 `conversation_id`。商品不存在返回 `404`；商品下架或无库存时仍返回基础详情，并通过 `stock_status` / `unavailable_reason` 标明不可加购原因。

**响应**：

```json
{
  "product_id": "...",
  "title": "...",
  "brand": "...",
  "category": "...",
  "sub_category": "...",
  "price": 99.0,
  "image_url": "/assets/...",
  "stock": 2,
  "detail_url": "/api/products/...",
  "landing_url": null,
  "highlights": ["口感清爽", "适合早餐"],
  "stock_status": "low_stock",
  "unavailable_reason": null,
  "group_label": null,
  "description": "...",
  "specs": [{"name": "规格", "value": "250ml / 1L"}],
  "faq": [{"question": "...", "answer": "..."}],
  "review_summary": {
    "average_rating": 4.5,
    "total_count": 2,
    "highlights": ["..."]
  }
}
```

`stock_status` 枚举值：`in_stock`、`low_stock`、`out_of_stock`、`inactive`。数据集没有真实外部商品页时，`landing_url` 返回 `null`；`detail_url` 指向服务端详情接口。

---

### GET /api/cart

查看当前会话购物车。该接口会在每次请求时重新读取 MySQL 最新商品快照，适合作为客户端打开购物车详情页时的同步入口。

**Query 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string?` | 会话 ID；缺省时创建新空会话 |

**响应**：

```json
{
  "conversation_id": "...",
  "items": [
    {
      "product_id": "...",
      "title": "...",
      "brand": "...",
      "category": "...",
      "sub_category": "...",
      "price": 99.0,
      "image_url": "...",
      "stock": 2,
      "detail_url": "/api/products/...",
      "landing_url": null,
      "highlights": [],
      "stock_status": "low_stock",
      "unavailable_reason": null,
      "group_label": null,
      "quantity": 2,
      "is_active": true
    }
  ],
  "total_quantity": 2,
  "total_price": 198.0,
  "messages": []
}
```

`items[].price`、`stock`、`stock_status` 和 `unavailable_reason` 均来自 MySQL 最新状态。商品价格相对上次购物车快照展示价变化时，`messages` 会返回一次性价格变动提示；缺货商品保留在 `items` 中并标记不可用；已下架或不存在商品会被移出购物车并在 `messages` 中说明原因。

---

### POST /api/cart/items

把当前会话近期展示过的商品加入购物车。接口只接受 `product_id` 和 `quantity`，近期展示商品池只用于确认商品身份并保留展示价用于价格变化提示；商品标题、当前价格、库存和上下架状态会在加购前从 MySQL 实时读取。

**请求体**：

```json
{
  "conversation_id": "...",
  "product_id": "...",
  "quantity": 1
}
```

**响应**：同 `GET /api/cart`。

**错误**：

| HTTP 状态码 | 场景 |
|-------------|------|
| `404` | 商品不在当前会话近期展示商品池中 |
| `409` | 商品已下架、无库存或库存不足 |
| `422` | `quantity < 1` 或请求体格式错误 |

---

### PATCH /api/cart/items/{product_id}

修改购物车中某个商品的数量。

**请求体**：

```json
{
  "conversation_id": "...",
  "quantity": 2
}
```

**响应**：同 `GET /api/cart`。

**错误**：

| HTTP 状态码 | 场景 |
|-------------|------|
| `404` | 购物车中不存在该商品 |
| `409` | 商品已下架、无库存或库存不足 |
| `422` | `quantity < 1` 或请求体格式错误 |

---

### DELETE /api/cart/items/{product_id}

从购物车删除某个商品。

**Query 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string?` | 会话 ID；缺省时创建新空会话 |

**响应**：同 `GET /api/cart`。

**错误**：

| HTTP 状态码 | 场景 |
|-------------|------|
| `404` | 购物车中不存在该商品 |

---

### DELETE /api/cart

清空当前会话购物车。

**Query 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `conversation_id` | `string?` | 会话 ID；缺省时创建新空会话 |

**响应**：同 `GET /api/cart`。

---

## 后端内部模块

### config.py

| 常量 | 说明 |
|------|------|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DATABASE` | MySQL 商品权威源连接配置，来自 `.env` 或默认值 |
| `DATASET_DIR` | 商品数据集目录 |
| `CHROMA_PERSIST_DIR` / `CHROMA_COLLECTION_NAME` | ChromaDB 持久化目录与 collection 名称 |
| `EMBEDDING_MODEL` | SentenceTransformer 模型名，默认 `BAAI/bge-base-zh-v1.5` |
| `HF_ENDPOINT` | Hugging Face Hub 下载端点，默认 `https://hf-mirror.com`；加载时写入 `os.environ` |
| `HF_HUB_OFFLINE` | 是否仅使用本地模型缓存，默认 `False`；首次 `ingest` 前须为 `False` |
| `TOP_K` | 默认检索返回数量 |

### agent.py

| 常量/类/函数 | 签名 | 说明 |
|---------|------|------|
| `TOOL_USE_PROMPT` | `str` | Agent 工具决策规则；`run_turn()` 与离线意图解析共用 |
| `FINAL_REPLY_PROMPT` | `str` | 最终回复规则，包含移动端推荐固定标签协议、对比标记和正文约束 |
| `SYSTEM_PROMPT` | `str` | `TOOL_USE_PROMPT + "\n" + FINAL_REPLY_PROMPT`，供 Agent 主链路使用 |
| `AgentRecoveryExhausted` | `RuntimeError` | 同类可恢复错误连续超过 2 次重试后的终止异常，包含结构化错误 payload |
| `RecoverableAgentError` | `RuntimeError` | LLM 可修正的边界错误，包括超时、空响应、工具参数错误、工具执行异常和隐藏标记错误 |
| `StructuredStatusEvent` | `@dataclass: phase: str, message: str, step: int?, total_steps: int?` | 块协议状态提示，状态不写入 conversation 历史 |
| `BlockTextEvent` | `@dataclass: message_id: str, block_id: str, content: str` | 块协议完整文本块 |
| `BlockTextDeltaEvent` | `@dataclass: message_id: str, block_id: str, content: str` | 真 streaming 文本增量块，同一文本块共享 `block_id` |
| `BlockProductEvent` | `@dataclass: message_id: str, block_id: str, product_id: str, product_data: dict, group: str?` | 块协议商品块 |
| `BlockCompareEvent` | `@dataclass: message_id: str, block_id: str, payload: dict` | 块协议结构化对比块 |
| `CartEvent` | `@dataclass: payload: dict` | 购物车快照同步事件 |
| `ParsedRecommendation` | `@dataclass: intro: str, items: list[RecommendationItem], outro: str?` | 固定 `<R>` 推荐标签解析结果 |
| `RecommendationItem` | `@dataclass: product_id: str, reason: str, group: str?` | 单个推荐商品及其理由 |
| `run_turn` | `async (conversation_id: str, user_message: str) -> AsyncIterator[...]` | 执行一轮对话：最多 3 步 ReAct 工具循环 + 最终回复解析；对 LLM 超时、工具调用解析失败、工具执行异常、非法 `<R>/<C>` 标记等可恢复错误进行结构化反馈，同类错误最多连续重试 2 次，单个恢复阶段整体最多 6 次 |

推荐回复固定标签协议：

```xml
<R>
<INTRO>整体建议：...</INTRO>
<ITEM id="p1" group="可选分组">
<REASON>推荐理由...</REASON>
</ITEM>
<OUTRO>可选总结...</OUTRO>
</R>
```

解析器会校验：`<R>` 外无非空正文、`<R>` 与 `<C>` 不共存、`id` 来自本轮候选、多 request 场景下 `group` 来自 `requests[].label` 且商品属于该分组、`ITEM` 属性字符集合法、每个 `ITEM` 必须且只能包含一个非空 `REASON`、`INTRO/ITEM/OUTRO` 顺序合法，并对 `INTRO`、`REASON`、`OUTRO` 分别做移动端文本校验。

### tools/\_\_init\_\_.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `execute` | `(name: str, arguments: dict, conversation_id: str \| None = None)` | 按工具名分发执行；购物车工具必须传入 `conversation_id` |

### tools/cart.py

| 函数/常量 | 签名 | 说明 |
|-----------|------|------|
| `TOOL_DEFINITIONS` | `list[dict]` | OpenAI Function Calling 格式的购物车工具定义 |
| `execute` | `(name: str, arguments: dict, conversation_id: str) -> dict` | 执行购物车工具，返回 `success`、`message` 和可选 `cart` 快照 |

购物车工具列表：

| 工具名 | 关键参数 | 说明 |
|--------|----------|------|
| `add_to_cart` | `product_ids`, `quantity?` | 批量把明确商品 ID 加入购物车；每个 ID 必须属于当前会话近期展示商品池，加购前读取 MySQL 最新价格、库存和上下架状态 |
| `list_recent_products` | 无 | 返回当前会话最近 20 个展示商品详情，按推荐时间从近到远排序；仅用于 LLM 因上下文过长记忆模糊时补充记忆 |
| `remove_from_cart` | `product_id?`, `cart_position?`, `title_keyword?` | 从购物车删除商品 |
| `update_cart_item` | `product_id?`, `cart_position?`, `title_keyword?`, `quantity` | 修改购物车商品数量 |
| `view_cart` | 无 | 查看当前购物车 |
| `clear_cart` | 无 | 清空当前购物车 |

### tools/retrieve_products.py

| 函数/常量 | 签名 | 说明 |
|-----------|------|------|
| `TOOL_DEFINITION` | `dict` | OpenAI Function Calling 格式的工具定义，参数为 `requests[]` |
| `execute` | `(arguments: dict) -> list[dict]` | 遍历 `requests[]`，每个 request 独立调用 `retriever.retrieve()`，返回多组 Top-K 商品 |
| `parse_intent` | `async (query: str) -> dict` | 使用 `TOOL_USE_PROMPT` + 精简意图解析提示（`temperature=0.3`），强制工具调用提取单 request 检索意图（供离线评估使用），不加载最终回复标签规则 |

`retrieve_products` 工具参数示例：

```json
{
  "requests": [
    {
      "label": "防晒护肤",
      "search_query": "海边 高倍 防晒 清爽 防水",
      "category": "美妆护肤",
      "must_have_terms": ["高倍防晒", "清爽", "防水"],
      "exclude_terms": [],
      "exclude_brands": []
    },
    {
      "label": "度假穿搭",
      "search_query": "度假 夏季 轻薄 透气 穿搭",
      "category": "服饰运动",
      "must_have_terms": ["轻薄", "透气"],
      "exclude_terms": [],
      "exclude_brands": []
    }
  ]
}
```

工具返回多组结果，Agent 会在生成阶段保留分组上下文，但发送商品卡片时将候选商品拍平成本轮推荐池。

### conversation.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `get_or_create_id` | `(conversation_id: str \| None) -> str` | 获取已有会话或创建新会话 |
| `get_history` | `(conversation_id: str) -> list[dict]` | 返回对话历史（浅拷贝） |
| `append` | `(conversation_id: str, message: dict) -> None` | 追加消息并执行滑动窗口裁剪 |

### cart_store.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `record_recent_product` | `(conversation_id: str, product: dict) -> None` | 记录当前会话已通过商品卡片展示的轻量近期记录：`product_id`、`displayed_price`、`displayed_at` |
| `get_recent_product_entry` | `(conversation_id: str, product_id: str) -> dict \| None` | 按商品 ID 从近期展示商品池取轻量记录，用于确认商品属于当前会话 |
| `list_recent_product_entries` | `(conversation_id: str) -> list[dict]` | 返回轻量近期记录，按展示时间从近到远排序 |
| `list_recent_products` | `(conversation_id: str) -> list[dict]` | 读取近期记录中的 `product_id` 并从 MySQL 补全商品详情，供工具返回给 LLM |
| `CartOperationError` | `ValueError` 子类，含 `status_code` | 加购或改数量校验失败，供 HTTP 和自然语言工具统一处理 |
| `add_item` | `(conversation_id: str, product_id: str, quantity: int = 1) -> dict` | 先确认 `product_id` 属于当前会话近期展示商品池，再读取 MySQL 最新商品并加购；商品下架、无库存或库存不足时抛出 `CartOperationError` |
| `remove_item` | `(conversation_id: str, product_id: str) -> dict` | 删除购物车商品；不存在时抛出 `KeyError` |
| `update_item` | `(conversation_id: str, product_id: str, quantity: int) -> dict` | 设置购物车商品数量；不存在时抛出 `KeyError`；商品下架、无库存或库存不足时抛出 `CartOperationError` |
| `clear_cart` | `(conversation_id: str) -> dict` | 清空当前会话购物车并返回快照 |
| `snapshot` | `(conversation_id: str) -> dict` | 从 MySQL 重新读取商品最新状态，返回 `items`、`total_quantity`、`total_price`、`messages` 购物车快照；价格变化会按购物车条目的 `last_seen_price` 返回一次性提示，缺货商品保留并标记不可用，下架或不存在商品会被移除并写入提示 |

### product_store.py

MySQL 商品权威源。FastAPI 启动时会调用 `load_dataset_to_mysql()`，确保 `products` 表存在并将数据集商品按 `product_id` 幂等写入 MySQL。

`products` 表关键字段：

| 字段 | 说明 |
|------|------|
| `product_id` | 商品唯一 ID，主键 |
| `title` / `brand` / `category` / `sub_category` | 商品基础信息 |
| `price` | 商品当前权威价格，来自数据集 `base_price` |
| `stock` | 商品当前权威库存，来自数据集 `stock`，缺失时默认 `2` |
| `is_active` | 是否上架，缺失时默认 `true` |
| `description` | 完整商品文档 |
| `image_url` | 后端静态资源 URL |
| `raw_payload` | 原始商品 JSON |
| `embedding_text` | 后续 ChromaDB 构建使用的紧凑向量化文本 |
| `created_at` / `updated_at` | 创建与更新时间；upsert 仅在商品字段变化时刷新 `updated_at` |

`sync_state` 表：

| 字段 | 说明 |
|------|------|
| `name` | 同步任务名称，主键 |
| `last_sync_at` | 最近一次成功同步到 ChromaDB 的 MySQL `updated_at` 水位 |
| `updated_at` | 同步状态记录更新时间 |

| 函数 | 签名 | 说明 |
|------|------|------|
| `initialize_database` | `() -> None` | 创建 MySQL database 和 `products` 表 |
| `load_dataset_to_mysql` | `(dataset_dir: str \| None = None) -> int` | 扫描数据集并 upsert 到 MySQL，返回加载商品数 |
| `upsert_products` | `(records: list[dict]) -> None` | 按 `product_id` 幂等写入商品记录 |
| `get_products_by_ids` | `(product_ids: list[str]) -> list[dict]` | 按传入顺序批量读取商品快照，缺失商品会被忽略 |
| `get_product_by_id` | `(product_id: str) -> dict \| None` | 读取单个商品快照 |
| `get_product_detail` | `(product_id: str) -> dict \| None` | 读取单个商品详情，返回公开详情字段、规格、FAQ 和评价摘要，不暴露完整 `raw_payload` |
| `product_card_payload` | `(product: dict, *, group_label: str \| None = None) -> dict` | 构造商品卡片和详情页共用公开字段，包含 `detail_url`、`landing_url`、`highlights`、`stock_status`、`unavailable_reason` 和 `group_label` |
| `product_availability` | `(product: dict) -> tuple[str, str \| None]` | 统一计算 `in_stock`、`low_stock`、`out_of_stock`、`inactive` 和不可用原因 |
| `get_products_updated_after` | `(updated_after: datetime) -> list[dict]` | 查询指定时间之后更新的商品，供后续增量同步使用 |
| `list_active_products` | `() -> list[dict]` | 返回所有上架商品 |
| `count_products` | `() -> int` | 返回 MySQL `products` 表商品数 |
| `get_sync_state` | `(name: str) -> datetime \| None` | 读取同步任务水位 |
| `set_sync_state` | `(name: str, last_sync_at: datetime) -> None` | upsert 同步任务水位 |
| `product_to_record` | `(product: dict) -> dict` | 将数据集商品对象转换为 MySQL 记录 |

### chroma_sync.py

| 函数/常量 | 签名 | 说明 |
|-----------|------|------|
| `SYNC_STATE_NAME` | `"chroma_products"` | ChromaDB 商品同步任务名称 |
| `SYNC_INTERVAL_SECONDS` | `180` | 后台同步间隔 |
| `sync_once` | `() -> dict` | 执行一轮 MySQL 增量变更同步；返回 scanned/upserted/deleted/elapsed_seconds/last_sync_at/upserted_product_ids/deleted_product_ids，并记录同步完成与变更明细日志 |
| `run_periodic_sync` | `async (interval_seconds: int = 180, *, max_runs: int \| None = None) -> None` | 后台循环执行 `sync_once()`；失败只记录日志并等待下一轮；`max_runs` 供测试或一次性调度使用 |

命令：

```bash
cd server
python chroma_sync.py        # 手动执行一次增量同步
python chroma_sync.py --loop # 按 3 分钟间隔持续同步
```

### retriever.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `retrieve` | `(query: str, top_k: int = 5, intent: dict \| None = None) -> list[dict]` | 基于 ChromaDB 召回候选 `product_id` 并重排，再从 MySQL 批量读取最新商品快照，过滤下架、无库存、预算不匹配、类目不匹配和排除品牌后返回 Top-K 商品 |

### ingest.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_products` | `(dataset_dir: str) -> list[dict]` | 扫描数据集目录，返回商品字典列表 |
| `build_embedding_text` | `(product: dict) -> str` | 构建紧凑的 embedding 文本，包含标题、品牌、类目、SKU 属性摘要、卖点、FAQ 问题摘要和评价摘要，不加入 `base_price` 和 SKU `price` 字段 |
| `build_full_document` | `(product: dict) -> str` | 构建完整商品文档，不写入价格、库存、上下架等易变字段 |
| `product_to_chroma_metadata` | `(product: dict) -> dict` | 构建 ChromaDB 稳定 metadata；初始 ingest 和后台同步共用 |
| `ingest` | `(dataset_dir: str \| None = None, *, reset: bool = True) -> int` | 从 MySQL 上架商品读取 `embedding_text` / `description` 写入 ChromaDB；`reset=True` 清空重建，`reset=False` upsert 更新 |

### embedding.py

| 函数/类 | 签名 | 说明 |
|---------|------|------|
| `QuietSentenceTransformerEmbeddingFunction` | `SentenceTransformerEmbeddingFunction` 子类 | 关闭 `SentenceTransformer.encode()` 的进度条输出，避免检索和同步时向控制台写入 `Batches:` |
| `get_embedding_function` | `() -> EmbeddingFunction` | 返回进程内单例缓存的 ChromaDB embedding function，避免请求和后台同步重复加载模型 |

### logging_config.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `configure_logging` | `() -> None` | 配置后端日志格式与级别：项目日志保持 INFO，压低 `httpx`、Hugging Face、SentenceTransformers、Transformers 等第三方库噪声 |

### schemas.py

| 类 | 字段 | 说明 |
|----|------|------|
| `ChatRequest` | `message: str`, `conversation_id: str \| None` | 聊天请求 |
| `Product` | `product_id`, `title`, `brand`, `category`, `sub_category`, `price`, `image_url`, `stock`, `detail_url`, `landing_url`, `highlights`, `stock_status`, `unavailable_reason`, `group_label` | 商品卡片数据；`price`、`stock` 和可用状态来自 MySQL 最新快照 |
| `ProductDetail` | `Product` 字段 + `description`, `specs`, `faq`, `review_summary` | 商品详情接口响应；从 MySQL 快照和 `raw_payload` 派生，不直接暴露完整原始 JSON |
| `CartItem` | `Product` 字段 + `quantity: int`, `is_active: bool?` | 购物车商品明细；复用 Product 的 `stock_status` / `unavailable_reason` 表达可用状态，价格、库存来自 MySQL 最新快照 |
| `CartSnapshot` | `conversation_id`, `items`, `total_quantity`, `total_price`, `messages` | 购物车快照响应；`messages` 包含价格变化、商品移除等提示 |
| `AddCartItemRequest` | `conversation_id: str \| None`, `product_id: str`, `quantity: int = 1` | 加购请求 |
| `UpdateCartItemRequest` | `conversation_id: str \| None`, `quantity: int` | 修改数量请求 |

---

## 离线评估工具

### eval/ground_truth.json

250 条检索评估查询，每条包含 `id`、`query`、`query_type`、人工可审核的 `relevant_product_ids` 和标注说明 `notes`。

### eval/run_retrieval_eval.py

对 Ground Truth 中每条查询调用检索链路并计算召回质量指标。默认通过 `tools.retrieve_products.parse_intent` 提取单 request 意图（强制工具调用），再调用 `retrieve(query, top_k, intent)`。

**命令**：

```bash
# 带意图解析（默认）
server/.venv/bin/python eval/run_retrieval_eval.py

# 仅评估纯检索（不含意图解析）
server/.venv/bin/python eval/run_retrieval_eval.py --no-intent

# 快速抽样
server/.venv/bin/python eval/run_retrieval_eval.py --limit 10

server/.venv/bin/python eval/run_retrieval_eval.py --top-k 10

# 离线环境：在 .env 中设置 HF_HUB_OFFLINE=1（模型已缓存后）
server/.venv/bin/python eval/run_retrieval_eval.py

# 复用已有报告中的 search_text/where_filter/intent，重新跑检索 + rerank
server/.venv/bin/python eval/run_saved_intent_vector_eval.py

# 仅复用 search_text/where_filter，纯向量距离排序
server/.venv/bin/python eval/run_saved_intent_vector_eval.py --vector-only
```

**输出指标**：

| 指标 | 说明 |
|------|------|
| `Recall@K` | Top-K 中命中的相关商品数 / Ground Truth 相关商品数 |
| `MRR` | 第一个相关商品排名的倒数，未命中为 0 |
| `Hit Rate@K` | Top-K 中是否至少命中 1 个相关商品 |
| `Precision@K` | Top-K 中命中的相关商品数 / K |

默认 K 读取 `server/config.py` 中的 `TOP_K`，也可通过 `--top-k` 覆盖。报告写入 `eval/reports/` 目录。

---

## Android 客户端接口

### data/model/Message.kt

| 类型 | 成员 | 说明 |
|------|------|------|
| `MessageRole` | `User`, `Assistant` | 消息角色枚举 |
| `Message` | `id: String`, `role: MessageRole`, `content: String`, `products: List<Product>`, `isStreaming: Boolean`, `isError: Boolean` | 聊天消息状态 |

### data/model/Product.kt

| 类型 | 字段 | 说明 |
|------|------|------|
| `Product` | `productId: String`, `title: String`, `category: String`, `price: Double`, `brand: String?`, `subCategory: String?`, `imageUrl: String?` | 客户端商品模型 |

### data/api/ChatEvent.kt

| 类型 | 成员 | 说明 |
|------|------|------|
| `ChatEvent` | `Status`, `CartUpdated`, `BlockText`, `BlockProduct`, `BlockCompare`, `Done`, `Error` | 块式 SSE 事件客户端封装 |

### data/api/ChatApiService.kt

| 成员 | 签名 | 说明 |
|------|------|------|
| `ChatApiService` | `(baseUrl: String = BuildConfig.API_BASE_URL, client: OkHttpClient = ...)` | SSE API 客户端 |
| `streamChat` | `(message: String, conversationId: String?) -> Flow<ChatEvent>` | POST `/api/chat`，解析事件并以 Flow 发出 |

### viewmodel/ChatViewModel.kt

| 类型/成员 | 签名 | 说明 |
|-----------|------|------|
| `ChatUiState` | `messages: List<Message>`, `isLoading: Boolean`, `conversationId: String` | Compose 层订阅的聊天 UI 状态 |
| `ChatViewModel.uiState` | `StateFlow<ChatUiState>` | 只读状态流 |
| `sendMessage` | `(text: String) -> Unit` | 追加用户消息，启动 SSE 流式请求 |
| `cancelResponse` | `() -> Unit` | 取消当前流式响应 |

### ui/chat/ChatScreen.kt

| Composable | 签名 | 说明 |
|------------|------|------|
| `ChatRoute` | `(viewModel: ChatViewModel = viewModel())` | 连接 ViewModel 与聊天界面 |
| `ChatScreen` | `(messages, isLoading, onSendMessage, onCancelResponse)` | 聊天主界面 |
| `MessageItem` | `(message, onProductClick)` | 单条消息与商品列表 |
| `MessageBubble` | `(message)` | 消息气泡 |
| `ProductCard` | `(product, onClick)` | 商品卡片 |
| `ProductImage` | `(imageUrl, modifier)` | 商品图片 |
| `ChatInputBar` | `(input, isLoading, onInputChange, onSend, onCancel)` | 输入栏 |
| `ProductDialog` | `(product, onDismiss)` | 商品详情弹窗 |
| `ProductInfoRow` | `(label, value)` | 商品详情字段行 |

### Android 构建与运行配置

| 文件 | 配置 | 说明 |
|------|------|------|
| `app/build.gradle.kts` | `BuildConfig.API_BASE_URL = "http://10.0.2.2:8000"` | 模拟器访问宿主机 FastAPI |
| `app/build.gradle.kts` | OkHttp、OkHttp SSE、Coil Compose、Lifecycle ViewModel Compose、Material Icons Extended | 客户端依赖 |
| `AndroidManifest.xml` | `INTERNET`, `usesCleartextTraffic=true` | 网络权限 |
| `gradle.properties` | `kotlin.compiler.execution.strategy=in-process` | Kotlin daemon 配置 |
## Android client compare display extension

| Type / member | Signature | Description |
|---------------|-----------|-------------|
| `CompareTable` | `products: List<CompareProduct>`, `rows: List<CompareRow>` | Client model for `block.type=compare` payloads. |
| `Message.compareTables` | `List<CompareTable>` | Structured comparison tables attached to an assistant message. |
| `Message.status` | `String?` | Current streaming status text from backend `status` events. |
| `ChatEvent.Status` | `phase: String, message: String, step: Int?, totalSteps: Int?` | Parsed backend `status` SSE event. |
| `ChatEvent.BlockCompare` | `messageId: String, blockId: String, table: CompareTable` | Parsed backend `block.type=compare` event. |
| `CompareTableCard` | `(table: CompareTable)` | Compose renderer for comparison tables inside the message stream. |

## Android client cart UI extension

| Type / member | Signature | Description |
|---------------|-----------|-------------|
| `CartItem` | `productId`, `title`, `category`, `price`, `brand`, `subCategory`, `imageUrl`, `quantity`, `stock`, `isActive`, `unavailableReason`, `subtotal` | Client model for one cart row, including backend availability state. |
| `Cart` | `conversationId`, `items`, `totalQuantity`, `totalPrice`, `messages` | Client model for backend cart snapshots, including server notices such as price changes or unavailable products. |
| `ChatEvent.CartUpdated` | `cart: Cart` | Parsed backend `cart` SSE event. |
| `ChatApiService.getCart` | `suspend (conversationId: String) -> Cart` | Calls `GET /api/cart`. |
| `ChatApiService.addCartItem` | `suspend (conversationId: String, productId: String, quantity: Int = 1) -> Cart` | Calls `POST /api/cart/items`. |
| `ChatApiService.updateCartItem` | `suspend (conversationId: String, productId: String, quantity: Int) -> Cart` | Calls `PATCH /api/cart/items/{product_id}`. |
| `ChatApiService.removeCartItem` | `suspend (conversationId: String, productId: String) -> Cart` | Calls `DELETE /api/cart/items/{product_id}`. |
| `ChatApiService.clearCart` | `suspend (conversationId: String) -> Cart` | Calls `DELETE /api/cart`. |
| `ChatUiState.cart` | `Cart` | Current cart snapshot for the active conversation. |
| `ChatUiState.isCartLoading` | `Boolean` | True while a direct cart HTTP mutation is in flight. |
| `ChatUiState.cartError` | `String?` | Last cart mutation error shown in the cart summary/sheet. |
| `CartSummaryBar` | `(cart, cartError, isCartLoading, onClick)` | Summary strip above the chat input; shows cart errors first, then backend cart messages. |
| `CartSheet` | `(cart, isCartLoading, cartError, onDismiss, onIncrement, onDecrement, onRemove, onClear)` | Bottom sheet for cart detail and management; shows backend messages and per-item unavailable status. |

## End-to-end validation

| Script | Command | Coverage |
|--------|---------|----------|
| `eval/run_cart_e2e.py` | `python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000` | Validates HTTP cart CRUD, SSE recommendation product capture, conversation isolation, and natural-language cart add/view/update/remove. |
| `eval/run_cart_e2e.py --http-only` | `python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000 --http-only` | Skips natural-language cart assertions when LLM access is unavailable. |

## Android client block-message update

| Type / member | Signature | Description |
|---------------|-----------|-------------|
| `MessageBlock.TextBlock` | `id: String, content: String` | Ordered text block in one chat message. |
| `MessageBlock.ProductBlock` | `id: String, product: Product` | Ordered product card block in one chat message. |
| `MessageBlock.CompareBlock` | `id: String, table: CompareTable` | Ordered compare block in one chat message. |
| `Message` | `id, role, blocks, isStreaming, isError, interrupted` | Chat message model now stores ordered blocks instead of `content + products + compareTables`. |
| `StreamingStatus` | `phase, message, step, totalSteps` | Temporary backend status UI state, not stored inside `Message.blocks`. |
| `Product` | `productId, title, category, price, brand, subCategory, imageUrl, stock, detailUrl, landingUrl, highlights, stockStatus, unavailableReason, groupLabel` | Client product card model aligned with backend `block.product` payload. |
| `ProductDetail` | `product, description, specs, faq, reviewSummary` | Client model for `GET /api/products/{product_id}`. |
| `ChatEvent.StructuredStatus` | `status: StreamingStatus` | Parsed backend `status` event. |
| `ChatEvent.BlockText` | `messageId, blockId, content` | Parsed backend `block.type=text` event. |
| `ChatEvent.BlockTextDelta` | `messageId, blockId, content` | Parsed backend `block.type=text_delta` event. |
| `ChatEvent.BlockProduct` | `messageId, blockId, product` | Parsed backend `block.type=product` event. |
| `ChatEvent.BlockCompare` | `messageId, blockId, table` | Parsed backend `block.type=compare` event. |
| `ChatApiService.getProductDetail` | `suspend (productId: String) -> ProductDetail` | Calls `GET /api/products/{product_id}`. |
| `ChatUiState` | `messages, isLoading, streamingStatus, conversationId, cart, isCartLoading, cartError, productDetail, isProductDetailLoading, productDetailError` | Compose UI state after stage 4/5. |
| `ChatViewModel.refreshCart` | `() -> Unit` | Refreshes cart snapshot before cart UI is opened. |
| `ChatViewModel.openProductDetail` | `(product: Product) -> Unit` | Loads product detail sheet content. |
| `ChatScreen` | `(..., streamingStatus, cart, isCartLoading, productDetail, ...)` | Compose screen now renders ordered blocks, independent streaming status, product detail sheet, and refreshed cart entry points. |
| `CartSummaryBar` | `(cart, cartError, isCartLoading, onClick)` | Clicking summary should refresh cart first, then open cart sheet. |
