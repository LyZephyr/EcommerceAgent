# 系统架构

## 整体架构

```
┌─────────────────┐         SSE          ┌──────────────────────────────────┐
│  Android Client │ ◄──────────────────► │         FastAPI Server           │
│  (Kotlin/Compose)│   POST /api/chat    │                                  │
└─────────────────┘                      │  ┌──────────┐   ┌────────────┐  │
                                         │  │ Retriever │──►│  ChromaDB  │  │
                                         │  └────┬─────┘   └────────────┘  │
                                         │       │                         │
                                         │       ▼                         │
                                         │  ┌──────────┐   ┌────────────┐  │
                                         │  │ Generator │──►│ Doubao API │  │
                                         │  └──────────┘   └────────────┘  │
                                         └──────────────────────────────────┘
```

## 模块职责

### server/config.py
- 从 `.env` 加载环境变量
- 导出全局配置常量（API Key、模型端点、ChromaDB 路径等）

### server/ingest.py
- 扫描 `ecommerce_agent_dataset/` 下所有类目目录
- 解析商品 JSON 文件
- 将商品信息拼接为文本 document
- 调用 Embedding 模型向量化
- 写入 ChromaDB（包含元数据）

### server/embedding.py
- 统一创建 ChromaDB embedding function
- 使用 `shibing624/text2vec-base-chinese`

### server/retriever.py
- 加载 ChromaDB collection
- 接收用户 query，生成 query embedding
- 执行相似度检索、查询扩展与轻量重排，返回 Top-K 商品信息

### server/generator.py
- 构造 System Prompt + User Prompt（含检索上下文）
- 调用 Doubao API（OpenAI 兼容接口，stream=True）
- 逐 token yield 生成结果

### server/schemas.py
- 定义 `ChatRequest`（用户输入）
- 定义 `Product`（商品卡片数据）

### server/main.py
- FastAPI 应用入口
- CORS 中间件配置
- 挂载 `/assets` 静态资源路径，用于返回商品图片
- `POST /api/chat` SSE 端点：串联 retriever → generator → SSE 输出

### client-android/
- **data/model/**: `Message`、`Product` 数据类
- **data/api/**: OkHttp SSE 客户端封装
- **viewmodel/**: `ChatViewModel`，管理对话状态
- **ui/chat/**: `ChatScreen`、`MessageBubble`、`ProductCard` Compose 组件

## 数据流

```
用户输入文字
    │
    ▼
Android Client ── POST {"message": "推荐一款手机"} ──► FastAPI
    │                                                      │
    │                                              1. query embedding
    │                                              2. ChromaDB 检索 Top-5 并重排
    │                                              3. 组装 prompt + context
    │                                              4. 调用 Doubao API (stream)
    │                                                      │
    ◄─── SSE event: product (商品卡片 JSON) ───────────────┤
    ◄─── SSE event: token ("这款") ────────────────────────┤
    ◄─── SSE event: token ("手机") ────────────────────────┤
    ◄─── SSE event: token ("非常") ────────────────────────┤
    ◄─── ...                                               │
    ◄─── SSE event: done ──────────────────────────────────┘
    │
    ▼
渲染消息气泡 + 商品卡片
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 后端框架 | Python 3.10+ / FastAPI |
| 向量数据库 | ChromaDB（嵌入式） |
| Embedding | shibing624/text2vec-base-chinese |
| LLM | Doubao-Seed-2.0-lite（Ark API） |
| 流式传输 | SSE (Server-Sent Events) |
| Android UI | Kotlin / Jetpack Compose / Material3 |
| Android 网络 | OkHttp + EventSource |
