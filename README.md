# EcommerceAgent — 电商智能导购 AI Agent

基于 RAG 技术的多模态电商智能导购助手，通过自然语言对话帮助用户发现和选购商品。

## 项目结构

```
├── server/                     # Python 后端
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── ingest.py               # 数据导入 & 向量化
│   ├── retriever.py            # RAG 检索模块
│   ├── intent.py               # LLM 意图解析
│   ├── generator.py            # LLM 对话生成
│   ├── schemas.py              # 数据模型
│   └── requirements.txt        # Python 依赖
├── eval/                       # 离线检索评估
│   ├── ground_truth.json       # 评估 query 与标注
│   ├── run_retrieval_eval.py   # 评估脚本
│   └── reports/                # 评估报告输出
├── client-android/             # Android 客户端 (Kotlin/Compose)
├── ecommerce_agent_dataset/    # 商品数据集 (4 类目 × 25 条)
├── PLAN.md                     # 实施计划
├── architecture.md             # 系统架构
└── api_index.md                # API 索引
```

## 快速开始

### 环境要求

- Python 3.10+
- Android Studio (Ladybug+)
- JDK 11+

### 后端启动

```bash
# 1. 创建虚拟环境
cd server
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp ../.env.example ../.env
# 编辑 .env 填入 ARK_API_KEY

# 4. 导入商品数据
python ingest.py

# 5. 启动服务
uvicorn main:app --host 0.0.0.0 --port 8000
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

# 离线环境（embedding 模型已缓存时）
HF_HUB_OFFLINE=1 server/.venv/bin/python eval/run_retrieval_eval.py
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
| 向量数据库 | ChromaDB |
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
