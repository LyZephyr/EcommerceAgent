# 系统架构

## 整体架构

```text
┌──────────────────┐        SSE         ┌──────────────────────────────────────┐
│ Android Client   │ ────────────────▶  │ FastAPI Server                       │
│ Kotlin/Compose   │   POST /api/chat   │                                      │
│                  │ ◀────────────────  │ ┌─────────────┐   ┌──────────────┐   │
│ ChatViewModel    │ product/compare/   │ │    Agent     │──▶│ Doubao API   │   │
│                  │ cart/token/done    │ │ (单跳工具调用)│   └──────────────┘   │
│ ChatApiService   │ /status            │ └──────┬──────┘                       │
│ ChatScreen       │                    │        │ tool_calls                   │
└──────────────────┘                    │        ▼                             │
                                        │ ┌─────────────┐   ┌──────────────┐  │
                                        │ │    Tools     │──▶│ Retriever    │  │
                                        │ └─────────────┘   └──────┬───────┘  │
                                        │                          ▼          │
                                        │ ┌─────────────┐   ┌──────────────┐  │
                                        │ │Conversation  │   │  ChromaDB    │  │
                                        │ └─────────────┘   └──────────────┘  │
                                        │ ┌─────────────┐                      │
                                        │ │ CartStore   │◀─ /api/cart*         │
                                        │ └─────────────┘                      │
                                        └──────────────────────────────────────┘
```

## Agent 调用流程

```text
用户消息 + 对话历史
    │
    ▼
Phase 1: LLM 决策（非流式）
    │
    ├─ 无 tool_calls → 直接回复
    │   适用于：反问澄清 / 追问已展示商品 / 基于历史的对比 / 寒暄
    │   可解析 <C> 结构化对比标记
    │   yield CompareEvent(可选) + TokenEvent(全文)
    │
    ├─ 有 tool_calls → 调用购物车工具
    │   适用于：自然语言加购 / 删除 / 改数量 / 查看 / 清空购物车
    │   yield StatusEvent + CartEvent(成功时) + TokenEvent
    │
    └─ 有 tool_calls → 调用 retrieve_products
        │
        ▼
    执行检索（每个 request 独立调用 retriever.retrieve）
        │
        ▼
    Phase 2: LLM 生成（流式）
        解析 <R> 推荐标记和可选 <C> 对比标记
        yield ProductEvent + CompareEvent(可选) + TokenEvent
```

## 模块职责

### server/config.py
- 从 `.env` 加载环境变量
- 导出全局配置常量，包括 API Key、模型端点、ChromaDB 路径等

### server/agent.py
- Agent 编排核心：单跳工具调用 + 流式生成
- Phase 1：LLM 接收对话历史 + 工具定义，决定调用工具还是直接回复
- Phase 2（仅工具调用时）：将工具返回的多组商品资料注入上下文，LLM 流式生成推荐回复
- 直接回复场景：反问澄清、追问已展示商品、寒暄等
- 购物车工具场景：执行确定性状态操作，产出 CartEvent 并返回简短操作结果
- 解析 `<R>` 推荐标记和可选 `<C>` 结构化对比标记，产出 TokenEvent / ProductEvent / CompareEvent / CartEvent / StatusEvent

### server/tools/\_\_init\_\_.py
- 工具注册表：维护工具定义列表和执行器映射
- 提供统一的 `execute(name, arguments)` 分发接口

### server/tools/cart.py
- 定义 `add_to_cart`、`remove_from_cart`、`update_cart_item`、`view_cart`、`clear_cart` 工具 schema
- 将 `product_id`、`recent_position`、`cart_position`、`title_keyword` 等工具参数解析为后端可信商品或购物车条目
- 加购只从最近展示商品池取商品快照；删除和改数量只操作当前购物车快照
- 指代缺失、位置不存在或关键词匹配多项时返回失败消息，不猜测商品

### server/tools/retrieve_products.py
- 定义 `retrieve_products` 工具的 OpenAI Function Calling schema
- `execute()`：接收 `requests[]`，将每个 request 转为 `retriever.retrieve()` 的 intent dict 并独立执行检索
- `parse_intent()`：通过强制工具调用提取检索意图（供离线评估使用）

### server/conversation.py
- 内存会话存储：`conversation_id -> list[message]`
- 滑动窗口：保留最近 10 轮对话
- 提供 `get_or_create_id`、`get_history`、`append` 接口

### server/cart_store.py
- 内存购物车存储：`conversation_id -> product_id -> cart item`
- 最近展示商品池：记录每个会话最近 20 个已通过 `product` SSE 发送的商品卡片快照
- 购物车加购只接受最近展示商品池中的后端可信商品快照，不从客户端接收标题、价格或图片
- 提供 `record_recent_product`、`get_recent_product`、`get_recent_product_by_position`、`list_recent_products`、`add_item`、`remove_item`、`update_item`、`clear_cart`、`snapshot`

### server/retriever.py
- 模块级初始化 ChromaDB PersistentClient，复用连接
- 接收用户 query 和 intent，用 rewritten_query 做向量检索
- 结合 category / SKU 价格范围 / brand 的 ChromaDB metadata filter
- 用向量距离、must_have_terms 命中率和 exclude_terms 违规分加权重排
- exclude_terms 对商品正文/元数据和用户评论分段采用指数衰减惩罚（正文 0.25^n，评论 0.15^n），并保护否定上下文
- 返回 Top-K 商品信息

### server/ingest.py
- 扫描 `ecommerce_agent_dataset/` 下所有类目目录
- 解析商品 JSON 文件
- 每个商品生成一条紧凑的 embedding 文本（标题+品牌+类目+价格+卖点+FAQ 问题摘要+评价摘要），控制在 512 token 以内
- 向量化文本与存储文本分离：embedding 基于紧凑文本计算，ChromaDB documents 存完整商品原文供 LLM 阅读
- 写入 ChromaDB，每个 product_id 对应一条向量记录

### server/embedding.py
- 统一创建 ChromaDB embedding function
- 使用 `BAAI/bge-base-zh-v1.5`（512 token 窗口）

### server/schemas.py
- 定义 `ChatRequest`：聊天请求体
- 定义 `Product`：商品卡片数据

### server/main.py
- FastAPI 应用入口
- 配置 CORS 中间件
- 挂载 `/assets` 静态资源路径，用于返回商品图片
- 提供 `GET /health`
- 提供 `POST /api/chat` SSE 端点：委托 `agent.run_turn()` 执行，将事件流转为 SSE
- 在发送 `product` SSE 事件时写入最近展示商品池
- 在收到 `CartEvent` 时发送 `cart` SSE 事件，同步最新购物车快照
- 提供购物车 HTTP 接口：`GET /api/cart`、`POST /api/cart/items`、`PATCH /api/cart/items/{product_id}`、`DELETE /api/cart/items/{product_id}`、`DELETE /api/cart`

### client-android/
- `MainActivity`：应用入口，启用 edge-to-edge 后挂载 `ChatRoute`
- `data/model/Message.kt`：定义聊天消息、消息角色和关联商品列表
- `data/model/Product.kt`：定义与后端商品卡片对应的客户端商品模型
- `data/api/ChatApiService.kt`：使用 OkHttp EventSource 连接 `POST /api/chat`，将 SSE 事件转换为 Kotlin `Flow<ChatEvent>`
- `data/api/ChatEvent.kt`：定义客户端可消费的 `ProductFound`、`Token`、`Done`、`Error` 事件
- `viewmodel/ChatViewModel.kt`：维护 `ChatUiState`、会话 ID、消息列表、流式响应任务和取消逻辑
- `ui/chat/ChatScreen.kt`：实现 Compose 聊天主界面、输入栏、消息气泡、商品横向卡片、商品详情弹窗和图片渲染
- `ui/theme/`：定义 Material3 主题色与动态色适配
- `app/build.gradle.kts`：启用 `BuildConfig.API_BASE_URL`，并引入 OkHttp、OkHttp SSE、Coil、Lifecycle ViewModel Compose 与 Material Icons 依赖
- `AndroidManifest.xml`：声明网络权限，并允许 debug 场景访问本机 FastAPI 的明文 HTTP 地址

## 数据流

```text
用户输入文字
    │
    ▼
ChatScreen
    │ onSendMessage
    ▼
ChatViewModel
    │ 1. 追加用户消息
    │ 2. 创建空的流式 assistant 消息
    │ 3. 调用 ChatApiService.streamChat(message, conversationId)
    ▼
ChatApiService
    │ POST {"message": "...", "conversation_id": "..."} 到 /api/chat
    ▼
FastAPI
    │ 1. Agent Phase 1：LLM 接收历史+工具定义，决策是否调用工具
    │    - 无需检索：直接生成回复（反问/追问/寒暄）
    │    - 购物车操作：调用 cart 工具，更新/查看当前会话购物车
    │    - 需要检索：调用 retrieve_products 工具，普通推荐使用 1 个 request，组合推荐使用多个 request
    │ 2. Agent Phase 2（仅工具调用时）：
    │    - 多组检索结果注入上下文，LLM 流式生成推荐回复
    │    - 解析 <R> 标记，只发送 LLM 推荐的商品卡片
    │    - 解析可选 <C> 标记，发送结构化对比事件
    ▼
SSE event: status (可选)
    │ 工具调用时发送，客户端可展示"正在检索..."或"正在更新购物车..."
    ▼
SSE event: cart (可选)
    │ 自然语言购物车工具成功执行后发送，携带当前 CartSnapshot
    ▼
SSE event: product
    │ 仅包含 LLM 明确推荐的商品；组合推荐也按扁平商品列表发送，不按子需求分组
    │ FastAPI 同步记录到当前 conversation_id 的最近展示商品池
    ▼
SSE event: compare (可选)
    │ 仅对比决策场景发送，携带结构化对比表数据
    ▼
SSE event: token
    │ ChatApiService 解析为 Token
    │ ChatViewModel 拼接到 assistant 消息 content
    ▼
SSE event: done
    │ ChatViewModel 结束流式状态
    ▼
ChatScreen 渲染消息气泡、商品卡片、图片和详情弹窗
```

## 购物车 HTTP 数据流

```text
商品卡片按钮 / 购物车弹窗
    │
    ▼
FastAPI /api/cart*
    │ 使用 conversation_id 定位会话
    │ POST /api/cart/items 只接收 product_id + quantity
    ▼
CartStore
    │ 从最近展示商品池取回后端可信商品快照
    │ 更新当前会话内存购物车
    ▼
CartSnapshot
    │ items + total_quantity + total_price
    ▼
客户端刷新购物车摘要和明细
```

## 自然语言购物车数据流

```text
用户输入“第二个加两件”“删掉购物车里的耳机”
    │
    ▼
Agent Phase 1
    │ 选择 add_to_cart / remove_from_cart / update_cart_item / view_cart / clear_cart
    ▼
server/tools/cart.py
    │ 使用 conversation_id 读取最近展示商品池或购物车快照
    │ 解析 recent_position / cart_position / title_keyword
    ▼
CartStore
    │ 执行确定性 add / remove / update / snapshot / clear
    ▼
CartEvent
    │ /api/chat 转为 SSE event: cart
    ▼
TokenEvent
    │ 返回自然语言操作结果或反问
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Python 3.10+ / FastAPI |
| Agent 编排 | 单跳工具调用（OpenAI Function Calling 协议） |
| 向量数据库 | ChromaDB（嵌入式） |
| Embedding | BAAI/bge-base-zh-v1.5（512 token 窗口） |
| LLM | Doubao-Seed-2.0-lite（Ark API） |
| 流式传输 | SSE (Server-Sent Events) |
| Android UI | Kotlin / Jetpack Compose / Material3 |
| Android 状态管理 | ViewModel + Kotlin Flow / StateFlow |
| Android 网络 | OkHttp + OkHttp SSE EventSource |
| Android 图片 | Coil Compose |
| Android 配置 | Gradle Version Catalog + BuildConfig.API_BASE_URL |
## Android compare display extension

The Android client parses backend `compare` SSE events into `CompareTable` models, stores them on the active assistant `Message`, and renders comparison tables inline before the existing flat product-card list. Combination recommendations continue to use the existing ungrouped horizontal product cards.
