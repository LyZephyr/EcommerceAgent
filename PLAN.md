# 电商导购 Agent 体验升级计划

## 当前已实现能力

本项目已完成基于 RAG 的电商导购 MVP：后端为 Python/FastAPI，客户端为 Android Kotlin/Compose。核心链路已经跑通：

- `POST /api/chat` 通过 SSE 返回 `status`、`product`、`compare`、`cart`、`token`、`error`、`done` 事件。
- Agent 可调用 `retrieve_products` 检索商品，检索结果由 MySQL 补全价格、库存、图片等权威数据。
- Android 客户端已能消费 SSE，展示聊天消息、横向商品卡片、对比表、商品弹窗和购物车。
- 后端已通过 `<R>` 推荐标记约束商品卡片输出，通过 `<C>` 标记输出结构化对比数据。

这些能力证明端到端链路可用，但当前交互仍偏 MVP：AI 长文本、商品卡片、对比表和等待状态没有被组织成适合移动端的导购体验。

## 当前问题

1. AI 回复信息密度过高。长段文本、Markdown 标题、编号和注意事项直接铺满屏幕，用户需要长时间滚动才能看到商品。
2. Markdown 没有完整渲染。`###`、`**`、表格竖线等语法会直接显示。
3. 商品卡片没有真正无缝嵌入对话流。目前卡片统一挂在整条回复之后，并以横向列表展示，容易被长文本和对比表压到后面。
4. 商品卡片不支持真正的落地页跳转。当前点击商品只打开弹窗，不是独立详情页或外部商品页。
5. 对比表以横向表格展示，手机端列宽受限，需要左右滑动，文字容易裁切。
6. 首次等待时间较长，状态事件粒度不足；最终 `token` 不是类似 ChatGPT、豆包的真逐字流式，而是后端解析完成后一次性发送可见文本。

## 任务目标

本轮升级目标是把回复从“长文本 + 横向卡片列表”改成“结构化块式对话流”，并实现真 streaming：

```text
整体建议：优先选常温奶，日常早餐和办公室补充都更方便。

[商品卡片 A，居中独立展示，可点击进入详情页]
A 的推荐理由逐字流式输出...

[商品卡片 B，居中独立展示，可点击进入详情页]
B 的推荐理由逐字流式输出...
```

必须满足：

- 商品卡片与文本按顺序交替出现。
- 每个商品卡片独立居中显示，不再把多个商品挤在一横排。
- 文本保持类似 ChatGPT、豆包的逐字或短片段流式输出。
- 商品卡片支持跳转落地页；没有真实外部链接时，先实现 App 内原生商品详情页。
- 等待态分阶段展示，用户在推荐文本到达前也能看到明确进度。
- 推荐正文移动端友好，禁止 Markdown 标题、Markdown 表格和长篇编号说明。

## 总体方案

核心改造方向是：服务端输出有顺序的结构化块；客户端按块渲染文本、商品卡片和对比。状态不作为消息块进入聊天流，而是作为当前 streaming 状态单独维护，完成或失败后清空。

`POST /api/chat` 只提供新版块式 SSE 协议：

```json
{
  "message": "推荐一些牛奶",
  "conversation_id": "..."
}
```

- 服务端发送 `block`、`status`、`cart`、`error`、`done`。
- 不保留旧 `product`、`compare`、`token` SSE 事件。
- 在整个计划完成前，不要求系统持续兼容旧客户端或保持每个阶段都端到端可用。

新版推荐使用 `block` SSE 事件：

```json
{
  "type": "text",
  "message_id": "assistant-message-id",
  "block_id": "block-1",
  "content": "整体建议：优先选常温奶，早餐和办公室补充都方便。"
}
```

```json
{
  "type": "text_delta",
  "message_id": "assistant-message-id",
  "block_id": "block-1",
  "content": "整"
}
```

```json
{
  "type": "product",
  "message_id": "assistant-message-id",
  "block_id": "block-2",
  "product": {
    "product_id": "...",
    "title": "...",
    "brand": "...",
    "category": "...",
    "sub_category": "...",
    "price": 85.0,
    "image_url": "...",
    "stock": 12,
    "detail_url": "/api/products/...",
    "landing_url": null,
    "highlights": ["常温保存", "适合早餐"],
    "stock_status": "in_stock"
  }
}
```

ID 生成规则：

- `message_id`：服务端在 `run_turn()` 开始时生成一次，建议使用 `asst-<uuid>`；本轮所有 `block` 事件共用同一个 `message_id`。
- `block_id`：服务端在每个可见块创建时按顺序分配，建议使用 `blk-1`、`blk-2`、`blk-3`；同一个文本块的完整 `text` 或所有 `text_delta` 共享同一个 `block_id`。
- 推荐链路的典型块顺序为：`INTRO text`、`product A`、`reason A text`、`product B`、`reason B text`、`OUTRO text`。

状态事件仍可使用 `block` 包装，也可继续使用 `status` 事件；但客户端不把状态写入 `Message.blocks`：

```json
{
  "type": "status",
  "phase": "retrieving",
  "message": "正在检索商品...",
  "step": 1,
  "total_steps": 4
}
```

## 推荐标记协议

为降低真 streaming 的解析复杂度，不使用 `<R>{JSON}</R>`。推荐场景改为固定标记协议，服务端只需识别少量固定标签：

```xml
<R>
<INTRO>整体建议：优先选择常温纯牛奶，早餐、办公室和宿舍都方便。</INTRO>
<ITEM id="p1" group="纯牛奶">
<REASON>这款容量和价格更均衡，适合家庭早餐和日常囤货。</REASON>
</ITEM>
<ITEM id="p2" group="有机牛奶">
<REASON>这款更适合看重奶源认证的家庭，老人小孩饮用更安心。</REASON>
</ITEM>
<OUTRO>如果你更看重性价比，优先选第一款；更看重有机认证，选第二款。</OUTRO>
</R>
```

跨类目组合推荐示例：

```xml
<R>
<INTRO>整体建议：海边出行建议同时准备防晒和轻薄外套，先保证防晒，再兼顾透气。</INTRO>
<ITEM id="sunscreen-1" group="防晒护肤">
<REASON>这款适合长时间户外使用，防晒强度和清爽度更均衡。</REASON>
</ITEM>
<ITEM id="jacket-1" group="度假穿搭">
<REASON>这款轻薄好收纳，适合早晚温差和空调环境。</REASON>
</ITEM>
<OUTRO>如果预算有限，优先保证防晒，再补充外套。</OUTRO>
</R>
```

解析与校验规则：

- 推荐场景中，`<R>...</R>` 之外不允许有非空可见文本，避免 LLM 两边重复写。
- `id` 必须来自本轮工具候选。
- `<ITEM>` 属性值只允许字母、数字、汉字、`-`、`_`、空格和常见 ASCII 标点中的冒号/斜杠；禁止 `"`、`'`、`<`、`>`、`\`，避免流式属性解析需要处理复杂转义。
- `group` 可选，用于跨类目组合推荐和客户端分组展示；当本轮 `retrieve_products` 包含多个非空 `requests[].label` 时，`group` 必须从这些 label 中选择，服务端用 `label -> product_id` 映射校验；单 request 或无 label 时，`group` 必须省略。
- `<INTRO>`、`<REASON>`、`<OUTRO>` 是用户可见文本。
- `<INTRO>` 必须位于所有 `<ITEM>` 之前。
- 每个 `<ITEM>` 内必须且只能有一个 `<REASON>`。
- `<ITEM>` 不允许嵌套 `<ITEM>`、`<INTRO>`、`<OUTRO>`。
- `<OUTRO>` 可选，但如果存在，必须位于所有 `<ITEM>` 之后。
- 违反标签顺序、嵌套或数量约束时触发可恢复错误，由 LLM 重试。
- 推荐正文长度按字段限制，而不是整段总长限制：
  - `INTRO` 建议不超过 40 个中文字符。
  - 每个 `REASON` 建议不超过 45 个中文字符。
  - `OUTRO` 建议不超过 40 个中文字符，可为空。
- `_MOBILE_VISIBLE_REPLY_MAX_CHARS` 继续用于非推荐纯文本场景，如澄清、寒暄、购物车操作回复；推荐场景改用 `INTRO`、`REASON`、`OUTRO` 字段级长度限制。
- 仍禁止 Markdown 标题、Markdown 表格、粗体标记和长编号列表。
- `<R>` 和 `<C>` 仍不能同时出现。
- 普通澄清、寒暄、购物车操作回复不输出 `<R>`，直接输出短文本。
- 对比仍使用 `<C>` 结构化标记。本轮阶段 3 不改造 `<C>` 为固定标签：对比场景在 streaming completion 下缓冲到 `</C>` 闭合后，一次性解析并发送完整 compare block；推荐链路不受该缓冲影响。后续可单独规划 `<COMPARE>` 固定标签协议。

历史落库规则：

- conversation 中不保存隐藏标签原文。
- 推荐完成后，将已发送给客户端的可见内容拼成一条 assistant 历史，格式为：

```text
整体建议：...
[商品] 商品标题A（product_id=p1）：A 的推荐理由
[商品] 商品标题B（product_id=p2）：B 的推荐理由
总结：...
```

- 这样下一轮用户追问“第一款怎么样”时，LLM 能看到商品标题、ID 和推荐理由；必要时仍可调用 `list_recent_products` 获取最新商品快照。
- 如果用户取消或 SSE 中断，服务端将已经发送的可见文本片段和商品 ID 落库，并追加 `[interrupted]`，避免下一轮上下文完全丢失。

## 阶段划分

### 阶段 1：服务端块顺序协议与解析器改造

目标：先完成块顺序协议，不做伪流式。服务端可以按“整体建议 -> 商品 -> 理由 -> 商品 -> 理由”输出块，但每个文本块可以一次性发送 `text`。

服务端任务：

- `POST /api/chat` 固定发送新版 `block` 事件和必要的 `status`、`cart`、`error`、`done`。
- 删除旧 `product`、`compare`、`token` SSE 推荐事件和相关兼容分支。
- 收紧 `SYSTEM_PROMPT`：
  - 移动端推荐回复使用 `<R>/<INTRO>/<ITEM>/<REASON>/<OUTRO>` 标记协议。
  - 推荐场景 `<R>` 外不允许有非空正文。
  - 禁止 Markdown 标题、Markdown 表格、`**`、表格竖线和长编号列表。
  - 商品价格、库存、规格等卡片字段不要在正文重复铺开。
  - 加入 few-shot 示例，至少覆盖普通同类推荐、跨类目组合推荐、反问澄清和现有 `<C>` 对比输出。
- 调整 `tools/retrieve_products.py::parse_intent` 的 prompt 使用方式：
  - 将现有 `SYSTEM_PROMPT` 拆为 `TOOL_USE_PROMPT` 和 `FINAL_REPLY_PROMPT`。
  - `agent.run_turn()` 使用 `TOOL_USE_PROMPT + "\n" + FINAL_REPLY_PROMPT`。
  - `parse_intent` 使用精简 system prompt，避免推荐标记规则污染离线评估的强制工具调用行为。
  - 在 `api_index.md` 登记 `TOOL_USE_PROMPT`、`FINAL_REPLY_PROMPT` 的职责。
- 新增推荐标记解析器：
  - 解析 `INTRO`、`ITEM id/group`、`REASON`、`OUTRO`。
  - 校验 `id` 来自本轮候选。
  - 校验多 request 场景下 `group` 来自 `requests[].label`；单 request 或无 label 时拒绝多余 group。
  - 校验 `<ITEM>` 属性字符集，拒绝需要转义的属性值。
  - 校验 reason 非空。
  - 校验每个 `<ITEM>` 内必须且只能有一个 `<REASON>`。
  - 校验 `<INTRO>`、`<ITEM>`、`<OUTRO>` 顺序和禁止嵌套规则。
  - 校验 `<R>` 外无非空文本。
  - 校验 `<R>` 与 `<C>` 不共存。
- 改造现有可见文本校验：
  - 从“整段 clean_text 不超过 120 字”改为按字段限制。
  - 对 `INTRO`、每条 `REASON`、`OUTRO` 分别执行移动端文本校验。
  - `_MOBILE_VISIBLE_REPLY_MAX_CHARS` 保留为非推荐纯文本回复的兜底限制。
- 改造隐藏标记剥离与历史落库：
  - 不再简单用 `_strip_hidden_event_marker_text()` 抠掉 `<R>` 后得到空正文。
  - 解析推荐块后拼接可读 assistant 历史，包含商品标题、product_id 和 reason。
- 新增服务端内部事件类型：
  - `BlockTextEvent`
  - `BlockProductEvent`
  - `BlockCompareEvent`
  - `StructuredStatusEvent`
- `_events_from_parsed_response()` 按块顺序产出事件：
  - intro text
  - product A
  - reason A text
  - product B
  - reason B text
  - outro text
- 精简状态阶段，只保留真实可解释的状态：
  - `retrieving`：正在检索商品...
  - `filtering`：正在筛选库存和价格...
  - `composing`：正在整理推荐...
  - `streaming`：正在输出推荐...
- 状态不写入 conversation 历史。
- 扩展后端测试：
  - 标记协议正常解析。
  - 普通同类推荐和跨类目组合推荐均能产出正确块顺序。
  - 非法商品 ID、非法 group、非法属性字符、空 reason、标签嵌套、`<R>` 外非空文本、`<R>`/`<C>` 共存均触发可恢复错误。
  - 历史落库包含商品标题、product_id 和 reason。
  - `/api/chat` 只发送新版推荐块事件，不发送旧 `product`、`compare`、`token`。
  - `parse_intent` 不受最终回复标记规则影响。

验收标准：

- 服务端能按顺序输出“整体建议 -> 商品卡片 A -> A 理由 -> 商品卡片 B -> B 理由”。
- 推荐正文不再出现 `###`、Markdown 表格、大段编号说明。
- 服务端不会发送旧推荐事件。
- assistant 历史不会因 `<R>` 被剥离而变成空回复。

### 阶段 2：服务端商品详情 API 与文档同步

目标：补齐 Task 中“商品卡片支持跳转落地页”的服务端数据闭环。该阶段与阶段 1 强依赖较少，可以并行实现。

服务端任务：

- 扩展后端 `Product` 数据结构和 `block.product` payload，补充：
  - `detail_url`
  - `landing_url`
  - `highlights`
  - `stock_status`
  - `unavailable_reason`
  - `group_label`，来自 `<ITEM group="...">`
- 统一商品可用性字段：
  - `stock_status` 是枚举：`in_stock`、`low_stock`、`out_of_stock`、`inactive`。
  - 客户端不再仅凭 `stock` 数字自行判断商品是否可购买。
  - `unavailable_reason` 上移为通用 Product 字段，购物车 `CartItem` 复用同名字段，避免 `schemas.py` 与 Android model 里出现两套相似定义。
- 新增 `ProductStore.get_product_detail(product_id)`：
  - 从 MySQL 最新快照读取基础字段。
  - 从 `raw_json`、`description` 或已有商品结构派生规格、卖点、评价摘要、FAQ。
  - 不直接向客户端暴露完整 `raw_json`。
- 新增 `GET /api/products/{product_id}`：
  - 详情接口公共可读，不绑定 `conversation_id`。
  - 商品不存在返回 `404`。
  - 商品下架或无库存时仍可返回基础详情，但必须带 `stock_status` 和 `unavailable_reason`，客户端据此禁用加购。
  - 加购仍走现有 `/api/cart*`，继续依赖近期展示商品池和 MySQL 最新状态校验。
- 如果数据集没有真实外部商品页，`landing_url` 返回 `null`，`detail_url` 指向 App 内详情接口。
- 更新 `api_index.md`：
  - 补 `block` 事件结构。
  - 补结构化 `status` 字段。
  - 补 `GET /api/products/{product_id}`。
  - 更新 `product` payload 字段说明。
- 更新 `architecture.md`：
  - 说明块式 SSE 数据流。
  - 说明商品详情 API 不绑定会话，但购物车加购继续绑定近期展示池。
  - 说明商品卡片、详情页、购物车之间的数据关系。
- 更新端到端验证脚本：
  - `eval/run_cart_e2e.py` 改为只验证块协议链路。
- 增加后端测试：
  - 商品详情接口返回完整字段。
  - 不存在商品返回 `404`。
  - 下架/无库存商品返回明确状态。
  - `block.product` 包含详情跳转字段和 group label。

验收标准：

- 每个商品卡片事件都包含可用于跳转的 `detail_url`。
- Android 可通过 `product_id` 请求商品详情页数据。
- 详情接口不要求 `conversation_id`，但加购仍不能绕过现有校验。
- 文档与实际 API 保持一致。

### 阶段 3：服务端真 Streaming 与取消语义

目标：直接实现真 LLM streaming，不做伪流式。使用固定标记协议进行增量字段提取，降低隐藏结构解析复杂度。

服务端任务：

- 将最终回复调用改为 streaming completion。
- 实现最小可用的流式标记提取器：
  - 识别 `<R>`、`</R>`、`<INTRO>`、`</INTRO>`、`<ITEM id="..." group="...">`、`</ITEM>`、`<REASON>`、`</REASON>`、`<OUTRO>`、`</OUTRO>`。
  - 进入 `INTRO`、`REASON`、`OUTRO` 后，按可见文本增量发送 `text_delta`。
  - 识别 `<ITEM id="...">` 后，先校验 product_id，再发送对应 `product` block，随后再发送该 item 的 reason delta。
  - 标签本身和隐藏结构不得泄漏给客户端。
  - 对跨 chunk 的标签和属性做缓冲处理。
  - 对 Unicode codepoint 安全切分；避免在 UTF-8 字节中间或 surrogate pair 中间切分。
  - emoji 等复杂 grapheme cluster 尽量不拆；无法完全支持时至少保证不产生非法 Unicode。
- 明确 `<C>` 对比场景的 streaming 路径：
  - 对比场景仍可使用 streaming completion。
  - 服务端识别到 `<C>` 后缓冲到 `</C>` 闭合，再 `json.loads` 解析并一次性发送完整 compare block。
  - 对比场景可以牺牲首可见文本延迟，推荐链路不受影响。
  - `<COMPARE>` 固定标签协议不纳入本轮，后续单独规划。
- `text_delta` 节流策略：
  - 每次发送 1-3 个中文字符或一个短词。
  - 最小刷新间隔 16ms。
  - 最大等待 80ms，避免长时间无输出。
  - 服务端只做网络事件节流，客户端仍可做 UI 层合并。
- 状态清空协作：
  - 服务端在发送首个 `text_delta` 或首个 `product` block 时，客户端应清空 `streamingStatus`。
  - `streaming` 状态只表示服务端已进入最终输出阶段，不应与可见推荐块长期并存。
- SSE 断开与取消：
  - `event_stream` 检测客户端断开，取消当前 `run_turn` 任务。
  - 取消正在进行的 LLM streaming 请求。
  - 记录 `logger.info("llm_call_cancelled", ...)`。
  - 已发送的可见文本和商品 ID 作为 interrupted assistant 历史落库。
- 异常恢复：
  - streaming 中断时发送 `error` + `done`。
  - 已发送的商品和文本不回滚。
  - 结构错误仍走可恢复机制；恢复失败后发送清晰错误事件。
- 补充后端测试：
  - 标签不会出现在 SSE 可见事件中。
  - 跨 chunk 标签可正确识别。
  - `ITEM` 识别后 product block 先于 reason delta。
  - `<C>` 对比场景缓冲到闭合后发送完整 compare block。
  - Unicode 文本切分合法。
  - 客户端断开后服务端取消 LLM 调用并落库 interrupted 历史。
  - `error` + `done` 收尾稳定。

验收标准：

- 用户发送消息后能快速看到首个状态。
- 推荐文本通过真实 LLM streaming 以 delta 形式持续出现。
- `<R>`、`<ITEM>`、`<REASON>` 等隐藏标签不会出现在客户端。
- 客户端取消或断开后，服务端不继续空跑到 60s timeout。

### 阶段 4：Android 客户端块式消息流、商品详情与体验改造

目标：客户端集中消费前三阶段服务端能力，实现文本与商品卡片交替、单卡居中、详情跳转、丰富等待态和移动端友好的对比展示。

客户端任务：

- 重构消息模型。当前 `Message` 是 `content + products + compareTables`，需要改为块式结构：

```kotlin
data class Message(
    val id: String,
    val role: MessageRole,
    val blocks: List<MessageBlock>,
    val isStreaming: Boolean,
    val isError: Boolean,
    val interrupted: Boolean = false
)
```

```kotlin
sealed interface MessageBlock {
    data class TextBlock(
        val id: String,
        val content: String
    ) : MessageBlock

    data class ProductBlock(
        val id: String,
        val productId: String,
        val card: ProductCardData
    ) : MessageBlock

    data class CompareBlock(
        val id: String,
        val table: CompareTable
    ) : MessageBlock
}
```

- 状态不要放入 `MessageBlock`，改为 `ChatUiState.streamingStatus`：

```kotlin
data class StreamingStatus(
    val phase: String,
    val message: String,
    val step: Int?,
    val totalSteps: Int?
)
```

- 更新 `ChatEvent`：
  - `BlockText`
  - `BlockTextDelta`
  - `BlockProduct`
  - `BlockCompare`
  - `StructuredStatus`
- 更新 `ChatApiService`：
  - 解析 `block` SSE。
  - 解析结构化 `status`。
  - 解析扩展后的商品字段：`detailUrl`、`landingUrl`、`highlights`、`stockStatus`、`unavailableReason`、`groupLabel`。
- 更新 `ChatViewModel`：
  - 收到 `text` 时插入完整 `TextBlock`。
  - 收到 `text_delta` 时按 `block_id` 追加到对应 `TextBlock`。
  - 收到 `product` 时按顺序插入 `ProductBlock`。
  - 收到 `status` 时更新 `streamingStatus`，完成或失败后清空。
  - 收到首个 `text_delta` 或首个 `product` block 时清空 `streamingStatus`，避免状态条与可见推荐内容长期并存。
  - 对高频 delta 做 16-33ms UI 合并，避免 Compose 过度重组。
  - 取消当前回复时取消 EventSource，将消息标记为 interrupted，并保留已输出内容；客户端取消依赖阶段 3 的服务端 SSE 断开检测，无需新增 cancel API。
- 更新 `ChatScreen`：
  - 按 `MessageBlock` 顺序渲染，不再先渲染大文本再渲染商品列表。
  - 商品卡片独立居中纵向展示，不再默认使用横向 `LazyRow`。
  - 推荐流展示顺序应为“整体建议 -> 商品卡片 A -> A 理由 -> 商品卡片 B -> B 理由”。
- 重做商品卡片：
  - 每张卡片 `fillMaxWidth(0.92f)`，并设置 `widthIn(max = 420.dp)`。
  - 图片比例稳定，避免加载后跳动。
  - 标题最多 2 行，价格和品牌位置固定。
  - 主按钮为“查看详情”，次按钮为“加入购物车”。
  - 点击卡片或“查看详情”进入详情页。
  - 失败图片、无库存、下架状态要有明确视觉状态。
- 分组展示策略：
  - 连续 `ProductBlock` 的 `groupLabel` 相同时，不重复展示分组标题。
  - `groupLabel` 变化时，在该商品卡片上方插入紧凑分组标签，例如“防晒护肤”“度假穿搭”。
  - `groupLabel` 为空时不展示分组标签。
- 新增商品详情页：
  - 通过 `GET /api/products/{product_id}` 拉取详情。
  - 展示图片、标题、价格、库存、规格、卖点、评价摘要、FAQ。
  - 详情页支持加入购物车，并复用现有购物车错误提示。
  - 如果后端返回 `landing_url`，提供“打开商品页”；否则停留在原生详情页。
- 重做等待态：
  - 检索阶段展示商品卡片骨架屏或紧凑状态条。
  - 输出阶段展示光标或流式点状动画。
  - 取消后停止动画并保留已输出内容。
- 重做对比展示：
  - 默认不再渲染横向宽表。
  - 将 `CompareTable` 转为纵向维度卡片：

```text
价格
蒙牛：85元/16盒
伊利：72元/12盒

适合人群
蒙牛：家庭早餐、补钙
伊利：有机品质、老人小孩
```

  - 超过 3 个商品时，提示用户选择要对比的 2-3 个商品，避免手机端横向挤压。
- 增加 Android 测试：
  - `block` 事件解析。
  - `text_delta` 合并。
  - 商品扩展字段解析。
  - 状态不进入消息块。
  - 购物车错误提示不回归。

验收标准：

- Android 中展示顺序为“整体建议 -> 商品卡片 A -> A 理由 -> 商品卡片 B -> B 理由”。
- 每个商品卡片居中独立展示，不再横排挤压。
- 文本以逐字或短片段形式持续出现。
- 点击商品卡片进入商品详情页。
- 详情页能展示主图、价格、库存、卖点、评价摘要等信息。
- 等待阶段有明确状态和骨架屏，但状态不会占用聊天消息流位置。
- 对比内容在手机端无需横向滑动即可阅读。

### 阶段 5：Android 购物车打开即同步最新快照

目标：用户点开购物车详情页时，客户端立即调用后端 `GET /api/cart`，用 MySQL 最新快照刷新本地购物车，展示最新价格、库存不足、商品下架或商品不存在等变化；不再依赖用户先点击「+」「-」或「加入购物车」触发刷新。

服务端前置能力：

- `GET /api/cart` 已经通过 `cart_store.snapshot()` 重新读取 MySQL 最新商品状态。
- 购物车快照会更新商品当前价格和总价。
- 当商品价格相对上次购物车快照展示价变化时，`messages` 返回一次性价格变动提示。
- 商品库存不足时保留购物车条目，并通过 `unavailable_reason` / `stock_status` 告知客户端禁用数量调整。
- 商品不存在或已下架时从内存购物车移除，并在 `messages` 返回移除原因。

客户端任务：

- `ChatRoute` 将 `viewModel::refreshCart` 传给 `ChatScreen`，例如新增 `onRefreshCart: () -> Unit` 参数。
- `ChatScreen` 点击顶部购物车图标时先调用 `onRefreshCart()`，再设置 `showCart = true`。
- 底部 `CartSummaryBar` 点击时同样先调用 `onRefreshCart()`，再打开 `CartSheet`。
- 打开 `CartSheet` 后复用现有 `isCartLoading` 显示加载态；刷新期间禁止重复清空、加减和删除操作。
- `CartSheet` 继续展示 `cart.messages`，用于呈现价格更新、缺货、下架或商品不存在等后端提示。
- `CartItemRow` 继续根据 `unavailableReason`、`stock`、`isActive` 禁用数量调整，并保留删除入口。
- 刷新失败时保留当前本地 cart，同时通过现有 `cartError` 显示错误，不清空用户已看到的购物车内容。
- 如后续引入真实页面导航，进入购物车详情页的导航入口也必须先触发 `refreshCart()` 或在页面 `LaunchedEffect` 中触发一次刷新。

客户端测试：

- 点击顶部购物车图标会调用 `refreshCart()` 并打开购物车。
- 点击底部购物车摘要会调用 `refreshCart()` 并打开购物车。
- 刷新期间 `CartSheet` 展示加载态并禁用加减、删除、清空。
- `GET /api/cart` 返回的价格更新消息能展示在 `CartNoticeList`。
- 刷新失败时显示 `cartError`，且不清空当前购物车条目。

验收标准：

- 在 MySQL 中修改购物车商品价格后，不执行任何加减或加购操作，直接打开购物车即可看到最新价格、总价和价格变动提示。
- 在 MySQL 中把购物车商品库存改为 0 后，直接打开购物车即可看到缺货提示，数量调整按钮不可用。
- 在 MySQL 中下架或删除购物车商品后，直接打开购物车即可看到后端移除提示。

## 风险与已敲定决策

- 已敲定：不做服务端伪流式。阶段 1 只做块顺序协议；阶段 3 直接做真 LLM streaming。
- 已敲定：不使用 `<R>{JSON}</R>`，改用更易流式解析的固定标记协议。
- 已敲定：不做新旧协议兼容，服务端和客户端只实现块式协议。
- 已敲定：商品详情接口公共可读，不绑定 `conversation_id`；加购继续绑定近期展示商品池。
- 已敲定：状态不作为聊天消息块落入对话流，而是客户端临时 UI 状态。
- 已敲定：对比 `<C>` 在本轮真 streaming 中采用闭合后整体解析发送 compare block，不做增量对比流式解析。
- 已敲定：客户端取消依赖 SSE 断开检测和服务端任务取消，不新增单独 cancel API。
- 风险：固定标记协议仍可能被 LLM 写错，必须保留当前可恢复错误机制。
- 风险：真 streaming 的增量标记解析要处理跨 chunk 标签、属性、Unicode 边界和中断落库，阶段 3 不应低估测试成本。
- 风险：Android 块式消息模型会影响聊天、商品、对比、购物车多个 UI 区域；切换期间允许系统临时不可用，直到整轮计划完成。

## Stage completion update

- Stage 4 completed on the Android client: chat messages now render from ordered `Message.blocks`, streaming status is separate UI state, product cards are centered vertical cards, compare content is rendered vertically, and product details load from `GET /api/products/{product_id}` into a bottom sheet.
- Stage 5 completed on the Android client: tapping the top-bar cart icon or `CartSummaryBar` now calls `refreshCart()` before opening `CartSheet`, and cart mutations are disabled while the refresh is in flight.
