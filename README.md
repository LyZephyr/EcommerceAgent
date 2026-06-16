# EcommerceAgent

基于 RAG 与 ReAct Agent 的电商智能导购系统。用户通过自然语言对话完成商品检索、对比推荐与购物车操作；后端以 MySQL 作为商品权威源、ChromaDB 作为语义检索索引，并通过 SSE 向客户端推送结构化消息块。

> 当前实现为**文本对话**导购。课题规划中的多模态（图片找货等）尚未接入，见 [architecture.md](architecture.md) 扩展点。

## 功能概览

- **语义检索**：向量召回 + 结构化意图过滤（类目、价格、必选/排除属性）
- **多轮对话**：会话上下文管理，支持追问、对比、场景化组合推荐
- **购物车闭环**：对话式加购、改量、删除、清空；REST API 与 Agent 工具双通道
- **流式响应**：SSE 推送文本增量、商品卡片、对比表、购物车快照与进度状态
- **移动端适配输出**：限制可见正文长度、禁止 Markdown，推荐/对比走结构化 block
- **数据一致性**：价格、库存、上下架以 MySQL 为准；ChromaDB 后台增量同步

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| LLM | 火山方舟（OpenAI 兼容 API） |
| 向量库 | ChromaDB + BAAI/bge-base-zh-v1.5 |
| 关系库 | MySQL 8 |
| 客户端 | Android（Kotlin + Jetpack Compose + OkHttp SSE） |

## 项目结构

```text
EcommerceAgent/
├── server/
│   ├── main.py              # 应用入口与生命周期
│   ├── config.py            # 环境变量
│   ├── schemas.py           # API 数据模型
│   ├── conversation.py      # 内存会话历史
│   ├── api/                 # HTTP 路由（chat / products / cart）
│   ├── agent/               # ReAct 主循环、流式解析、提示词
│   ├── tools/               # Agent 工具（检索、购物车）
│   ├── sse/mapper.py        # Agent 事件 → SSE 协议
│   ├── catalog/             # 商品卡片/详情字段派生
│   ├── retriever.py         # RAG 检索与重排
│   ├── product_store.py     # MySQL 商品权威源
│   ├── cart_store.py        # 内存购物车与近期展示商品池
│   ├── chroma_sync.py       # MySQL → ChromaDB 增量同步
│   ├── ingest.py            # 从 MySQL 构建 ChromaDB 索引
│   ├── embedding.py         # Embedding 函数封装
│   └── tests/
├── client-android/          # Android 客户端
├── ecommerce_agent_dataset/ # 商品数据集（JSON + 图片）
├── docker-compose.yml
├── .env.example
├── architecture.md
└── api_index.md
```

## 环境要求

- Python 3.12+
- Docker（MySQL）
- 火山方舟 API Key（`ARK_API_KEY`）
- 首次运行需联网下载 Embedding 模型（国内建议 `HF_ENDPOINT=https://hf-mirror.com`）

## 快速开始

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 ARK_API_KEY 等配置
```

### 2. 启动 MySQL

```bash
docker compose up -d
```

默认映射 `127.0.0.1:3306`，数据库名 `ecommerce_agent`。

### 3. 安装 Python 依赖

```bash
cd server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. 导入数据并构建向量索引

`ingest.py` **从 MySQL 读取上架商品**写入 ChromaDB，不会自动扫描 JSON 目录。全新环境需先 upsert 数据集：

```bash
cd server
python ingest.py --dataset-dir ../ecommerce_agent_dataset
```

说明：

- `--dataset-dir`：先把指定目录 JSON upsert 到 MySQL，再基于 MySQL 构建 Chroma 索引。
- 不加 `--dataset-dir`：仅读取 MySQL 已有商品（需服务曾启动过并完成 `load_dataset_to_mysql()`，或上一步已导入）。
- `--upsert`：增量更新 Chroma collection，不清空重建。

### 5. 启动后端

```bash
cd server
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

启动时会：幂等加载数据集到 MySQL、挂载 `/assets` 静态资源、每 3 分钟后台同步 ChromaDB。

验证：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

### 6. 运行 Android 客户端（可选）

后端地址在 `client-android/app/build.gradle.kts` 的 `API_BASE_URL` 中配置，**需按你的联调环境修改**：

```kotlin
buildConfigField("String", "API_BASE_URL", "\"http://192.168.188.128:8000\"")
```

| 场景 | 典型地址 |
|------|----------|
| 模拟器访问宿主机 | `http://10.0.2.2:8000` |
| 真机访问局域网后端 | `http://<电脑局域网 IP>:8000` |

客户端在本地生成 `conversation_id`（UUID），每次请求携带；服务端不通过 SSE 回传会话 ID。详见 [client-android/README.md](client-android/README.md)。

## 常用命令

```bash
cd server

# 运行测试
pytest

# 手动 ChromaDB 同步
python chroma_sync.py

# 持续同步（每 3 分钟）
python chroma_sync.py --loop

# 增量更新 Chroma（不清空 collection）
python ingest.py --upsert
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ARK_API_KEY` | 火山方舟 API Key | （必填） |
| `ARK_BASE_URL` | LLM API 地址 | `https://ark.cn-beijing.volces.com/api/v3/` |
| `ARK_MODEL` | 模型端点 ID | 见 `.env.example` |
| `EMBEDDING_MODEL` | 向量模型 | `BAAI/bge-base-zh-v1.5` |
| `HF_ENDPOINT` | Hugging Face 镜像 | `https://hf-mirror.com` |
| `HF_HUB_OFFLINE` | 仅使用本地缓存 | `0` |
| `TOP_K` | 单次检索返回商品数 | `5` |
| `CHROMA_COLLECTION_NAME` | Chroma collection 名 | `products` |
| `MYSQL_*` | MySQL 连接 | 见 `.env.example` |

## 文档索引

- [architecture.md](architecture.md) — 系统架构、Agent 编排、数据流
- [api_index.md](api_index.md) — HTTP / SSE 接口与数据模型
- [Task.md](Task.md) — 课题背景与业务场景

## 设计原则

1. **MySQL 为权威源**：价格、库存、上下架不在向量文档中固化，检索与展示时实时补全。
2. **RAG 防幻觉**：Agent 仅基于工具返回的商品资料回复；推荐/对比经 `<R>` / `<C>` 标记解析为 UI block。
3. **会话隔离**：购物车与近期展示商品池按 `conversation_id` 隔离；加购仅限本会话已展示商品。
4. **移动端输出约束**：可见正文 ≤ 120 字、禁止 Markdown；推荐 intro/reason/outro 有独立字数上限。
