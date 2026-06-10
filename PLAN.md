# 电商导购 Agent 后续实施任务

## 一、当前系统状态

项目已经完成 MVP 核心链路：后端基于 FastAPI + SSE 提供流式对话接口，Agent 采用单跳工具调用架构，通过 `retrieve_products` 工具执行 RAG 商品检索；客户端为 Android Kotlin/Compose，支持聊天输入、流式文本渲染、商品卡片展示、商品详情弹窗和基础多轮对话。

当前已完成能力包括：

- 商品检索：bge-base-zh-v1.5 embedding、ChromaDB 向量库、metadata filter、must/exclude 加权重排。
- Agent 编排：LLM 自主决定是否调用检索工具，支持普通推荐、反问澄清、多轮追问和否定约束。
- 推荐展示：后端通过 `<R>` 标记约束商品卡片输出，客户端消费 `product` SSE 事件渲染商品卡片。
- 对比与组合推荐：后端支持 `requests[]` 多子需求检索和 `<C>` 结构化对比事件。
- 购物车闭环后端：已完成内存购物车、HTTP 操作接口、自然语言购物车工具和 SSE `cart` 同步事件。
- 可信商品快照：购物车加购只接受最近展示商品池中的后端商品快照，避免客户端或模型自行拼装标题、价格和图片。
- 评估体系：已有离线检索评估脚本和 ground truth，用于验证检索质量。

下一阶段重点转向**数据一致性保障与特征治理**：引入 MySQL 作为商品权威源，运行时将数据集加载至 MySQL；ChromaDB 作为语义索引与 MySQL 初始保持一致，后台每 10 分钟从 MySQL 增量同步。线上推荐链路允许 ChromaDB 短暂滞后，但价格、库存、上下架等关键字段必须以 MySQL 实时状态为准。

## 二、数据一致性目标

### 核心原则

- MySQL 是商品价格、库存、上下架状态和商品主数据的唯一权威源。
- ChromaDB 只负责语义召回和检索辅助，不作为价格、库存等关键字段的最终依据。
- LLM 只负责推荐理由和表达，不允许生成或修改商品价格、库存、优惠等关键参数。
- 推荐展示、商品卡片、购物车加购和后续模拟下单前，都必须读取或校验 MySQL 最新状态。
- 接受 ChromaDB 语义索引最多 10 分钟的最终一致性，但不接受价格、库存、上下架状态在用户可见结果中滞后。

### 目标能力

- Server 启动时自动读取 `ecommerce_agent_dataset/`，将商品数据幂等写入 MySQL。
- ChromaDB 初始索引与 MySQL 商品数据保持一致。
- 检索时先从 ChromaDB 召回候选 `product_id`，再从 MySQL 实时补全商品详情。
- MySQL 中无库存、已下架、价格不满足用户约束的商品，不返回给 LLM 和客户端。
- 后台任务每 10 分钟扫描 MySQL 变更，并增量更新 ChromaDB。
- 同步期间服务继续可用；此时 ChromaDB 可能召回旧候选，但最终展示结果仍由 MySQL 过滤。

### 非目标

- 不实现真实支付、真实库存扣减和订单履约。
- 不引入复杂分布式事务、消息队列或 CDC。
- 不要求 ChromaDB 与 MySQL 强一致。
- 不为了兼容旧数据结构保留双写分支；后续商品权威字段统一走 MySQL。

## 三、总体设计

### MySQL 商品权威源

新增商品表，建议命名为 `products`：


| 字段               | 说明                   |
| ---------------- | -------------------- |
| `product_id`     | 商品唯一 ID，主键           |
| `title`          | 商品标题                 |
| `brand`          | 品牌                   |
| `category`       | 一级类目                 |
| `sub_category`   | 二级类目                 |
| `price`          | 最新价格                 |
| `stock`          | 最新库存                 |
| `is_active`      | 是否上架                 |
| `description`    | 商品详情描述               |
| `image_url`      | 主图地址                 |
| `embedding_text` | 用于生成 embedding 的紧凑文本 |
| `created_at`     | 创建时间                 |
| `updated_at`     | 最近更新时间               |


设计要求：

- `product_id` 必须稳定，作为 MySQL、ChromaDB、购物车和客户端商品卡片之间的关联键。
- 启动加载数据集时使用 upsert，避免重复插入。
- `updated_at` 用于后台同步任务判断哪些商品需要重新写入 ChromaDB。
- 数据集中的 `stock` 字段进入 MySQL 后即视为权威库存；若后续新增商品缺失该字段，加载时默认 `stock = 2`。
- 商品下架不删除 MySQL 记录，只更新 `is_active = false`，便于购物车和历史会话做明确校验。

### ChromaDB 语义索引

ChromaDB 存储内容：

- `product_id`
- embedding 向量
- 用于 LLM 阅读的商品文本或摘要
- 稳定 metadata：`category`、`sub_category`、`brand`
- 可选 metadata：价格区间，但不能作为最终价格判断依据

设计要求：

- ChromaDB 的文档内容从 MySQL 的 `embedding_text` 或商品字段生成。
- ChromaDB 中可以保留商品描述、卖点、评价摘要等相对稳定内容。
- 价格、库存、上下架等易变字段即使写入 ChromaDB，也只能作为粗召回辅助。
- 为避免价格变动导致漏召回，预算筛选应优先在 MySQL 层做精确过滤；ChromaDB 价格 filter 只能在确认风险可接受时使用。

### 在线推荐链路

推荐链路调整为：

```text
用户消息
  -> Agent 决策调用 retrieve_products
  -> ChromaDB 语义召回 Top-N product_id
  -> MySQL 批量查询最新商品状态
  -> 过滤 is_active=false / stock<=0 / 最新价格不满足约束的商品
  -> 将 MySQL 商品快照注入 LLM
  -> LLM 生成推荐理由
  -> SSE product 事件发送 MySQL 商品快照
```

关键约束：

- `ProductEvent.product_data.price` 必须来自 MySQL。
- 最近展示商品池记录的也必须是 MySQL 商品快照。
- 购物车加购时再次读取或校验 MySQL，不能只信任最近展示商品池里的旧价格。
- 如果商品展示后价格变动，购物车应使用最新价格，并向用户提示价格已更新。
- 如果商品展示后库存变为 0 或下架，加购应失败并说明原因。

### 后台 ChromaDB 同步

后台同步任务每 10 分钟执行一次：

```text
读取 last_sync_at
  -> 查询 MySQL 中 updated_at > last_sync_at 的商品
  -> 对新增/修改/重新上架商品生成 embedding_text 和 embedding
  -> upsert 到 ChromaDB
  -> 对下架商品从 ChromaDB 删除，或更新 inactive metadata
  -> 成功后更新 last_sync_at
```

同步要求：

- 同步任务不能阻塞 `/api/chat` 和购物车接口。
- 同步失败应记录日志并等待下一轮重试，不改变在线检索链路。
- 如果同步期间用户请求命中旧 ChromaDB 内容，MySQL 过滤层负责剔除失效商品。
- `last_sync_at` 必须持久化，避免服务重启后误判同步进度。
- 初始建库和周期同步复用同一套索引写入逻辑，避免两套数据转换规则。

## 四、分阶段实施计划

### 阶段 1：MySQL 商品权威源

目标：建立商品主数据层，让价格、库存、上下架状态有唯一可信来源。

任务：

1. 引入 MySQL 连接配置：
  - `MYSQL_HOST`
  - `MYSQL_PORT`
  - `MYSQL_USER`
  - `MYSQL_PASSWORD`
  - `MYSQL_DATABASE`
2. 新增商品数据访问模块，例如 `server/product_store.py`：
  - 初始化连接池或会话工厂。
  - 提供按 `product_id` 批量查询商品接口。
  - 提供数据集 upsert 接口。
  - 提供按 `updated_at` 查询增量变更接口。
3. 新增 MySQL 表结构初始化脚本或启动时建表逻辑。
4. Server 启动时扫描 `ecommerce_agent_dataset/`：
  - 解析原始商品 JSON。
  - 生成稳定 `product_id`。
  - 生成 `embedding_text`。
  - upsert 到 MySQL。
5. 明确数据集字段映射：
  - 原始价格映射到 `price`。
  - 原始主图映射到 `image_url`。
  - 读取数据集 `stock` 字段；缺失时设置默认库存 `2`。
  - 缺失上下架状态时设置 `is_active = true`。
6. 增加最小验证脚本或测试：
  - 首次启动能写入商品。
  - 重复启动不会产生重复数据。
  - 修改数据集价格后再次启动能更新 MySQL。

验收标准：

- MySQL 中商品数量与数据集商品数量一致。
- `product_id` 稳定且唯一。
- 重复启动 server 后商品数量不增加。
- 能通过 `product_id` 批量读取最新价格、库存和上下架状态。

### 阶段 2：ChromaDB 初始构建改为基于 MySQL

目标：让 ChromaDB 的初始内容来自 MySQL，而不是直接读取数据集形成另一套事实来源。

任务：

1. 调整 `server/ingest.py`：
  - 从 MySQL 读取 `is_active = true` 的商品。
  - 使用 MySQL 中的 `embedding_text` 生成 embedding。
  - 将 `product_id` 写入 ChromaDB metadata。
2. 确保 ChromaDB metadata 至少包含：
  - `product_id`
  - `category`
  - `sub_category`
  - `brand`
3. 保留商品描述、卖点、评价摘要等检索需要的信息。
4. 避免把 MySQL 之外的价格、库存副本作为在线展示依据。
5. 为初始构建增加可重复执行能力：
  - 可清空重建。
  - 可 upsert 更新。

验收标准：

- 清空 ChromaDB 后可从 MySQL 完整重建向量索引。
- ChromaDB 中每条记录都能通过 `product_id` 回查 MySQL 商品。
- MySQL 下架商品不会进入新的 ChromaDB 初始索引。

### 阶段 3：检索后 MySQL 实时补全与过滤

目标：保证推荐给 LLM 和客户端的商品关键字段始终来自 MySQL 最新状态。

任务：

1. 调整 `server/retriever.py` 返回流程：
  - ChromaDB 召回候选时取 Top-N，N 应大于最终展示数量。
  - 提取候选 `product_id`。
  - 批量查询 MySQL 最新商品快照。
2. 实现 MySQL 过滤规则：
  - 过滤 `is_active = false`。
  - 过滤 `stock <= 0`。
  - 如果用户有预算，使用 MySQL 最新价格过滤。
  - 如果用户有品牌、类目等结构化条件，优先使用 MySQL 字段做最终校验。
3. 调整返回给 Agent 的商品结构：
  - 标题、品牌、类目、价格、图片、库存状态均来自 MySQL。
  - ChromaDB distance 和重排分数只作为排序信号。
4. 调整 Agent prompt：
  - 明确价格、库存、优惠只能引用工具返回字段。
  - 禁止自行推断库存、折扣和不存在的商品属性。
5. 调整 SSE `product` 事件：
  - 发送 MySQL 商品快照。
  - 最近展示商品池记录同一份快照。

验收标准：

- 修改 MySQL 中某商品价格后，无需重建 ChromaDB，下一次推荐展示即使用新价格。
- 将 MySQL 中某商品 `stock` 改为 0 后，该商品不会出现在推荐卡片中。
- 将 MySQL 中某商品 `is_active` 改为 false 后，即使 ChromaDB 仍召回它，也不会返回给 LLM 和客户端。
- 预算类查询使用 MySQL 最新价格做最终判断。

### 阶段 4：购物车关键字段二次校验

目标：推荐展示后的商品在加购时仍能使用 MySQL 最新状态，避免展示快照过期。

任务：

1. 调整 `server/cart_store.py` 或购物车工具调用路径：
  - 最近展示商品池只用于解析用户指代和确认商品身份。
  - 加购前根据 `product_id` 查询 MySQL 最新商品。
2. 加购校验：
  - 商品不存在：失败。
  - 商品下架：失败。
  - 库存不足或库存为 0：失败。
  - 价格变化：使用最新价格，并返回明确提示。
3. 购物车快照价格来源：
  - 购物车展示时可重新读取 MySQL 最新价格。
  - 或在每次购物车操作后刷新对应商品快照。
4. 自然语言购物车工具和 HTTP 购物车接口共用同一套校验逻辑。
5. 更新客户端提示文案：
  - 价格已更新。
  - 商品已下架。
  - 库存不足。

验收标准：

- 商品展示后修改 MySQL 价格，再点击加购，购物车使用最新价格。
- 商品展示后将库存改为 0，再点击加购，接口返回失败。
- 自然语言“把刚才那款加到购物车”和商品卡片按钮加购表现一致。
- 购物车中不出现 MySQL 已下架或不存在的商品。

### 阶段 5：ChromaDB 后台增量同步

目标：让语义索引周期性追上 MySQL 最新商品内容，同时保持服务在线可用。

任务：

1. 新增同步状态表，例如 `sync_state`：
  - `name`
  - `last_sync_at`
  - `updated_at`
2. 新增后台同步模块，例如 `server/chroma_sync.py`：
  - 每 10 分钟触发一次。
  - 查询 MySQL 中 `updated_at > last_sync_at` 的商品。
  - 对新增、修改、重新上架商品 upsert ChromaDB。
  - 对下架商品删除 ChromaDB 记录，或更新 inactive metadata。
3. 在 FastAPI lifespan 中启动后台任务。
4. 同步任务与在线请求隔离：
  - 同步失败只记录日志。
  - 不阻塞 `/api/chat`。
  - 不阻塞购物车接口。
5. 提供手动同步入口或本地命令：
  - 便于 Demo 前强制同步。
  - 便于测试索引更新效果。
6. 记录同步日志：
  - 本轮扫描商品数。
  - upsert 数量。
  - delete 或 inactive 数量。
  - 同步耗时。
  - 错误信息。

验收标准：

- 修改 MySQL 商品描述后，最多 10 分钟内 ChromaDB 索引更新。
- 新增 MySQL 商品后，后台同步完成后可被语义检索召回。
- 下架商品在 ChromaDB 未同步前也不会被最终展示；同步后不再被 ChromaDB 正常召回。
- 同步过程中 `/api/chat` 仍可正常返回推荐结果。

### 阶段 6：文档、测试与 Demo 验收

目标：让数据一致性方案可解释、可演示、可验证。

任务：

1. 更新 `architecture.md`：
  - 增加 MySQL 商品权威源。
  - 更新推荐链路数据流。
  - 说明 ChromaDB 最终一致性边界。
  - 说明购物车二次校验。
2. 更新 `api_index.md`：
  - 如新增商品管理或同步接口，补充接口说明。
  - 更新商品卡片字段来源说明。
3. 必要时更新 `README.md`：
  - MySQL 启动方式。
  - 环境变量配置。
  - 初始化和同步命令。
4. 增加测试用例：
  - MySQL upsert 幂等性。
  - 检索后 MySQL 过滤。
  - 价格变更实时生效。
  - 库存为 0 不展示。
  - 下架商品不展示。
  - 后台同步失败不影响在线请求。
5. 准备 Demo 脚本：
  - 推荐某商品并展示价格。
  - 直接修改 MySQL 价格。
  - 再次推荐，展示新价格无需重建 ChromaDB。
  - 将商品库存改为 0。
  - 再次推荐或加购，验证商品被过滤或加购失败。
  - 修改商品描述，等待或手动触发同步，验证语义召回更新。

验收标准：

- 文档与实际实现一致。
- Demo 能清楚说明：MySQL 强一致负责关键字段，ChromaDB 最终一致负责语义索引。
- 能证明 AI 不会输出 MySQL 中已下架、无库存或过期价格的商品。

## 五、推荐实施顺序

建议按以下顺序推进：

1. MySQL 商品权威源。
2. ChromaDB 初始构建改为基于 MySQL。
3. 检索后 MySQL 实时补全与过滤。
4. 购物车关键字段二次校验。
5. ChromaDB 后台增量同步。
6. 文档、测试与 Demo 验收。

这个顺序先建立唯一事实来源，再改造在线链路，最后补齐后台同步。即使第五阶段尚未完成，前三阶段完成后也已经能保证价格、库存、上下架状态在推荐结果中实时生效。

## 六、验收注意事项

1. MySQL 是本阶段新增运行依赖。若本地未安装或未启动 MySQL，应先修复环境，而不是改成 SQLite、JSON 文件或内存存储替代。
2. ChromaDB 与 MySQL 不追求强一致；验收重点是 MySQL 关键字段是否实时生效。
3. 如果后台同步失败，在线推荐仍应可用，但新增或修改过的语义内容可能暂时无法通过 ChromaDB 召回。
4. 涉及 Agent 自然语言推荐的验收需要访问 LLM。若网络或代理导致 LLM 不可用，应记录阻塞原因，并优先验证 MySQL、ChromaDB 和购物车接口层的确定性行为。
5. 不允许为了通过演示让 LLM 直接编写价格、库存或优惠信息；所有关键字段必须来自后端工具返回的 MySQL 商品快照。

