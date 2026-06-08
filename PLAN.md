# 项目实施计划

## 一、当前已落地实现（MVP）

端到端链路已跑通：用户输入 → 后端 RAG 检索 → LLM 生成 → SSE 流式返回 → Android 商品卡片展示。

### 后端

| 模块 | 实现 | 现状 |
|------|------|------|
| `ingest.py` | 扫描 4 类目 100 条商品 JSON，拼接全字段文本为 document，调用 embedding 写入 ChromaDB | 已完成 |
| `embedding.py` | 使用 `shibing624/text2vec-base-chinese` 本地模型 | 已完成，存在严重截断问题（见下） |
| `retriever.py` | query embedding → ChromaDB 相似度搜索 → 手工同义词扩展 + 词法/价格 rerank → Top-K | 已完成，检索质量不足 |
| `generator.py` | System Prompt + 检索上下文 → Doubao API stream 生成 | 已完成 |
| `main.py` | FastAPI SSE 端点 `POST /api/chat`，先发 product 事件再发 token 流 | 已完成 |
| `eval/` | 117 条 ground truth + 离线评估脚本，计算 Recall/MRR/HitRate/Precision | 已完成 |

### Android 客户端

| 模块 | 实现 | 现状 |
|------|------|------|
| `ChatApiService` | OkHttp SSE 客户端，解析 product/token/done 事件为 Flow | 已完成 |
| `ChatViewModel` | 管理消息列表、流式响应拼接、取消逻辑 | 已完成 |
| `ChatScreen` | Compose 聊天界面，消息气泡 + 商品横向卡片 + 详情弹窗 | 已完成 |

### 已知问题

**1) Embedding 截断导致检索质量差**

`text2vec-base-chinese` 的 `max_seq_length` 仅 128 tokens，而 100 条商品文档的 token 长度为 801~3159（平均 2016）。模型只能看到每篇文档的前 ~10%（商品ID + 标题 + 品牌 + 类目 + 价格 + 卖点开头一句），FAQ、用户评价、SKU 属性等全部被截断丢弃，导致所有文档的向量高度相似、区分度极低。

当前评估指标（Top-5）：

| 指标 | 值 | 说明 |
|------|------|------|
| Recall@5 | 0.389 | 不到 40% 的相关商品被召回 |
| Hit Rate@5 | 0.632 | 近 37% 的查询一个相关商品都没命中 |
| 零召回查询 | 43/117 | 超过三分之一完全偏离 |

按查询类型看，场景化模糊查询（functional_scene）是重灾区：recall 仅 0.273，56 条中 26 条零召回。

**2) 商品卡片与 LLM 回复不一致**

当前流程是检索结果直接全部作为 product 事件发送，LLM 拿到同样的结果后可能判断不相关而回复"未找到匹配商品"——客户端展示了 5 张无关卡片却收到否定回复。

**3) 手工同义词扩展覆盖面极窄**

`_expand_query` 仅覆盖 8 个词的静态映射，无法应对开放式查询。

**4) 无类目过滤**

纯向量检索无结构化过滤，搜"上衣"可能返回美妆/食品商品。

---

## 二、下一阶段任务

按实现顺序组织，前一个子任务是后一个的基础。

### 子任务 1：Embedding 与 Chunking 重构

**目标**：解决 128 token 截断问题，让商品的完整语义进入向量空间。

**方案**：

1. 换用 `BAAI/bge-base-zh-v1.5`（512 token 窗口、768 维、C-MTEB 中文检索榜领先），修改 `.env` 中的 `EMBEDDING_MODEL`
2. 重构 `ingest.py` 的 chunking 策略：为每个商品生成 2-3 个语义 chunk（核心卖点 / FAQ / 用户评价），每个 chunk 都带 "标题+品牌+类目" 前缀以保证独立可检索
3. ChromaDB 中同一 product_id 对应多条向量记录，检索时按 product_id 去重取最高语义分
4. 如果 bge 模型无法下载，降级方案：保留 text2vec，但将嵌入文本精简为 128 token 内的检索摘要（标题+品牌+类目+卖点前两句+场景标签），完整文档仅存入 documents 字段供 LLM 阅读

**验收标准**：重新跑 `eval/run_retrieval_eval.py`，各项指标较 MVP 基线有明显提升。

### 子任务 2：LLM 意图解析 + 查询改写

**目标**：在检索之前用 LLM 理解用户意图，将口语化查询转换为高质量检索 query，并提取结构化筛选条件。

**方案**：

1. 新建 `server/intent.py`，定义意图解析的 prompt 和输出 schema
2. LLM 一次调用输出结构化 JSON：
   - `intent_type`：recommend / filter / compare / exclude / combo / clarify
   - `rewritten_query`：改写后的检索用语句（补充品类词、属性词）
   - `category_hint`：推断的商品类目
   - `price_range`：{min, max}
   - `brand_filter`：{include, exclude}
   - `exclude_terms`：排除条件列表
   - `needs_clarification` + `clarification_question`：信息不足时的反问
3. 改造 `retriever.py`：接收意图结构体，用 `rewritten_query` 做向量检索，用 `category_hint`/`price_range`/`brand_filter` 构建 ChromaDB `where` filter
4. 删除手工 `_expand_query` 同义词表和 `_price_target` 正则——这些能力被 LLM 意图解析完全替代

**验收标准**：各项指标在子任务 1 基础上继续提升，functional_scene 类型零召回数明显减少。

### 子任务 3：LLM 筛选商品 + 卡片一致性

**目标**：商品卡片只展示 LLM 认为真正相关的商品，消除卡片与回复文本的矛盾。

**方案**：

1. 改造 `main.py` 的 SSE 流程：检索返回候选集 → LLM 在生成回复时同时输出推荐的 product_id 列表 → 后端解析后只发送选中商品的 product 事件
2. 调整 `generator.py` 的 prompt：要求 LLM 在回复开头以 `[PRODUCTS: p_xxx_001, p_xxx_002]` 格式标注推荐商品，后端解析该行后剥离，不发给客户端
3. SSE 事件顺序调整为：先完成 LLM 流式输出（token 事件），解析出推荐商品 ID 后再发 product 事件；或者先发一个解析行，再发 token 流
4. 如果 LLM 判断无匹配商品，不发任何 product 事件，客户端自然不展示卡片

**验收标准**：curl 测试 10 条典型查询，卡片展示与 LLM 回复内容一致。

### 子任务 4：多轮对话与追问细化

**目标**：支持上下文连续对话，用户可以在多轮中逐步追加条件，Agent 能基于累积意图检索。

**方案**：

1. 后端用内存 dict 维护 `conversation_id → list[{role, content}]` 的历史映射
2. 子任务 2 的意图解析 prompt 注入对话历史，LLM 将新条件与已有意图合并（如 "帮我推荐跑鞋" → "要轻量的" → 合并为 {keywords: [跑鞋, 轻量]}）
3. 当 LLM 判断 `needs_clarification=true` 时，跳过检索直接返回反问文本，引导用户细化需求
4. 滑动窗口：只保留最近 10 轮对话，避免超出模型上下文窗口

**验收标准**：演示 "推荐跑鞋 → 要轻量的 → 预算500以内" 三轮追问场景，检索结果逐步收敛。

### 子任务 5：反选/排除约束

**目标**：正确处理"不要含酒精的"、"除了耐克还有什么"等否定语义。

**方案**：

1. 意图解析（子任务 2）已输出 `exclude_terms` 和 `brand_filter.exclude`
2. 品牌排除：ChromaDB `where` filter 用 `$nin` 操作符
3. 成分/功效等非结构化排除：由 LLM 在筛选阶段（子任务 3）读取 document 全文后判断，排除包含被否定属性的商品
4. prompt 中明确指导 LLM 识别否定语义，不要将"不要X"理解为"要X"

**验收标准**：否定语义查询中，LLM 回复不推荐被排除的商品。

### 子任务 6：对比决策

**目标**：用户要求对比时，Agent 提取关键维度生成结构化对比。

**方案**：

1. 意图解析识别 `intent_type: "compare"`，提取要对比的商品名/品牌
2. 检索每个商品的完整信息，让 LLM 按维度（价格、核心卖点、适合人群、用户评价摘要）输出结构化对比
3. SSE 协议新增 `event: compare` 事件类型，携带对比维度和各商品对应值
4. Android 客户端新增对比表格组件，渲染在消息流中

**验收标准**：演示 "A和B哪个更好？" 场景，客户端展示对比表格 + LLM 给出推荐理由。

### 子任务 7：场景化组合推荐

**目标**：支持"去三亚度假，帮我搭配从防晒到穿搭的方案"等跨类目组合推荐。

**方案**：

1. 意图解析识别 `intent_type: "combo"`，LLM 将场景拆解为多个子需求（防晒霜 + 墨镜 + 短袖 + 短裤 + ...）
2. 对每个子需求分别检索，合并候选集
3. LLM 组合编排输出按场景逻辑组织的推荐方案
4. product 事件按子需求分组发送，客户端可在每个推荐段落下方展示对应商品卡片

**验收标准**：演示一个跨 2+ 类目的场景组合推荐，每个子需求至少命中 1 个相关商品。

---

## 三、后续任务

以下任务在上述核心功能稳定后按需推进。

### 购物车闭环（加分项 4.1）

- 后端新增购物车 CRUD API（内存或 SQLite）
- LLM 通过 Function Calling 调用购物车操作
- 客户端展示购物车浮层，支持 "把这个加到购物车"、"删掉第二个" 等自然语言指令

### 拍照找货 / 多模态（加分项 4.2）

- Android 端接入相机拍照
- 后端调用 VLM 提取图片特征描述
- 描述文本送入 RAG 检索相似商品

### 工程优化（加分项 4.4）

- 热门查询语义缓存（减少重复 LLM 调用）
- 首屏极速响应（意图解析与 embedding 并行、prompt 压缩）
- 客户端骨架屏、流式动效、商品卡片富交互打磨

### 文档与演示

- 完善 README（环境搭建、运行步骤、架构说明）
- 技术文档（RAG 链路设计、Prompt 工程、检索优化过程和指标对比）
- 准备 3-5 分钟 Demo 演示脚本
