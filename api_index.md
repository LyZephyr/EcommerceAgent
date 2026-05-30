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
| `product` | `{"product_id": "...", "title": "...", "brand": "...", "category": "...", "sub_category": "...", "price": 99.0, "image_url": "..."}` | 检索到的商品卡片数据，在 LLM 回复之前发送 |
| `token` | `{"content": "这款"}` | LLM 生成的文本片段，逐 token 发送 |
| `done` | `{}` | 流结束标记 |

---

## 后端内部模块

### ingest.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_products` | `(dataset_dir: str) -> list[dict]` | 扫描数据集目录，返回商品字典列表 |
| `build_document` | `(product: dict) -> str` | 商品字典转换为可检索文本 |
| `ingest` | `(dataset_dir: str \| None = None) -> None` | 主入口，执行完整导入流程 |

### retriever.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `retrieve` | `(query: str, top_k: int = 5) -> list[dict]` | 语义检索、查询扩展、价格重排后返回 Top-K 商品 |

### embedding.py

| 函数/类 | 签名 | 说明 |
|---------|------|------|
| `get_embedding_function` | `() -> EmbeddingFunction` | 创建 ChromaDB embedding function |

### generator.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `generate_stream` | `async (query: str, context: list[dict]) -> AsyncIterator[str]` | 流式调用 LLM 生成回复 |

### schemas.py

| 类 | 字段 | 说明 |
|----|------|------|
| `ChatRequest` | `message: str`, `conversation_id: str \| None` | 聊天请求 |
| `Product` | `product_id`, `title`, `brand`, `category`, `sub_category`, `price`, `image_url` | 商品卡片数据 |

---

## Android 客户端接口

### data/model/Message.kt

| 类型 | 成员 | 说明 |
|------|------|------|
| `MessageRole` | `User`, `Assistant` | 消息角色枚举 |
| `Message` | `id: String`, `role: MessageRole`, `content: String`, `products: List<Product>`, `isStreaming: Boolean`, `isError: Boolean` | 聊天消息状态，assistant 消息可携带商品卡片列表 |

### data/model/Product.kt

| 类型 | 字段 | 说明 |
|------|------|------|
| `Product` | `productId: String`, `title: String`, `category: String`, `price: Double`, `brand: String?`, `subCategory: String?`, `imageUrl: String?` | 客户端商品模型，与后端 `product` SSE 事件对应 |

### data/api/ChatEvent.kt

| 类型 | 成员 | 说明 |
|------|------|------|
| `ChatEvent` | `ProductFound(product)`, `Token(content)`, `Done`, `Error(message)` | `ChatApiService` 对 SSE 事件的客户端封装 |

### data/api/ChatApiService.kt

| 成员 | 签名 | 说明 |
|------|------|------|
| `ChatApiService` | `(baseUrl: String = BuildConfig.API_BASE_URL, client: OkHttpClient = ...)` | SSE API 客户端，默认连接 Gradle 注入的后端地址 |
| `streamChat` | `(message: String, conversationId: String?) -> Flow<ChatEvent>` | POST `/api/chat`，解析 `product`、`token`、`done` 事件并以 Flow 发出 |

### viewmodel/ChatViewModel.kt

| 类型/成员 | 签名 | 说明 |
|-----------|------|------|
| `ChatUiState` | `messages: List<Message>`, `isLoading: Boolean`, `conversationId: String` | Compose 层订阅的聊天 UI 状态 |
| `ChatViewModel.uiState` | `StateFlow<ChatUiState>` | 只读状态流 |
| `sendMessage` | `(text: String) -> Unit` | 追加用户消息，启动 SSE 流式请求，并把商品与 token 合并到 assistant 消息 |
| `cancelResponse` | `() -> Unit` | 取消当前流式响应并清除 loading 状态 |

### ui/chat/ChatScreen.kt

| Composable | 签名 | 说明 |
|------------|------|------|
| `ChatRoute` | `(viewModel: ChatViewModel = viewModel())` | 连接 `ChatViewModel` 与聊天界面 |
| `ChatScreen` | `(messages, isLoading, onSendMessage, onCancelResponse)` | 聊天主界面，包含顶部栏、消息列表和输入栏 |
| `MessageItem` | `(message, onProductClick)` | 单条消息与其商品横向列表 |
| `MessageBubble` | `(message)` | 用户/助手/错误消息气泡 |
| `ProductCard` | `(product, onClick)` | 商品卡片，展示图片、标题、价格、品牌和类目 |
| `ProductImage` | `(imageUrl, modifier)` | 使用 Coil 加载商品图片，无图时显示占位 |
| `ChatInputBar` | `(input, isLoading, onInputChange, onSend, onCancel)` | 输入框、发送按钮和流式取消按钮 |
| `ProductDialog` | `(product, onDismiss)` | 商品详情弹窗 |
| `ProductInfoRow` | `(label, value)` | 商品详情字段行 |

### MainActivity.kt

| 类型/成员 | 签名 | 说明 |
|-----------|------|------|
| `MainActivity.onCreate` | `(savedInstanceState: Bundle?) -> Unit` | 启用 edge-to-edge，应用 `EcommerceRagAgentTheme` 并挂载 `ChatRoute` |

### Android 构建与运行配置

| 文件 | 配置 | 说明 |
|------|------|------|
| `app/build.gradle.kts` | `BuildConfig.API_BASE_URL = "http://10.0.2.2:8000"` | Android 模拟器访问宿主机 FastAPI 的默认地址 |
| `app/build.gradle.kts` | OkHttp、OkHttp SSE、Coil Compose、Lifecycle ViewModel Compose、Material Icons Extended | 客户端聊天、流式网络、图片和 UI 所需依赖 |
| `AndroidManifest.xml` | `INTERNET`, `usesCleartextTraffic=true` | 允许 debug 客户端访问本地 HTTP 后端 |
| `gradle.properties` | `kotlin.compiler.execution.strategy=in-process` | 避免当前工作区 Kotlin daemon 启动受限导致构建失败 |
