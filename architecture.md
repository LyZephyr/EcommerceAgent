# 系统架构

## 整体架构

```text
┌──────────────────┐        SSE        ┌──────────────────────────────────────┐
│ Android Client   │ ────────────────▶ │ FastAPI Server                       │
│ Kotlin/Compose   │   POST /api/chat  │                                      │
│                  │ ◀──────────────── │ ┌───────────┐     ┌──────────────┐   │
│ ChatViewModel    │ product/token/done│ │  Intent   │ ──▶ │ Doubao API   │   │
│ ChatApiService   │                   │ └─────┬─────┘     └──────────────┘   │
│ ChatScreen       │                   │       ▼                              │
└──────────────────┘                   │ ┌───────────┐     ┌──────────────┐   │
                                       │ │ Retriever │ ──▶ │ ChromaDB     │   │
                                       │ └─────┬─────┘     └──────────────┘   │
                                       │       ▼                              │
                                       │ ┌───────────┐     ┌──────────────┐   │
                                       │ │ Generator │ ──▶ │ Doubao API   │   │
                                       │ └───────────┘     └──────────────┘   │
                                       └──────────────────────────────────────┘
```

## 模块职责

### server/config.py
- 从 `.env` 加载环境变量
- 导出全局配置常量，包括 API Key、模型端点、ChromaDB 路径等

### server/ingest.py
- 扫描 `ecommerce_agent_dataset/` 下所有类目目录
- 解析商品 JSON 文件
- 每个商品按语义拆分为 2-3 个 chunk（core 卖点 / faq 问答 / review 评价），每个 chunk 带标题+品牌+类目前缀
- 向量化文本与存储文本分离：embedding 基于精简 chunk 计算，ChromaDB documents 存完整商品原文供 LLM 阅读
- 写入 ChromaDB，同一 product_id 对应多条向量记录

### server/embedding.py
- 统一创建 ChromaDB embedding function
- 使用 `BAAI/bge-base-zh-v1.5`（512 token 窗口）

### server/intent.py
- 调用 Doubao API 解析用户购物意图
- 输出结构化 JSON：改写 query、类目、价格区间、品牌排除、否定约束
- 解析失败时回退为原始 query

### server/retriever.py
- 加载 ChromaDB collection
- 接收用户 query 和 intent，用 rewritten_query 做向量检索
- 结合 category / price / brand 的 ChromaDB metadata filter
- 按 product_id 去重（保留距离最小的 chunk）
- 词法匹配 + 价格加权轻量重排
- 返回 Top-K 商品信息

### server/generator.py
- 构造 System Prompt + User Prompt，并注入检索上下文
- 要求 LLM 在回复开头输出 `<R>product_id,...</R>` 推荐标记
- 调用 Doubao API 的 OpenAI 兼容接口，使用 `stream=True`
- 逐 token yield 生成结果

### server/schemas.py
- 定义 `ChatRequest`：聊天请求体
- 定义 `Product`：商品卡片数据

### server/main.py
- FastAPI 应用入口
- 配置 CORS 中间件
- 挂载 `/assets` 静态资源路径，用于返回商品图片
- 提供 `GET /health`
- 提供 `POST /api/chat` SSE 端点：意图解析 → 混合检索 → LLM 流式生成 → 解析 `<R>` 标记 → 只发送 LLM 推荐的商品卡片 → 流式文本

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
    │ 1. LLM 意图解析（query 改写 + 结构化 filter）
    │ 2. ChromaDB 混合检索 Top-K 并重排
    │ 3. 组装 prompt + context，调用 Doubao API stream
    │ 4. 解析 <R> 标记，只发送 LLM 推荐的 product 事件
    ▼
SSE event: product
    │ 仅包含 LLM 明确推荐的商品
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

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Python 3.10+ / FastAPI |
| 向量数据库 | ChromaDB（嵌入式） |
| Embedding | BAAI/bge-base-zh-v1.5（512 token 窗口） |
| LLM | Doubao-Seed-2.0-lite（Ark API） |
| 流式传输 | SSE (Server-Sent Events) |
| Android UI | Kotlin / Jetpack Compose / Material3 |
| Android 状态管理 | ViewModel + Kotlin Flow / StateFlow |
| Android 网络 | OkHttp + OkHttp SSE EventSource |
| Android 图片 | Coil Compose |
| Android 配置 | Gradle Version Catalog + BuildConfig.API_BASE_URL |
