# EcommerceAgent — 电商智能导购 AI Agent

基于 RAG 技术的多模态电商智能导购助手，通过自然语言对话帮助用户发现和选购商品。

## 项目结构

```
├── server/                     # Python 后端
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── product_store.py        # MySQL 商品权威源
│   ├── ingest.py               # 数据导入 & 向量化
│   ├── chroma_sync.py          # MySQL -> ChromaDB 增量同步
│   ├── retriever.py            # RAG 检索模块
│   ├── agent.py                # Agent 编排
│   ├── cart_store.py           # 内存购物车
│   ├── schemas.py              # 数据模型
│   └── requirements.txt        # Python 依赖
├── eval/                       # 离线检索评估
│   ├── ground_truth.json       # 评估 query 与标注
│   ├── run_retrieval_eval.py   # 评估脚本
│   └── reports/                # 评估报告输出
├── client-android/             # Android 客户端 (Kotlin/Compose)
├── ecommerce_agent_dataset/    # 商品数据集 (4 类目 × 25 条)
├── docker-compose.yml          # 开发用 MySQL 容器
├── PLAN.md                     # 实施计划
├── architecture.md             # 系统架构
└── api_index.md                # API 索引
```

## 快速开始

### 环境要求

- Python 3.10+
- Docker 与 Docker Compose（仅用于 MySQL）
- Android Studio (Ladybug+)
- JDK 11+

### 1. 启动 MySQL

```bash
# 在项目根目录执行
cp .env.example .env
# 编辑 .env：填入 ARK_API_KEY；MYSQL_PASSWORD 默认 ecommerce123 即可
# HF_ENDPOINT 默认使用 hf-mirror.com 下载 embedding 模型；首次 ingest 前请保持 HF_HUB_OFFLINE=0

docker compose up -d
```

MySQL 映射到本机 `127.0.0.1:3306`，数据持久化在 Docker 卷 `mysql_data`。

```bash
# 查看 MySQL 状态
docker compose ps

# 停止（保留数据）
docker compose down

# 停止并清空数据库
docker compose down -v
```

若 `3306` 端口已被占用，在 `.env` 中设置 `MYSQL_PORT=3307`。

### 2. 启动后端

```bash
cd server
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 初始化 MySQL 商品权威源
python product_store.py

# 导入商品向量数据（首次会通过 HF_ENDPOINT 镜像下载 embedding 模型，可能较慢）
python ingest.py

# 可选：Demo 前手动执行一次 MySQL -> ChromaDB 增量同步
python chroma_sync.py

# 启动服务（启动时会自动把 ecommerce_agent_dataset/ 幂等加载到 MySQL，并每 3 分钟后台增量同步 ChromaDB）
uvicorn main:app --host 0.0.0.0 --port 8000
```

```bash
curl http://127.0.0.1:8000/health
```

### 检索评估

评估脚本位于 `eval/run_retrieval_eval.py`，默认走与线上一致的检索链路：`parse_intent` → `retrieve(query, top_k, intent)`。

**前置条件**：已执行 `python ingest.py` 导入向量库。

```bash
# 在项目根目录执行

# 带 LLM 意图解析（默认），报告写入 eval/reports/retrieval_eval_top5_with_intent.json
server/.venv/bin/python eval/run_retrieval_eval.py

# 快速抽样（前 10 条，避免全量 LLM 调用）
server/.venv/bin/python eval/run_retrieval_eval.py --limit 10

# 仅评估纯检索，不含意图解析（对比用）
server/.venv/bin/python eval/run_retrieval_eval.py --no-intent

# 指定 Top-K
server/.venv/bin/python eval/run_retrieval_eval.py --top-k 10

# 离线环境（embedding 模型已缓存时；或在 .env 中设置 HF_HUB_OFFLINE=1）
server/.venv/bin/python eval/run_retrieval_eval.py
```

**输出指标**：Recall@K、MRR、Hit Rate@K、Precision@K。完整报告含逐条 query 的命中详情及解析出的 `intent` 字段。

### Android 客户端

1. 用 Android Studio 打开 `client-android/` 目录
2. 修改 API 地址指向后端服务
3. 运行到模拟器或真机

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 后端框架 | FastAPI |
| 商品权威源 | MySQL + SQLAlchemy Core + PyMySQL |
| 向量数据库 | ChromaDB |
| 索引同步 | FastAPI 后台任务 + MySQL `sync_state` |
| Embedding | BAAI/bge-base-zh-v1.5 |
| LLM | Doubao-Seed-2.0-lite |
| 流式传输 | SSE |
| Android | Kotlin / Jetpack Compose / Material3 |

## 文档

- [实施计划](PLAN.md)
- [系统架构](architecture.md)
- [API 索引](api_index.md)
- [需求文档](Task.md)

## Cart Demo Flow

1. Start the FastAPI backend on port `8000`.
2. Build and run the Android debug app.
3. Ask for product recommendations, then tap the cart button on a product card.
4. Use the cart icon or bottom summary strip to open the cart sheet.
5. Increase, decrease, remove, or clear cart items from the sheet.
6. Try natural-language operations such as `把第一款加入购物车`, `购物车里有什么`, `把购物车第一个商品数量改成2`, and `删除购物车第一个商品`.

## Cart End-to-End Validation

With the backend running:

```powershell
python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000
```

If LLM access is blocked but the backend is running, validate the deterministic HTTP cart path:

```powershell
python eval/run_cart_e2e.py --base-url http://127.0.0.1:8000 --http-only
```
