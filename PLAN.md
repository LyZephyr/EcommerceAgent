# 项目实施计划

## 一、当前系统状态

### 架构

系统已从固定流水线（意图解析 -> RAG 检索 -> LLM 生成）重构为**单跳工具调用 Agent**：

- LLM 接收对话历史 + 工具定义，自主决定是否需要检索
- 需要商品推荐时：LLM 通过 Function Calling 调用 `retrieve_products` 工具，填充结构化检索参数（改写 query、类目、价格区间、正向关键词、排除条件），工具内部调用 `retriever.retrieve()` 执行 RAG 检索，检索结果注入上下文后 LLM 流式生成推荐回复
- 无需检索时：LLM 直接回复（反问澄清、追问已展示商品细节、寒暄等）
- 多轮对话由 `conversation.py` 管理，内存存储，滑动窗口保留最近 10 轮

### 已完成功能


| 模块                                      | 状态  |
| --------------------------------------- | --- |
| Embedding 重构（bge-base-zh-v1.5 + 紧凑文本策略） | 已完成 |
| RAG 检索 + metadata filter + 加权重排         | 已完成 |
| Agent 架构（单跳工具调用替代固定流水线）                 | 已完成 |
| LLM 筛选商品 + 卡片一致性（`<R>` 标记）              | 已完成 |
| 多轮对话上下文管理                               | 已完成 |
| 反选/排除约束（exclude_terms + exclude_brands） | 已完成 |
| SSE 流式传输 + Android 客户端聊天界面              | 已完成 |
| 离线评估体系（250 条 ground truth + 指标计算）       | 已完成 |


### 后端文件结构

```
server/
├── config.py                  # 环境变量与全局配置
├── embedding.py               # ChromaDB embedding function
├── ingest.py                  # 商品数据导入
├── retriever.py               # RAG 检索 + 重排
├── conversation.py            # 多轮对话历史管理
├── agent.py                   # Agent 编排（单跳工具调用 + 流式生成）
├── tools/
│   ├── __init__.py            # 工具注册表
│   └── retrieve_products.py   # 商品检索工具定义 + 执行
├── main.py                    # FastAPI 入口
└── schemas.py                 # Pydantic 数据模型
```

---

## 二、下一阶段任务

### 子任务 1：Agent 行为验证与调优

**目标**：验证 Agent 在各类场景下的路由决策和检索质量。

**方案**：

1. 用 curl 测试以下场景，确认 Agent 行为符合预期：
  - 正常推荐查询（应触发 `retrieve_products` 工具调用）
  - 模糊需求（如"推荐手机"，应直接反问而非检索）
  - 追问已展示商品（如"第一个的成分是什么"，应直接回复而非重新检索）
  - 多轮追加条件（如"推荐跑鞋" -> "要轻量的" -> "500以内"，应逐轮检索并收敛结果）
  - 否定语义（如"不要含酒精的"，应正确填充 exclude_terms）
2. 跑 `eval/run_retrieval_eval.py` 对比工具调用方式与原 intent 方式的检索指标，确认无回退
3. 根据测试结果调优 system prompt 和工具 description 中的规则表述

**验收标准**：各场景路由决策正确，检索指标与重构前持平或提升。

### 子任务 2：后端 Agent / RAG 能力扩展

**目标**：在保持单跳工具调用架构的前提下，支持多商品对比决策和跨类目场景化组合推荐。

**方案**：

1. 调整 Agent system prompt：
  - 对比决策：当用户要求对比两个或多个商品时，优先基于对话历史中的已展示商品回答；如果用户引入了新商品或新筛选条件，再调用 `retrieve_products` 检索。
  - 对比输出：按价格、核心卖点、适合人群、评价反馈和注意事项等维度组织内容，由 LLM 整合商品资料后输出，不直接堆叠原始长字段。
  - 场景化组合推荐：当用户描述一个场景需要多类商品时，将场景拆解为多个子需求，但仍只发起一次 `retrieve_products` 工具调用。
2. 重构 `retrieve_products` 工具参数 schema：
  - 将单个 `search_query` 扩展为 `requests` 数组，每个元素表示一个独立检索子需求。
  - 每个 request 包含 `label`、`search_query`、`category`、`min_price`、`max_price`、`must_have_terms`、`exclude_terms`、`exclude_brands`。
  - 示例：
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
3. 修改 `tools/retrieve_products.py` 执行逻辑：
  - `execute()` 遍历 `requests`，为每个 request 构造 intent。
  - 每个 request 独立调用现有 `retriever.retrieve(search_query, TOP_K, intent)`，保留各自的 category / 价格 / 正向关键词 / 排除条件 / rerank 逻辑。
  - 工具一次性返回多组检索结果，保留 `label` 供 LLM 理解来源，但不要求下游客户端按 label 分组展示。
4. 修改 `agent.py` 对工具结果的处理：
  - 支持格式化多组检索结果注入 Phase 2 上下文。
  - 生成 `candidates_by_id` 时将多组商品拍平成一个候选池，用于解析 `<R>` 推荐标记并发送商品卡片。
  - LLM 回复给用户时可以按场景逻辑组织推荐说明，但商品卡片仍作为本轮推荐商品的扁平列表发送，不按子需求分组。
5. 对比场景的后端输出：
  - 文本回复仍通过 `token` 事件流式返回。
  - 如需要结构化对比表，SSE 新增 `event: compare`，携带维度、商品和对应值；该事件仅用于对比决策，不用于场景化组合推荐分组。
6. 更新离线评估：
  - 保持现有单 query 检索评估可运行，评估脚本可将单条 query 包装成单元素 `requests`。
  - 增加少量场景化组合推荐 case，验证一次工具调用下多个 request 均能至少召回 1 个相关商品。

**验收标准**：

1. 演示 "A和B哪个更好？" 场景，后端能基于已有商品或新检索结果生成结构化对比说明。
2. 演示 "去三亚度假，帮我搭配从防晒到穿搭的方案" 场景，LLM 一次调用 `retrieve_products`，工具内部完成 2+ 个 request 的检索与 rerank。
3. 场景化组合推荐的回复自然说明整体方案，商品卡片以普通扁平列表返回，不按子需求分组。

### 子任务 3：客户端展示能力扩展

**目标**：让 Android 客户端能消费后端新增的对比事件，并继续以现有商品卡片列表承载推荐结果。

**方案**：

1. 扩展 Android SSE 事件解析：
  - 保留现有 `status`、`product`、`token`、`done`、`error` 事件处理。
  - 新增 `compare` 事件模型，用于承载后端返回的结构化对比表数据。
2. 新增对比表格 UI：
  - 在消息流中渲染商品对比表，展示价格、核心卖点、适合人群、评价反馈和注意事项等维度。
  - 表格内容来自后端 `compare` 事件，用户仍能在同一条消息中看到 LLM 的文字推荐理由。
3. 保持组合推荐的商品卡片展示方式：
  - 场景化组合推荐不做子需求分组 UI。
  - 所有 `product` 事件仍追加到当前 assistant 消息的商品列表中，沿用现有横向商品卡片组件。
4. 客户端体验验证：
  - 验证普通推荐、多轮追问、对比决策和场景化组合推荐都能正常流式展示。
  - 确认新增对比表不会影响现有商品卡片、详情弹窗和取消生成逻辑。

**验收标准**：

1. 对比决策场景：客户端展示对比表格 + LLM 推荐理由。
2. 场景化组合推荐场景：客户端展示自然语言方案 + 普通商品卡片列表，不出现分组卡片 UI。

---

## 三、加分项任务

以下任务在核心功能稳定后按需推进，均基于 Agent 工具调用架构扩展。

### 购物车闭环（加分项 4.1）

新增 `tools/cart.py`，定义购物车 CRUD 工具：


| 工具                 | 功能        |
| ------------------ | --------- |
| `add_to_cart`      | 将商品加入购物车  |
| `remove_from_cart` | 从购物车删除商品  |
| `update_cart_item` | 修改购物车商品数量 |
| `view_cart`        | 查看购物车内容   |


- 后端用内存或 SQLite 存储购物车数据
- Agent 根据用户自然语言指令自动选择对应的购物车工具
- SSE 新增 `event: cart` 事件，客户端展示购物车状态

### 拍照找货 / 多模态（加分项 4.2）

新增 `tools/image_search.py`，定义图片搜索工具：

- Android 端接入相机拍照，将图片 base64 或 URL 上传
- `POST /api/chat` 请求体扩展，支持 `image` 字段
- 工具内部调用 VLM 提取图片特征描述，描述文本送入 `retriever.retrieve()` 检索相似商品
- Agent 在收到图片输入时自动调用此工具

### 工程优化（加分项 4.4）

- 语义缓存：对高频相似 query 缓存工具调用结果，减少 LLM + 检索开销
- 首屏加速：Phase 1 决策与 embedding 计算并行，压缩 system prompt
- 客户端体验：骨架屏加载、`status` 事件驱动的检索中状态展示、商品卡片富交互打磨

---

## 四、文档与演示

- 完善 README（环境搭建、运行步骤、架构说明）
- 技术文档（Agent 架构设计、RAG 链路、Prompt 工程、检索优化过程和指标对比）
- 准备 3-5 分钟 Demo 演示脚本，覆盖：单轮推荐、多轮追问、反问澄清、否定排除、（可选）对比决策、（可选）购物车操作
