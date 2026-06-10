# 电商导购 Agent 后续实施任务

## 一、当前系统状态

项目已经完成 MVP 核心链路：后端基于 FastAPI + SSE 提供流式对话接口，Agent 采用单跳工具调用架构，通过 `retrieve_products` 工具执行 RAG 商品检索；客户端为 Android Kotlin/Compose，已经支持聊天输入、流式文本渲染、商品卡片展示、商品详情弹窗和基础多轮对话。

当前已完成能力包括：

- 商品检索：bge-base-zh-v1.5 embedding、ChromaDB 向量库、metadata filter、must/exclude 加权重排。
- Agent 编排：LLM 自主决定是否调用检索工具，支持普通推荐、反问澄清、多轮追问和否定约束。
- 推荐展示：后端通过 `<R>` 标记约束商品卡片输出，客户端消费 `product` SSE 事件渲染商品卡片。
- 对比与组合推荐：后端支持 `requests[]` 多子需求检索和 `<C>` 结构化对比事件，客户端已具备消费对比事件的扩展方向。
- 购物车闭环后端：已完成内存购物车、HTTP 操作接口、自然语言购物车工具和 SSE `cart` 同步事件。
- 评估体系：已有离线检索评估脚本和 ground truth，用于验证检索质量。

下一阶段重点转向**Android 购物车 UI 与端到端验证**：在客户端消费购物车状态，让用户可以通过商品卡片按钮、全局购物车摘要栏和底部弹窗完成加购、查看、改数量、删除等操作。

## 二、购物车闭环目标

### 目标范围

本阶段只实现购物车管理，不实现模拟下单、地址确认、支付或库存扣减。

目标能力：

- 用户可以说“把刚才那款加到购物车”“第二个加两件”“删掉购物车里的耳机”“把数量改成 1”。
- 商品卡片上提供加购按钮，用户可以直接点击加入购物车。
- 客户端展示全局购物车摘要栏，点击后打开底部弹窗查看和管理购物车。
- 后端通过 SSE `cart` 事件向客户端实时同步购物车状态。
- 购物车暂时使用内存存储，按 `conversation_id` 隔离。

### 非目标

- 不做真实下单。
- 不做地址、优惠券、库存、支付、物流等交易系统能力。
- 不做持久化购物车，服务重启后购物车可丢失。
- 不引入用户账号体系。

## 三、总体设计

### 后端设计

新增内存购物车模块：

- `server/cart_store.py`
  - 按 `conversation_id` 保存购物车。
  - 提供 add / remove / update / view / clear 操作。
  - 计算 `total_quantity` 和 `total_price`。

新增购物车工具：

- `server/tools/cart.py`
  - `add_to_cart`
  - `remove_from_cart`
  - `update_cart_item`
  - `view_cart`
  - `clear_cart`

扩展 Agent：

- 将购物车工具加入工具注册表。
- 在 Agent prompt 中明确购物车操作规则。
- 维护最近展示商品池，用于解析“刚才那个”“第一个”“第二个”等指代。
- 最近展示商品池同时作为商品卡片加购接口的后端可信商品来源，避免客户端或模型重新拼装商品价格、标题和图片。
- 工具执行后产出 `CartEvent`，由 `/api/chat` 转为 SSE `cart` 事件。

扩展 SSE：

```text
event: cart
data: {
  "items": [
    {
      "product_id": "...",
      "title": "...",
      "brand": "...",
      "category": "...",
      "sub_category": "...",
      "price": 99.0,
      "image_url": "...",
      "quantity": 2
    }
  ],
  "total_quantity": 2,
  "total_price": 198.0
}
```

### 客户端设计

新增数据模型：

- `Cart`
- `CartItem`
- `ChatEvent.CartUpdated`

扩展 `ChatViewModel`：

- 在 `ChatUiState` 中保存当前购物车状态。
- 消费 SSE `cart` 事件并更新全局购物车。
- 为商品卡片加购按钮提供调用入口。

扩展 UI：

- 商品卡片增加加购按钮。
- 聊天页增加全局购物车摘要栏，展示商品件数和总价。
- 点击摘要栏打开底部弹窗，展示购物车明细。
- 底部弹窗支持查看、增加数量、减少数量、删除商品。

## 四、分阶段实施计划

### 阶段 1：后端购物车基础能力

目标：建立可信的购物车状态层，并提供确定性的 HTTP 操作接口，为自然语言和按钮加购共用。

任务：

1. 新增 `server/cart_store.py`，按 `conversation_id` 维护内存购物车。
2. 定义购物车快照结构，包含商品明细、总件数和总价。
3. 实现购物车基础操作：
   - 加购商品。
   - 删除商品。
   - 修改数量。
   - 查看购物车。
   - 清空购物车。
4. 建立最近展示商品池：
   - 记录最近若干个 `ProductEvent` 商品。
   - 支持按 `product_id` 找回后端已发送过的商品快照。
   - 支持后续 Agent 解析“第一个”“第二个”“刚才那款”等指代。
5. 新增购物车 HTTP 接口，供客户端按钮和底部弹窗直接操作：
   - `GET /api/cart`
   - `POST /api/cart/items`
   - `PATCH /api/cart/items/{product_id}`
   - `DELETE /api/cart/items/{product_id}`
   - 可选 `DELETE /api/cart`
6. 更新 `api_index.md` 和 `architecture.md` 中的购物车接口、状态存储和数据流说明。

验收标准：

- 同一 `conversation_id` 下可正确加购、删除、改数量、清空。
- 不同 `conversation_id` 的购物车互不影响。
- 商品卡片按钮只需传 `conversation_id`、`product_id`、`quantity`，后端能从最近展示商品池解析商品快照。
- 商品不在最近展示商品池中时接口返回错误，不猜测、不额外检索。

### 阶段 2：Agent 自然语言购物车操作与 SSE 同步

目标：让用户可以通过自然语言管理购物车，并通过 SSE `cart` 事件实时同步客户端状态。

任务：

1. 新增 `server/tools/cart.py`，定义并实现购物车工具：
   - `add_to_cart`
   - `remove_from_cart`
   - `update_cart_item`
   - `view_cart`
   - `clear_cart`
2. 更新 `server/tools/__init__.py`，将购物车工具加入工具注册表。
3. 扩展 Agent system prompt：
   - 用户明确要求购物车操作时调用 cart 工具。
   - “第一个”“第二个”“刚才那款”优先指向最近展示商品。
   - 指代不明确时必须反问。
   - 不允许编造购物车中不存在的商品、价格或优惠。
4. 在 `server/agent.py` 中新增 `CartEvent` dataclass。
5. 在 `server/main.py` 中将 `CartEvent` 转为 SSE `event: cart`。
6. 工具操作成功后返回购物车快照，并触发 `CartEvent`。

验收标准：

- “把刚才第一款加到购物车”能正确加购最近展示的第一个商品。
- “第二个加两件”“把数量改成 1”“删掉购物车里的耳机”能正确操作购物车。
- “购物车里有什么”能返回当前购物车状态。
- 指代不明确时 Agent 反问，而不是猜测。
- `cart` 事件不影响现有 `status`、`product`、`compare`、`token`、`done` 事件。

### 阶段 3：Android 购物车 UI 与端到端验证

目标：完成购物车闭环的 Demo 验证和文档维护。

任务：

1. 新增客户端购物车数据模型：
   - `data/model/Cart.kt`
   - `data/model/CartItem.kt`
2. 扩展 SSE 事件解析：
   - `ChatEvent.CartUpdated(cart: Cart)`
   - `ChatApiService` 解析 `cart` 事件。
   - `ChatViewModel` 将购物车保存到 `ChatUiState.cart`。
3. 在聊天页增加全局购物车摘要栏：
   - 展示当前商品件数。
   - 展示当前总价。
   - 点击后打开底部弹窗。
4. 实现购物车底部弹窗：
   - 展示商品图、标题、单价、数量、小计。
   - 支持数量 +1、数量 -1、删除商品。
   - 空购物车时展示简洁空状态。
5. 在 `ProductCard` 增加加购按钮：
   - 点击后调用 `POST /api/cart/items`。
   - 成功后用返回的购物车快照刷新 `ChatUiState.cart`。
   - 加购按钮不干扰商品详情弹窗点击。
6. 编写端到端测试用例：
   - 推荐商品后点击加购。
   - 推荐商品后自然语言加购。
   - 查看购物车。
   - 修改数量。
   - 删除商品。
   - 清空购物车。
7. 验证异常边界：
   - 空购物车查看。
   - 加购不存在商品。
   - 指代不明确。
   - 不同会话购物车隔离。
8. 必要时更新 `README.md` 的 Demo 流程。

验收标准：

- 后端接口、Agent 工具调用和 Android UI 均可串联演示。
- 点击商品卡片加购按钮后，购物车摘要栏立即更新。
- 购物车底部弹窗可以查看、改数量和删除商品。
- 自然语言购物车操作能通过 `cart` SSE 事件同步到客户端。
- 文档与实际接口保持一致。
- 购物车功能不影响原有推荐、对比、多轮追问链路。

## 五、推荐实施顺序

建议按以下顺序推进：

1. 后端购物车基础能力。
2. Agent 自然语言购物车操作与 SSE 同步。
3. Android 购物车 UI 与端到端验证。

这样既能避免一次性实现完整功能，也不会把任务拆得过碎。每个阶段都有明确产出，可以单独验收。

## 六、验收注意事项

购物车的部分端到端验收需要调用 LLM，例如自然语言加购、指代解析和 Agent 工具调用。由于 LLM 请求可能受网络或代理配置影响，验收时按以下规则处理：

1. 优先使用正常后端启动方式和 curl / Android 客户端完成验收。
2. 如果 curl 调用 LLM 时出现代理或网络问题，可以尝试在 curl 命令中临时绕过代理，例如清空 `http_proxy`、`https_proxy`、`HTTP_PROXY`、`HTTPS_PROXY` 环境变量，或使用 `--noproxy '*'`。
3. 如果绕过代理后仍无法访问 LLM，不要反复重试，也不要为了通过验收改写实现方案。
4. 此时应记录已经验证通过的非 LLM 部分，例如购物车 HTTP 接口、内存状态隔离、客户端购物车 UI、商品卡片按钮加购。
5. 对依赖 LLM 的验收项，向用户说明阻塞原因，并给出可手动完成的验收步骤，包括需要启动的服务、要发送的测试消息、预期 SSE 事件和预期客户端表现。
