# EcommerceAgent

EcommerceAgent 是一个面向移动端电商导购场景的 RAG Agent 项目。仓库包含
Python FastAPI 后端、Kotlin Jetpack Compose Android 客户端、商品样例数据集
以及离线检索评估脚本。

后端以 MySQL 作为商品权威源，使用 ChromaDB + SentenceTransformer 建立商品
语义索引，通过 OpenAI 兼容的 Ark Chat Completions 接口驱动 ReAct 工具调用。
客户端通过 SSE 消费聊天流式事件，并用 REST 接口读取商品详情和购物车状态。

## 功能

- 商品导购聊天：根据预算、品类、场景和筛选条件检索商品并生成移动端短回复。
- 商品卡片：聊天流中输出结构化商品块，包含价格、库存、图片、详情入口和卖点。
- 多类目组合推荐：一次用户请求可拆成 2-4 个检索子需求，并按 group 展示商品。
- 商品对比：支持结构化对比块，客户端渲染为对比表。
- 购物车：支持查看、加购、改量、删除、清空，并校验库存、上下架和近期展示约束。
- 商品详情：公开规格、FAQ、评价摘要等详情字段，不暴露完整原始 payload。
- 后台同步：启动时加载 JSON 数据集到 MySQL，后台周期性把 MySQL 增量同步到 ChromaDB。

## 项目结构

```text
.
├── server/                    # FastAPI 后端、Agent、RAG、MySQL/Chroma 同步
│   ├── api/                   # HTTP 路由
│   ├── agent/                 # ReAct 循环、LLM 调用、流式解析、事件模型
│   ├── catalog/               # 商品卡片与详情字段派生
│   ├── sse/                   # Agent 事件到 SSE 协议的映射
│   ├── tools/                 # LLM 可调用工具：商品检索、购物车
│   └── tests/                 # 后端单元测试
├── client-android/            # Kotlin + Jetpack Compose Android 客户端
├── ecommerce_agent_dataset/   # 商品 JSON 与图片资源
├── eval/                      # 检索评估脚本、ground truth、历史报告
├── docker-compose.yml         # MySQL 8 开发服务
├── .env.example               # 后端环境变量示例
├── architecture.md            # 架构说明
└── api_index.md               # API、事件、schema 和核心接口索引
```

## 后端快速启动

### 前置条件

- Python 3.11 或更新版本
- Docker / Docker Compose
- 可访问 Ark OpenAI 兼容接口的 `ARK_API_KEY`
- 首次构建向量库时需要下载 `EMBEDDING_MODEL`，默认是 `BAAI/bge-base-zh-v1.5`

### 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
ARK_API_KEY=your-api-key-here
MYSQL_PASSWORD=ecommerce123
```

默认 MySQL 连接为 `127.0.0.1:3306`，默认数据库为 `ecommerce_agent`。
`HF_ENDPOINT` 默认使用 `https://hf-mirror.com`；如果你的环境直连 Hugging Face，
可以改为 `https://huggingface.co`。

### 启动 MySQL

```bash
docker compose up -d mysql
```

### 安装 Python 依赖

```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 初始化商品与向量索引

启动服务时会自动把 `ecommerce_agent_dataset/` 中的 JSON 商品幂等写入 MySQL。
首次运行聊天检索前，还需要构建 ChromaDB 索引：

```bash
cd server
source .venv/bin/activate
python ingest.py
```

如果只想增量 upsert ChromaDB collection：

```bash
python ingest.py --upsert
```

### 启动 API 服务

```bash
source .env
cd server
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 基本使用

### 流式聊天

`POST /api/chat` 返回 Server-Sent Events。

```bash
curl -N \
  -H "Content-Type: application/json" \
  -X POST http://127.0.0.1:8000/api/chat \
  -d '{"conversation_id":"demo","message":"一百元以内推荐适合早餐的咖啡"}'
```

典型事件包括：

- `status`：当前阶段，如检索、筛选、输出。
- `message_start` / `message_reset` / `message_commit`：一条 assistant 消息的生命周期。
- `block`：正文增量、完整正文、商品卡片或对比表。
- `cart`：购物车发生变化时的快照。
- `done`：本轮结束。
- `error`：本轮失败。

### 商品详情

```bash
curl http://127.0.0.1:8000/api/products/p_food_001
```

### 购物车

购物车以 `conversation_id` 隔离，并且加购接口只允许加入当前会话近期真正展示过
的商品卡片。这一约束由 `cart_store.record_recent_product()` 在消息提交时记录，
用于避免模型凭空加购未展示商品。

```bash
curl "http://127.0.0.1:8000/api/cart?conversation_id=demo"
```

## Android 客户端

客户端位于 `client-android/`，使用 Kotlin、Jetpack Compose、Material 3、
OkHttp SSE 和 Coil。

API 基址写在 `client-android/app/build.gradle.kts`：

```kotlin
buildConfigField("String", "API_BASE_URL", "\"http://192.168.188.128:8000\"")
```

联调前按运行环境修改：

| 场景 | 地址示例 |
| --- | --- |
| Android 模拟器访问宿主机 | `http://10.0.2.2:8000` |
| 真机访问局域网后端 | `http://192.168.x.x:8000` |

构建 Debug 包：

```bash
cd client-android
./gradlew assembleDebug
```

## 关键配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ARK_API_KEY` | 无 | Ark / OpenAI 兼容 Chat Completions API Key |
| `ARK_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3/` | OpenAI 兼容 API 基址 |
| `ARK_MODEL` | `ep-20260514111645-lmgt2` | 聊天模型名称 |
| `EMBEDDING_MODEL` | `BAAI/bge-base-zh-v1.5` | ChromaDB 使用的 SentenceTransformer 模型 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | Hugging Face 下载端点 |
| `HF_HUB_OFFLINE` | `0` | 设为 `1` 时只使用本地模型缓存 |
| `TOP_K` | `5` | 默认商品召回数量 |
| `MYSQL_HOST` | `127.0.0.1` | MySQL 主机 |
| `MYSQL_PORT` | `3306` | MySQL 端口 |
| `MYSQL_USER` | `root` | MySQL 用户 |
| `MYSQL_PASSWORD` | 空字符串 | MySQL 密码 |
| `MYSQL_DATABASE` | `ecommerce_agent` | MySQL 数据库名 |

## 数据与状态

- 商品 JSON 和图片在 `ecommerce_agent_dataset/{category}/data|images/`。
- `server/product_store.py` 启动时把商品 JSON upsert 到 MySQL `products` 表。
- `server/ingest.py` 从 MySQL 上架商品构建 ChromaDB collection。
- `server/chroma_sync.py` 后台每 180 秒同步 MySQL 的增量变更到 ChromaDB。
- 会话历史、购物车和近期展示商品池当前都是进程内内存状态；服务重启后会丢失。
- 商品权威字段以 MySQL 为准；ChromaDB 只保存检索用文本和稳定 metadata。

