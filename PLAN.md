# 项目实施计划

## 一、最小闭环（MVP）

**目标**：跑通「用户输入 → 后端 RAG 检索 → LLM 生成 → SSE 流式返回 → Android 端商品卡片展示」完整链路。

### Phase 1：后端数据层

| 步骤 | 内容 | 产出 |
|------|------|------|
| 1.1 数据导入 | 扫描 `ecommerce_agent_dataset/` 下 4 个类目共 100 条 JSON，解析为统一结构 | `ingest.py` 中的 `load_products()` |
| 1.2 文本构造 | 将每条商品的 title、category、marketing_description、FAQ、user_reviews 拼接为一段可检索文本 | `ingest.py` 中的 `build_document()` |
| 1.3 向量化入库 | 调用 Embedding 模型生成向量，连同元数据（product_id, title, price, category, image_path）写入 ChromaDB | `ingest.py` 中的 `ingest()` |

**Embedding 策略**：优先使用 `sentence-transformers/text2vec-base-chinese` 本地模型，无需额外 API Key，768 维向量，中文语义效果好。如后续需要更高质量可切换为 Doubao Embedding API。

**Chunking 策略**：每条商品作为一个独立 document（不再切分），原因是单条商品文本量约 500-1500 字，在 embedding 模型的窗口范围内，且检索粒度就是"商品"级别。

### Phase 2：后端 RAG 链路

| 步骤 | 内容 | 产出 |
|------|------|------|
| 2.1 检索模块 | 用户 query → embedding → ChromaDB 相似度搜索 Top-K → 返回商品元数据 + 原文 | `retriever.py` |
| 2.2 Prompt 构造 | System Prompt 定义角色和输出格式；User Prompt 拼接检索上下文 + 用户问题 | `generator.py` |
| 2.3 流式生成 | 调用 Doubao API（OpenAI 兼容接口），stream=True，逐 token yield | `generator.py` |
| 2.4 SSE 端点 | FastAPI POST `/api/chat`，接收消息后串联 retriever → generator，通过 SSE 返回 | `main.py` |

**Prompt 设计要点**：
- System Prompt 明确要求"只基于提供的商品信息回答，不编造不存在的商品或属性"
- 商品卡片数据由检索结果直接通过 `product` SSE 事件发送，不依赖 LLM 生成结构化标记
- 控制回复风格为友好专业的导购语气

**SSE 协议设计**：
```
event: token
data: {"content": "这款"}

event: token
data: {"content": "手机"}

event: product
data: {"product_id": "p_digital_001", "title": "...", "price": 8999.0, "image_url": "..."}

event: done
data: {}
```

### Phase 3：Android 客户端

| 步骤 | 内容 | 产出 |
|------|------|------|
| 3.1 数据层 | 定义 `Message`、`Product` 数据类；OkHttp SSE 客户端封装 | `data/` 目录 |
| 3.2 ViewModel | `ChatViewModel` 管理消息列表状态，处理 SSE 事件流，逐字追加 AI 回复 | `viewmodel/` |
| 3.3 对话 UI | `ChatScreen`（消息列表 + 输入框）、`MessageBubble`（用户/AI 气泡）、`ProductCard`（商品卡片） | `ui/chat/` |
| 3.4 联调 | 连接后端 SSE 接口，完整对话流程跑通 | 可运行 Demo |

**商品卡片**：展示商品名、价格、类目标签、商品主图。点击卡片在 MVP 阶段弹出简单详情弹窗。

---

## 二、后续功能演进

按优先级排列，每个方向独立可拆分为单独的开发会话。

### P0 — 多轮对话（加分项 4.3 ⭐）

- 后端维护 conversation_id → 历史消息列表的映射
- 每次请求将最近 N 轮历史拼入 prompt
- 支持追问："再便宜点的？"、"有其他颜色吗？"

### P1 — 购物车闭环（加分项 4.1 ⭐⭐）

- 后端新增购物车 CRUD API（内存或 SQLite 存储）
- LLM 通过 Function Calling / Tool Use 调用购物车操作
- 客户端展示购物车状态浮层
- 支持"把这个加到购物车"、"删掉第二个"等自然语言指令

### P2 — 否定语义 & 排除约束（加分项 4.3 ⭐⭐）

- Prompt 增强：指导 LLM 识别"不要含酒精的"、"除了耐克"等否定条件
- 检索后过滤：LLM 生成结构化过滤条件，对检索结果做二次筛选
- 需要在 metadata 中增加 brand、成分等可过滤字段

### P3 — 商品对比（加分项 4.3 ⭐⭐⭐）

- 用户要求对比时，LLM 提取关键维度（价格、性能、口碑等）
- 后端并行检索多商品信息
- 客户端渲染对比表格组件

### P4 — 拍照找货 / 多模态（加分项 4.2 ⭐⭐⭐）

- Android 端接入相机拍照
- 后端调用 VLM（视觉语言模型）提取图片特征描述
- 将描述文本送入 RAG 检索相似商品

### P5 — 工程优化（加分项 4.4）

- 热门查询缓存（语义相似度去重 + Redis/内存缓存）
- 首屏极速响应（Prompt 压缩、检索与生成流水线并行）
- 客户端骨架屏、流式动效打磨

---

## 三、关键技术难点及应对策略

### 难点 1：进一步幻觉校验

**问题**：LLM 可能编造不存在的商品、虚假价格、虚构优惠信息。

**应对**：
- 对 LLM 回复做后处理，校验提及的 product_id 是否存在于检索结果中

### 难点 2：检索质量

**问题**：纯向量相似度检索可能不够精准，特别是涉及价格范围、品牌等结构化条件时。

**应对**：
- 后续增加混合检索：LLM 先提取结构化条件（价格区间、类目、品牌），在 metadata 上做过滤，再在过滤后的子集上做语义排序
- ChromaDB 支持 metadata filter，可直接利用

### 难点 3：多轮对话上下文管理

**问题**：历史消息不断增长，会超出模型上下文窗口；且需要正确理解指代关系。

**应对**：
- 滑动窗口：只保留最近 5-10 轮对话
- 可选：对历史对话做摘要压缩
- 指代消解放在 Prompt 中引导 LLM 处理

### 难点 4：Android 流式文本渲染性能

**问题**：高频 SSE 事件可能导致 Compose 重组过于频繁，造成 UI 卡顿。

**应对**：
- ViewModel 中对 token 事件做批量合并（如每 50ms 合并一次），减少 State 更新频率
- 消息文本用 `StringBuilder` 拼接，只在合并点触发 State 更新

---

## 四、开发会话规划

| 会话 | 目标 | 预计产出 |
|------|------|----------|
| **会话 1**（当前） | 搭建项目骨架，编写计划文档 | 目录结构、PLAN.md、architecture.md、api_index.md |
| **会话 2** | 实现后端数据导入 + RAG 检索 | ingest.py、retriever.py 完整实现，可脚本验证检索效果 |
| **会话 3** | 实现后端 LLM 生成 + SSE API | generator.py、main.py 完整实现，可 curl 验证流式输出 |
| **会话 4** | 实现 Android 客户端 | 聊天 UI + SSE 客户端 + 商品卡片，端到端联调 |
| **会话 5** | 多轮对话 + 购物车 | 加分项核心功能 |
| **会话 6** | 打磨 + 文档 + 演示准备 | UI 美化、README、技术文档完善 |
