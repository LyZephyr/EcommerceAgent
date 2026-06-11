# 系统架构

## 整体架构

```text
┌──────────────────┐        SSE         ┌──────────────────────────────────────┐
│ Android Client   │ ────────────────▶  │ FastAPI Server                       │
│ Kotlin/Compose   │   POST /api/chat   │                                      │
│                  │ ◀────────────────  │ ┌─────────────┐   ┌──────────────┐   │
│ ChatViewModel    │ block/cart/done    │ │    Agent     │──▶│ Doubao API   │   │
│                  │ /status/error      │ │ (ReAct loop) │   └──────────────┘   │
│ ChatApiService   │                    │ └──────┬──────┘                       │
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
                                        │ ┌─────────────┐                      │
                                        │ │ProductStore │──▶ MySQL products    │
                                        │ └─────────────┘                      │
                                        │ ┌─────────────┐                      │
                                        │ │ChromaSync   │──▶ MySQL sync_state  │
                                        │ └──────┬──────┘                      │
                                        │        ▼                             │
                                        │     ChromaDB                         │
                                        └──────────────────────────────────────┘
```

## Agent 调用流程

```text
用户消息 + 对话历史
    │
    ▼
ReAct loop: LLM 决策（最多 3 步工具调用）
    │
    ├─ LLM 超时 / 工具调用格式错误 / 工具执行异常 / 最终标记非法
    │   结构化错误反馈给 LLM 修正，同类问题最多连续重试 2 次，单个恢复阶段整体最多 6 次
    │   重试耗尽后记录错误上下文，/api/chat 发送 error + done
    │
    ├─ 无 tool_calls → 直接回复
    │   适用于：反问澄清 / 追问已展示商品 / 基于历史的对比 / 寒暄
    │   可解析 <C> 结构化对比标记
    │   yield BlockCompareEvent(可选) + BlockTextEvent(全文)
    │
    ├─ 有 tool_calls → 调用购物车工具
    │   适用于：自然语言批量加购 / 查询近期商品 / 删除 / 改数量 / 查看 / 清空购物车
    │   yield StructuredStatusEvent + CartEvent(成功时)
    │   工具结果返回 LLM，继续决策或生成最终回复
    │
    └─ 有 tool_calls → 调用 retrieve_products
        │
        ▼
    执行检索（每个 request 独立调用 retriever.retrieve）
        │
        ▼
    工具结果返回 LLM，最终 streaming 生成回复
        解析 <R> 推荐标记和可选 <C> 对比标记
        yield BlockTextDeltaEvent + BlockProductEvent + BlockCompareEvent(可选)
```

## 模块职责

### server/config.py
- 从 `.env` 加载环境变量
- 在导入 Hugging Face 相关库之前设置 `HF_ENDPOINT`（默认 `https://hf-mirror.com`）与 `HF_HUB_OFFLINE`
- 导出全局配置常量，包括 API Key、模型端点、MySQL 连接信息、ChromaDB 路径、Embedding 模型名等

### server/product_store.py
- MySQL 商品权威源：维护 `products` 表结构和数据访问接口
- 维护 `sync_state` 表，持久化 ChromaDB 增量同步水位
- 启动时确保数据库和商品表存在
- 将 `ecommerce_agent_dataset/` 商品 JSON 转换为商品记录，并按 `product_id` 幂等 upsert 到 MySQL
- 商品表保存标题、品牌、类目、价格、库存、上下架状态、图片、完整描述、原始 JSON 和 embedding 文本
- 提供 `get_products_by_ids`、`get_product_by_id`、`get_products_updated_after`、`list_active_products`、`count_products`、`get_sync_state`、`set_sync_state` 等接口，供检索补全、购物车校验和 ChromaDB 同步使用
- 提供 `product_card_payload()` 和 `get_product_detail()`，统一输出商品卡片/详情页公开字段、`detail_url`、`landing_url`、`highlights`、`stock_status` 和 `unavailable_reason`
- 商品详情从 MySQL 最新快照和 `raw_payload` 派生规格、FAQ 和评价摘要，但不向客户端暴露完整原始 JSON

### server/chroma_sync.py
- ChromaDB 后台增量同步模块
- `sync_once()` 读取 `sync_state.last_sync_at`，查询 MySQL 增量变更
- 对新增、修改、重新上架且有库存的商品 upsert 到 ChromaDB
- 对下架商品从 ChromaDB 删除
- 成功同步后持久化新的 `last_sync_at`
- 每轮同步完成后输出完成日志；有写入、更新或删除时记录对应商品 ID、标题、库存和更新时间等变更明细
- `run_periodic_sync()` 每 3 分钟在后台执行；失败只记录日志，下一轮重试，不阻塞在线请求
- 可通过 `python chroma_sync.py` 手动执行一次同步，Demo 前可用于强制追平索引
- 手动同步复用统一日志配置，只保留同步统计和异常等关键信息

### server/agent.py
- Agent 编排核心：最多 3 步 ReAct 工具循环 + 最终回复解析
- 存放 `SYSTEM_PROMPT` 等 LLM 提示词，包含工具使用规则、回复规则和隐藏事件标记规则
- LLM 接收对话历史 + 工具定义，决定调用工具还是直接回复；工具结果会回填给 LLM 继续决策
- 单次 LLM 调用超过 60 秒会中断，并作为可恢复错误反馈给 LLM 重试
- 记录 LLM 调用耗时、超时、可恢复错误、重试耗尽，以及每次工具调用的请求、摘要结果和执行耗时，便于排查 Agent 决策链路
- 对工具参数 JSON 解析失败、工具执行异常、空响应、非法 `<R>/<C>` 标记等边界错误生成结构化反馈，同类问题最多连续重试 2 次，单个恢复阶段整体最多 6 次，避免错误类型来回切换导致无限循环
- 本轮使用 `retrieve_products` 后，最终回复必须包含合法 `<R>` 推荐标记，并基于标记中的商品 ID 发送商品卡片
- 直接回复场景：反问澄清、追问已展示商品、寒暄等
- 购物车工具场景：执行确定性状态操作，成功时产出 CartEvent；最终自然语言回复由 LLM 基于工具结果生成
- 严格解析 `<R>` 推荐固定标签和 `<C>` 结构化对比标记，产出 BlockTextEvent / BlockProductEvent / BlockCompareEvent / CartEvent / StructuredStatusEvent；两类标记不能同时出现
- 检索或购物车工具完成后的最终回复使用 LLM streaming completion；推荐场景增量识别 `<INTRO>`、`<ITEM>`、`<REASON>`、`<OUTRO>`，只发送可见 `text_delta` 和商品块，隐藏标签不下发
- `<C>` 对比场景在 streaming 中缓冲到 `</C>` 闭合后一次性解析并发送完整 compare block
- streaming 期间记录首 chunk、首个可见输出、chunk 数、可见字符数和总耗时；客户端断开或 ASGI 取消时关闭当前 LLM stream，并将已发送可见内容以 `[interrupted]` 形式写入历史

### server/tools/\_\_init\_\_.py
- 工具注册表：维护工具定义列表和执行器映射
- 提供统一的 `execute(name, arguments)` 分发接口

### server/tools/cart.py
- 定义 `add_to_cart`、`list_recent_products`、`remove_from_cart`、`update_cart_item`、`view_cart`、`clear_cart` 工具 schema
- `add_to_cart` 只接受明确的 `product_ids[]` 和 `quantity`，支持批量加购；批量需求应一次工具调用完成
- `list_recent_products` 无参数，按推荐时间从近到远返回当前会话近期展示商品详情，仅用于 LLM 因上下文过长记忆模糊时补充记忆
- 加购先用近期商品池确认 `product_id` 属于当前会话，再由 `cart_store` 查询 MySQL 最新状态完成价格、库存和上下架校验
- 删除只操作当前购物车条目；改数量会重新校验 MySQL 最新库存和上下架状态
- 指代缺失或无法唯一确定时返回失败消息，不猜测商品

### server/tools/retrieve_products.py
- 定义 `retrieve_products` 工具的 OpenAI Function Calling schema
- `execute()`：接收 `requests[]`，将每个 request 转为 `retriever.retrieve()` 的 intent dict 并独立执行检索
- `parse_intent()`：复用 `agent.SYSTEM_PROMPT`，通过强制工具调用提取检索意图（供离线评估使用）

### server/conversation.py
- 内存会话存储：`conversation_id -> list[message]`
- 滑动窗口：保留最近 10 轮对话
- 提供 `get_or_create_id`、`get_history`、`append` 接口

### server/cart_store.py
- 内存购物车存储：`conversation_id -> product_id -> cart item`
- 近期展示商品池：记录每个会话最近 20 个已通过 `product` SSE 发送的轻量记录，只包含 `product_id`、`displayed_price` 和 `displayed_at`
- 近期展示商品池用于确认商品身份和价格变化提示，不作为商品标题、库存、当前价格等主数据来源
- 加购和改数量前按 `product_id` 查询 MySQL 最新商品；商品不存在、下架、无库存或库存不足时失败
- 购物车条目保存 `last_seen_price`，用于在后续快照刷新时识别用户尚未看到的价格变化
- 商品价格变化时使用 MySQL 最新价格，并在购物车快照 `messages` 中返回一次性提示
- 购物车快照每次重新读取 MySQL 最新价格、库存和上下架状态；缺货商品保留并标记不可用，下架或不存在商品会从内存购物车移除并返回提示
- 提供 `record_recent_product`、`get_recent_product_entry`、`list_recent_product_entries`、`list_recent_products`、`add_item`、`remove_item`、`update_item`、`clear_cart`、`snapshot`

### server/retriever.py
- 模块级初始化 ChromaDB PersistentClient，复用连接
- 接收用户 query 和 intent，用 rewritten_query 做向量检索
- 结合 category / brand 的 ChromaDB metadata filter 做粗召回；预算不使用 ChromaDB 价格 metadata，避免索引滞后导致漏召回
- 用向量距离、must_have_terms 命中率和 exclude_terms 违规分加权重排
- 重排后按 `product_id` 批量读取 MySQL 最新商品快照，并过滤 `is_active=false`、`stock<=0`、预算不匹配、类目不匹配和排除品牌
- 返回给 Agent 和 SSE 的标题、品牌、类目、价格、图片、库存状态来自 MySQL；ChromaDB distance 和 rerank_score 只作为排序信号
- exclude_terms 对商品正文/元数据和用户评论分段采用指数衰减惩罚（正文 0.25^n，评论 0.15^n），并保护否定上下文
- 返回 Top-K 商品信息

### server/ingest.py
- 扫描 `ecommerce_agent_dataset/` 下所有类目目录
- 解析商品 JSON 文件
- 每个商品生成一条紧凑的 embedding 文本（标题+品牌+类目+SKU 属性摘要+卖点+FAQ 问题摘要+评价摘要），控制在 512 token 以内；不加入价格、库存、上下架字段
- 向量化文本与存储文本分离：`product_store` 将紧凑文本和完整描述写入 MySQL，ChromaDB 初始构建从 MySQL 读取上架商品的 `embedding_text` 和 `description`
- ChromaDB metadata 只保留 `product_id`、标题、品牌、类目、二级类目、图片等稳定字段，不保存价格和库存作为在线展示依据
- 支持清空 collection 重建和对现有 collection 执行 upsert，每个 product_id 对应一条向量记录
- 暴露 `product_to_chroma_metadata()`，供初始构建和后台增量同步复用同一套 metadata 规则

### server/embedding.py
- 统一创建 ChromaDB embedding function
- 使用 `EMBEDDING_MODEL`（默认 `BAAI/bge-base-zh-v1.5`，512 token 窗口），经 `config` 配置的 `HF_ENDPOINT` 下载权重
- 进程内单例缓存 SentenceTransformer embedding function，并关闭 embedding 进度条，避免请求和后台同步重复加载模型或污染日志

### server/logging_config.py
- 后端统一日志配置
- 保持项目自身 INFO 级观测日志，压低 `httpx`、Hugging Face、SentenceTransformers、Transformers 等第三方库噪声

### server/schemas.py
- 定义 `ChatRequest`：聊天请求体
- 定义 `Product`：商品卡片数据，包含详情跳转、外部落地页、卖点、库存状态和不可用原因
- 定义 `ProductDetail`：商品详情响应，包含描述、规格、FAQ 和评价摘要

### server/main.py
- FastAPI 应用入口
- 启动时应用统一日志配置
- 启动时调用 `product_store.load_dataset_to_mysql()`，确保 MySQL 商品权威源已初始化并加载当前数据集
- 启动时创建 `chroma_sync.run_periodic_sync()` 后台任务，每 3 分钟从 MySQL 增量同步 ChromaDB
- 配置 CORS 中间件
- 挂载 `/assets` 静态资源路径，用于返回商品图片
- 提供 `GET /health`
- 提供 `POST /api/chat` SSE 端点：委托 `agent.run_turn()` 执行，将事件流转为 SSE；Agent 重试耗尽或异常时发送 `error` 事件并以 `done` 结束流
- 在发送 `product` SSE 事件时写入近期展示商品池
- 在收到 `CartEvent` 时发送 `cart` SSE 事件，同步最新购物车快照
- 提供 `GET /api/products/{product_id}` 公共商品详情接口，不绑定会话；商品下架或无库存仍返回详情，并通过 `stock_status` / `unavailable_reason` 禁用加购
- 商品详情接口只负责展示数据；加购仍走 `/api/cart*`，继续依赖当前会话近期展示商品池和 MySQL 最新状态校验
- 提供购物车 HTTP 接口：`GET /api/cart`、`POST /api/cart/items`、`PATCH /api/cart/items/{product_id}`、`DELETE /api/cart/items/{product_id}`、`DELETE /api/cart`

### client-android/
- `MainActivity`：应用入口，启用 edge-to-edge 后挂载 `ChatRoute`
- `data/model/Message.kt`：定义聊天消息、消息角色和关联商品列表
- `data/model/Product.kt`：定义与后端商品卡片对应的客户端商品模型
- `data/api/ChatApiService.kt`：使用 OkHttp EventSource 连接 `POST /api/chat`，将 SSE 事件转换为 Kotlin `Flow<ChatEvent>`
- `data/api/ChatEvent.kt`：定义客户端可消费的 `BlockText`、`BlockProduct`、`BlockCompare`、`Status`、`CartUpdated`、`Done`、`Error` 事件
- `viewmodel/ChatViewModel.kt`：维护 `ChatUiState`、会话 ID、消息列表、流式响应任务和取消逻辑
- `ui/chat/ChatScreen.kt`：实现 Compose 聊天主界面、输入栏、消息气泡、商品横向卡片、商品详情弹窗和图片渲染
- `ui/theme/`：定义 Material3 主题色与动态色适配
- `app/build.gradle.kts`：启用 `BuildConfig.API_BASE_URL`，并引入 OkHttp、OkHttp SSE、Coil、Lifecycle ViewModel Compose 与 Material Icons 依赖
- `AndroidManifest.xml`：声明网络权限，并允许 debug 场景访问本机 FastAPI 的明文 HTTP 地址

## 启动数据流

```text
Server 启动
    │
    ▼
server/main.py startup
    │
    ▼
ProductStore
    │ 1. CREATE DATABASE IF NOT EXISTS
    │ 2. CREATE TABLE IF NOT EXISTS products / sync_state
    │ 3. 扫描 ecommerce_agent_dataset/*/data/*.json
    │ 4. 构建 description 与 embedding_text
    │ 5. 按 product_id 幂等 upsert 到 MySQL
    ▼
MySQL products
    │ 商品价格、库存、上下架状态和主数据权威源
    │
    ├─▶ ChromaSync 后台任务
    │   │ 每 3 分钟读取 updated_at 增量
    │   │ upsert 上架有库存商品，删除下架商品
    │   ▼
    │  ChromaDB 最终一致语义索引
    ▼
FastAPI 开始服务请求
```

## 对话数据流

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
    │ Agent ReAct loop：LLM 接收历史+工具定义，最多执行 3 步工具调用
    │    - 无需工具：直接生成回复（反问/追问/寒暄）
    │    - 购物车操作：调用 cart 工具，更新/查看购物车或读取近期商品补充记忆
    │    - 需要检索：调用 retrieve_products，普通推荐使用 1 个 request，组合推荐使用多个 request
    │ 工具结果回填给 LLM 后生成最终回复
    │    - 解析 <R> 固定标签，按顺序发送文本块和商品块
    │    - 解析可选 <C> 标记，发送结构化对比块
    ▼
SSE event: status (可选)
    │ 工具调用时发送结构化状态，客户端作为临时 streamingStatus 展示
    ▼
SSE event: cart (可选)
    │ 自然语言购物车工具成功执行后发送，携带当前 CartSnapshot
    ▼
SSE event: block
    │ type=text/text_delta/product/compare
    │ 商品块由 FastAPI 同步记录到当前 conversation_id 的近期展示商品池
    │ 商品块携带 detail_url、landing_url、highlights、stock_status、unavailable_reason、group_label
    │ ChatApiService 解析为 BlockText / BlockProduct / BlockCompare
    ▼
SSE event: done
    │ ChatViewModel 结束流式状态
    ▼
ChatScreen 渲染消息气泡、商品卡片、图片和详情弹窗
```

## 商品详情数据流

```text
商品卡片 / 原生详情页
    │
    ▼
GET /api/products/{product_id}
    │ 不需要 conversation_id，公共读取商品展示数据
    ▼
ProductStore.get_product_detail()
    │ 从 MySQL products 最新快照读取标题、价格、库存、上下架、图片
    │ 从 raw_payload / description 派生规格、卖点、FAQ、评价摘要
    ▼
ProductDetail
    │ stock_status / unavailable_reason 决定详情页是否禁用加购
    │ landing_url 缺失时为 null，detail_url 指向服务端详情接口
```

详情读取不授予加购权限。用户从详情页加入购物车时仍必须调用 `/api/cart*`，后端继续使用当前 `conversation_id` 的近期展示商品池确认该商品曾在会话中展示过，并再次读取 MySQL 最新库存和上下架状态。

## 购物车 HTTP 数据流

```text
商品卡片按钮 / 购物车弹窗
    │
    ▼
FastAPI /api/cart*
    │ 使用 conversation_id 定位会话
    │ POST /api/cart/items 只接收 product_id + quantity
    │ 先用近期展示商品池确认 product_id 属于当前会话
    ▼
CartStore
    │ 查询 MySQL 最新商品状态
    │ 校验存在、上架、库存和数量
    │ 使用 MySQL 最新价格更新当前会话内存购物车
    ▼
CartSnapshot
    │ items + total_quantity + total_price + messages
    ▼
客户端刷新购物车摘要和明细
```

## 自然语言购物车数据流

```text
用户输入“把这些商品加入购物车”“删掉购物车里的耳机”
    │
    ▼
Agent ReAct loop
    │ 选择 add_to_cart / list_recent_products / remove_from_cart / update_cart_item / view_cart / clear_cart
    │ 批量加购时一次传入 product_ids[]；对话过长记忆模糊时才调用 list_recent_products
    ▼
server/tools/cart.py
    │ 使用 conversation_id 校验近期展示商品池或读取购物车快照
    │ add_to_cart 只接收 product_ids[]；删除/改数量仍可按购物车位置或关键词解析
    ▼
CartStore
    │ 执行确定性 add / remove / update / snapshot / clear
    │ add/update/snapshot 读取 MySQL 最新商品状态
    ▼
CartEvent
    │ /api/chat 转为 SSE event: cart
    ▼
BlockTextEvent
    │ 返回自然语言操作结果、反问或推荐理由
```

## 部署方式

开发环境采用「Docker MySQL + 本机 Python 后端」：

| 组件 | 运行方式 | 说明 |
|------|----------|------|
| MySQL | `docker compose up -d` | 官方 `mysql:8` 镜像，数据卷 `mysql_data`，映射到本机 `127.0.0.1:3306` |
| FastAPI 后端 | 本机 venv + uvicorn | ChromaDB、embedding 模型运行在宿主机；模型经 `HF_ENDPOINT`（默认 hf-mirror.com）下载 |
| Android 客户端 | Android Studio | 连接本机 `8000` 端口 API |

后端按 README 配置 `.env`、执行 `product_store.py` 与 `ingest.py` 后启动；`main.py` lifespan 也会在启动时幂等同步商品到 MySQL。
`chroma_sync.py` 可手动执行一次增量同步；FastAPI 启动后也会后台每 3 分钟自动同步。

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Python 3.10+ / FastAPI |
| MySQL（开发） | Docker Compose |
| Agent 编排 | ReAct 工具循环（OpenAI Function Calling 协议，最多 3 步） |
| 商品权威源 | MySQL + SQLAlchemy Core + PyMySQL |
| ChromaDB 同步 | FastAPI 后台任务 + MySQL `sync_state` 水位 |
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

## Android cart UI extension

The Android client consumes backend `cart` SSE events and direct `/api/cart*`
HTTP responses into `Cart` / `CartItem` models. `ChatViewModel` stores the
current cart snapshot in `ChatUiState.cart`, tracks direct cart mutations with
`isCartLoading`, and exposes add, increment, decrement, remove, and clear
operations for Compose.

`ChatScreen` renders a global cart icon in the app bar, a cart summary strip
above the input bar when the cart has items, an error, or backend cart messages,
and a `ModalBottomSheet` for cart management. The summary and sheet display
backend `messages`, and cart rows display `unavailableReason` / stock / active
state when the backend marks an item unavailable. Product cards and the product
detail dialog call `POST /api/cart/items` through `ChatViewModel.addToCart`; the
backend still resolves trusted title, price, and image data from the current
conversation's recently displayed product pool.

Opening the cart should call `ChatViewModel.refreshCart()` before showing the
cart sheet or cart detail view. That direct `GET /api/cart` refresh is the
client entry point for MySQL-authoritative price, stock, and availability
changes that happened after the last cart mutation or SSE cart event.

End-to-end cart validation lives in `eval/run_cart_e2e.py`. It exercises empty
cart reads, invalid add rejection, product recommendation, HTTP add, quantity
update, deletion, clearing, conversation isolation, and natural-language cart
operations through `/api/chat` SSE when the LLM route is available.

## Android client block-message update

- `client-android/data/model/Message.kt` now stores ordered `MessageBlock.TextBlock / ProductBlock / CompareBlock` entries instead of `content + products + compareTables`.
- `client-android/data/model/Product.kt` now also models `detailUrl`, `landingUrl`, `highlights`, `stockStatus`, `unavailableReason`, `groupLabel`, and `ProductDetail`.
- `client-android/data/api/ChatApiService.kt` parses backend `block` SSE events into typed client events and fetches `GET /api/products/{product_id}` for detail sheets.
- `client-android/viewmodel/ChatViewModel.kt` keeps `streamingStatus` separate from the message stream, merges `text_delta` into existing text blocks, refreshes cart snapshots on demand, and loads product details before opening the detail sheet.
- `client-android/ui/chat/ChatScreen.kt` renders messages in block order, shows centered vertical product cards, converts compare payloads into vertically readable sections, and opens the cart only after `refreshCart()` is triggered from the top-bar cart button or `CartSummaryBar`.
