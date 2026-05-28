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
|-------|----------|------|
| `product` | `{"product_id": "...", "title": "...", "brand": "...", "category": "...", "sub_category": "...", "price": 99.0, "image_url": "..."}` | 检索到的商品卡片数据，在 LLM 回复之前发送 |
| `token` | `{"content": "这款"}` | LLM 生成的文本片段，逐 token 发送 |
| `done` | `{}` | 流结束标记 |

---

## 后端内部模块

### ingest.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_products` | `(dataset_dir: str) -> list[dict]` | 扫描数据集目录，返回商品字典列表 |
| `build_document` | `(product: dict) -> str` | 商品字典 → 可检索文本 |
| `ingest` | `(dataset_dir: str \| None = None) -> None` | 主入口，执行完整的导入流程 |

### retriever.py

| 函数 | 签名 | 说明 |
|------|------|------|
| `retrieve` | `(query: str, top_k: int = 5) -> list[dict]` | 语义检索、查询扩展、价格重排后返回 Top-K 商品 |

### embedding.py

| 函数/类 | 签名 | 说明 |
|------|------|------|
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

## Android 客户端关键类（规划）

| 类 | 位置 | 职责 |
|----|------|------|
| `Message` | `data/model/` | 对话消息数据类（角色、内容、关联商品列表） |
| `Product` | `data/model/` | 商品数据类（与后端 Product 对应） |
| `ChatApiService` | `data/api/` | OkHttp SSE 客户端，连接后端并解析事件流 |
| `ChatViewModel` | `viewmodel/` | 管理消息列表状态、调用 API、处理流式事件 |
| `ChatScreen` | `ui/chat/` | 聊天主界面 Composable |
| `MessageBubble` | `ui/chat/` | 消息气泡组件 |
| `ProductCard` | `ui/chat/` | 商品卡片组件 |
