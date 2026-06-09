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
| `status` | `{"message": "正在检索商品..."}` | Agent 正在执行工具调用，仅工具调用时发送 |
| `product` | `{"product_id": "...", "title": "...", "brand": "...", "category": "...", "sub_category": "...", "price": 99.0, "image_url": "..."}` | LLM 明确推荐的商品卡片 |
| `compare` | `{"products": [{"product_id": "...", "title": "..."}], "rows": [{"dimension": "价格", "values": {"product_id": "..."}}]}` | 多商品对比表数据，仅对比决策场景发送 |
| `token` | `{"content": "这款"}` | LLM 生成的文本片段 |
| `done` | `{}` | 流结束标记 |

---

## 后端内部模块

### agent.py

| 类/函数 | 签名 | 说明 |
|---------|------|------|
| `TokenEvent` | `@dataclass: content: str` | 文本片段事件 |
| `ProductEvent` | `@dataclass: product_id: str, product_data: dict` | 商品推荐事件 |
| `StatusEvent` | `@dataclass: status: str` | 状态提示事件 |
| `CompareEvent` | `@dataclass: payload: dict` | 结构化对比事件 |
| `run_turn` | `async (conversation_id: str, user_message: str) -> AsyncIterator[TokenEvent \| ProductEvent \| StatusEvent \| CompareEvent]` | 执行一轮对话：Phase 1 决策 + Phase 2 工具调用/生成 |

### tools/\_\_init\_\_.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `execute` | `(name: str, arguments: dict) -> list[dict]` | 按工具名分发执行 |

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

### retriever.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `retrieve` | `(query: str, top_k: int = 5, intent: dict \| None = None) -> list[dict]` | 基于 intent 做 metadata filter + 向量检索，结合 `distance`、`must_have_terms`、`exclude_terms` 加权重排返回 Top-K 商品 |

### ingest.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_products` | `(dataset_dir: str) -> list[dict]` | 扫描数据集目录，返回商品字典列表 |
| `build_embedding_text` | `(product: dict) -> str` | 构建紧凑的 embedding 文本，控制在 512 token 以内 |
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
