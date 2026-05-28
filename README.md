# EcommerceAgent — 电商智能导购 AI Agent

基于 RAG 技术的多模态电商智能导购助手，通过自然语言对话帮助用户发现和选购商品。

## 项目结构

```
├── server/                     # Python 后端
│   ├── main.py                 # FastAPI 入口
│   ├── config.py               # 配置管理
│   ├── ingest.py               # 数据导入 & 向量化
│   ├── retriever.py            # RAG 检索模块
│   ├── generator.py            # LLM 对话生成
│   ├── schemas.py              # 数据模型
│   └── requirements.txt        # Python 依赖
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

### Android 客户端

1. 用 Android Studio 打开 `client-android/` 目录
2. 修改 API 地址指向后端服务
3. 运行到模拟器或真机

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| 后端框架 | FastAPI |
| 向量数据库 | ChromaDB |
| Embedding | text2vec-base-chinese |
| LLM | Doubao-Seed-2.0-lite |
| 流式传输 | SSE |
| Android | Kotlin / Jetpack Compose / Material3 |

## 文档

- [实施计划](PLAN.md)
- [系统架构](architecture.md)
- [API 索引](api_index.md)
- [需求文档](Task.md)
