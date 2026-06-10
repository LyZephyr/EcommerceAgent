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

**SSE 事件类型**：

| event | data 结构 | 说明 |
|-------|-----------|------|
| `status` | `{"message": "正在检索商品..."}` 或 `{"message": "正在更新购物车..."}` | Agent 正在执行工具调用，仅工具调用时发送 |
| `product` | `{"product_id": "...", "title": "...", "brand": "...", "category": "...", "sub_category": "...", "price": 99.0, "image_url": "..."}` | LLM 明确推荐的商品卡片 |
| `compare` | `{"products": [{"product_id": "...", "title": "..."}], "rows": [{"dimension": "价格", "values": {"product_id": "..."}}]}` | 多商品对比表数据，仅对比决策场景发送 |
| `cart` | `{"conversation_id": "...", "items": [...], "total_quantity": 2, "total_price": 198.0}` | 自然语言购物车工具成功执行后同步当前购物车快照 |
| `token` | `{"content": "这款"}` | LLM 生成的文本片段 |
| `done` | `{}` | 流结束标记 |

---

### GET /api/cart

查看当前会话购物车。

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
      "quantity": 2
    }
  ],
  "total_quantity": 2,
  "total_price": 198.0
}
```

---

### POST /api/cart/items

把最近展示过的商品加入购物车。接口只接受 `product_id` 和 `quantity`，商品标题、价格和图片由后端最近展示商品池解析。

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
| `404` | 商品不在当前会话最近展示商品池中 |
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
| `TOP_K` | 默认检索返回数量 |

### agent.py

| 类/函数 | 签名 | 说明 |
|---------|------|------|
| `TokenEvent` | `@dataclass: content: str` | 文本片段事件 |
| `ProductEvent` | `@dataclass: product_id: str, product_data: dict` | 商品推荐事件 |
| `StatusEvent` | `@dataclass: status: str` | 状态提示事件 |
| `CompareEvent` | `@dataclass: payload: dict` | 结构化对比事件 |
| `CartEvent` | `@dataclass: payload: dict` | 购物车快照同步事件 |
| `run_turn` | `async (conversation_id: str, user_message: str) -> AsyncIterator[TokenEvent \| ProductEvent \| StatusEvent \| CompareEvent \| CartEvent]` | 执行一轮对话：Phase 1 决策 + 检索生成或购物车工具操作 |

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
| `add_to_cart` | `product_id?`, `recent_position?`, `title_keyword?`, `quantity?` | 从最近展示商品池解析商品并加购 |
| `remove_from_cart` | `product_id?`, `cart_position?`, `title_keyword?` | 从购物车删除商品 |
| `update_cart_item` | `product_id?`, `cart_position?`, `title_keyword?`, `quantity` | 修改购物车商品数量 |
| `view_cart` | 无 | 查看当前购物车 |
| `clear_cart` | 无 | 清空当前购物车 |

### tools/retrieve_products.py

| 函数/常量 | 签名 | 说明 |
|-----------|------|------|
| `TOOL_DEFINITION` | `dict` | OpenAI Function Calling 格式的工具定义，参数为 `requests[]` |
| `execute` | `(arguments: dict) -> list[dict]` | 遍历 `requests[]`，每个 request 独立调用 `retriever.retrieve()`，返回多组 Top-K 商品 |
| `parse_intent` | `async (query: str) -> dict` | 通过强制工具调用提取单 request 检索意图（供离线评估使用） |

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
| `record_recent_product` | `(conversation_id: str, product: dict) -> None` | 记录当前会话已通过商品卡片展示的后端商品快照 |
| `get_recent_product` | `(conversation_id: str, product_id: str) -> dict \| None` | 按商品 ID 从最近展示商品池取可信商品快照 |
| `get_recent_product_by_position` | `(conversation_id: str, position: int) -> dict \| None` | 按 1-based 展示顺序取最近展示商品，供后续指代解析使用 |
| `list_recent_products` | `(conversation_id: str) -> list[dict]` | 返回当前会话最近展示商品快照列表 |
| `add_item` | `(conversation_id: str, product: dict, quantity: int = 1) -> dict` | 加购商品；已有商品累加数量；返回购物车快照 |
| `remove_item` | `(conversation_id: str, product_id: str) -> dict` | 删除购物车商品；不存在时抛出 `KeyError` |
| `update_item` | `(conversation_id: str, product_id: str, quantity: int) -> dict` | 设置购物车商品数量；不存在时抛出 `KeyError` |
| `clear_cart` | `(conversation_id: str) -> dict` | 清空当前会话购物车并返回快照 |
| `snapshot` | `(conversation_id: str) -> dict` | 返回 `items`、`total_quantity`、`total_price` 购物车快照 |

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

| 函数 | 签名 | 说明 |
|------|------|------|
| `initialize_database` | `() -> None` | 创建 MySQL database 和 `products` 表 |
| `load_dataset_to_mysql` | `(dataset_dir: str \| None = None) -> int` | 扫描数据集并 upsert 到 MySQL，返回加载商品数 |
| `upsert_products` | `(records: list[dict]) -> None` | 按 `product_id` 幂等写入商品记录 |
| `get_products_by_ids` | `(product_ids: list[str]) -> list[dict]` | 按传入顺序批量读取商品快照，缺失商品会被忽略 |
| `get_product_by_id` | `(product_id: str) -> dict \| None` | 读取单个商品快照 |
| `get_products_updated_after` | `(updated_after: datetime) -> list[dict]` | 查询指定时间之后更新的商品，供后续增量同步使用 |
| `list_active_products` | `() -> list[dict]` | 返回所有上架商品 |
| `count_products` | `() -> int` | 返回 MySQL `products` 表商品数 |
| `product_to_record` | `(product: dict) -> dict` | 将数据集商品对象转换为 MySQL 记录 |

### retriever.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `retrieve` | `(query: str, top_k: int = 5, intent: dict \| None = None) -> list[dict]` | 基于 intent 做 metadata filter + 向量检索，结合 `distance`、`must_have_terms`、`exclude_terms` 加权重排返回 Top-K 商品 |

### ingest.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_products` | `(dataset_dir: str) -> list[dict]` | 扫描数据集目录，返回商品字典列表 |
| `build_embedding_text` | `(product: dict) -> str` | 构建紧凑的 embedding 文本，包含标题、品牌、类目、SKU 属性摘要、卖点、FAQ 问题摘要和评价摘要，不加入 `base_price` 和 SKU `price` 字段 |
| `build_full_document` | `(product: dict) -> str` | 构建完整商品文档，存入 ChromaDB documents 字段 |
| `ingest` | `(dataset_dir: str \| None = None) -> None` | 主入口：加载数据 -> 构建 embedding 文本 -> 写入 ChromaDB |

### embedding.py

| 函数/类 | 签名 | 说明 |
|---------|------|------|
| `get_embedding_function` | `() -> EmbeddingFunction` | 创建 ChromaDB embedding function |

### schemas.py

| 类 | 字段 | 说明 |
|----|------|------|
| `ChatRequest` | `message: str`, `conversation_id: str \| None` | 聊天请求 |
| `Product` | `product_id`, `title`, `brand`, `category`, `sub_category`, `price`, `image_url` | 商品卡片数据 |
| `CartItem` | `Product` 字段 + `quantity: int` | 购物车商品明细 |
| `CartSnapshot` | `conversation_id`, `items`, `total_quantity`, `total_price` | 购物车快照响应 |
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
HF_HUB_OFFLINE=1 server/.venv/bin/python eval/run_retrieval_eval.py

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
| `ChatEvent` | `ProductFound(product)`, `Token(content)`, `Done`, `Error(message)` | SSE 事件客户端封装 |

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
| `CompareTable` | `products: List<CompareProduct>`, `rows: List<CompareRow>` | Client model for `compare` SSE table payloads. |
| `Message.compareTables` | `List<CompareTable>` | Structured comparison tables attached to an assistant message. |
| `Message.status` | `String?` | Current streaming status text from backend `status` events. |
| `ChatEvent.Status` | `message: String` | Parsed backend `status` SSE event. |
| `ChatEvent.Compare` | `table: CompareTable` | Parsed backend `compare` SSE event. |
| `CompareTableCard` | `(table: CompareTable)` | Compose renderer for comparison tables inside the message stream. |

## Android client cart UI extension

| Type / member | Signature | Description |
|---------------|-----------|-------------|
| `CartItem` | `productId`, `title`, `category`, `price`, `brand`, `subCategory`, `imageUrl`, `quantity`, `subtotal` | Client model for one cart row. |
| `Cart` | `conversationId`, `items`, `totalQuantity`, `totalPrice` | Client model for backend cart snapshots. |
| `ChatEvent.CartUpdated` | `cart: Cart` | Parsed backend `cart` SSE event. |
| `ChatApiService.getCart` | `suspend (conversationId: String) -> Cart` | Calls `GET /api/cart`. |
| `ChatApiService.addCartItem` | `suspend (conversationId: String, productId: String, quantity: Int = 1) -> Cart` | Calls `POST /api/cart/items`. |
| `ChatApiService.updateCartItem` | `suspend (conversationId: String, productId: String, quantity: Int) -> Cart` | Calls `PATCH /api/cart/items/{product_id}`. |
| `ChatApiService.removeCartItem` | `suspend (conversationId: String, productId: String) -> Cart` | Calls `DELETE /api/cart/items/{product_id}`. |
| `ChatApiService.clearCart` | `suspend (conversationId: String) -> Cart` | Calls `DELETE /api/cart`. |
| `ChatUiState.cart` | `Cart` | Current cart snapshot for the active conversation. |
| `ChatUiState.isCartLoading` | `Boolean` | True while a direct cart HTTP mutation is in flight. |
| `ChatUiState.cartError` | `String?` | Last cart mutation error shown in the cart summary/sheet. |
| `CartSummaryBar` | `(cart, cartError, isCartLoading, onClick)` | Summary strip above the chat input. |
| `CartSheet` | `(cart, isCartLoading, cartError, onDismiss, onIncrement, onDecrement, onRemove, onClear)` | Bottom sheet for cart detail and management. |

## End-to-end validation

| Script | Command | Coverage |
|--------|---------|----------|
| `eval/run_cart_e2e.py` | `python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000` | Validates HTTP cart CRUD, SSE recommendation product capture, conversation isolation, and natural-language cart add/view/update/remove. |
| `eval/run_cart_e2e.py --http-only` | `python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000 --http-only` | Skips natural-language cart assertions when LLM access is unavailable. |
