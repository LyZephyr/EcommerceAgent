# 项目规范

## 项目概述

基于 RAG 的多模态电商智能导购 AI Agent。后端 Python/FastAPI，客户端 Android Kotlin/Compose。

## 关键文件

- `PLAN.md` — 当前实施计划和后续方向
- `architecture.md` — 系统架构、模块职责、数据流
- `api_index.md` — API 接口与模块函数索引
- `Task.md` — 原始需求文档（只读，不修改）

## 开发环境

- 客户端在 Windows 环境下使用 Android Studio 进行开发，其余部分在 Linux (WSL) 中进行开发

## 执行规则

- 如果依赖、网络、运行环境、权限或外部服务等问题导致原定方案无法完整落实，必须立即终止当前任务并向用户说明阻塞原因。
- 不得在未获得用户明确同意的情况下编写后备方案、降级实现、兼容分支或替代设计。
- 需要用户决策时，应说明原方案缺失的条件、已经验证过的事实，以及继续推进所需的具体动作。

## 当前项目进展

**MVP 核心链路已打通**，详见 `PLAN.md` 第一节「当前系统状态」。

### 已完成

- 单跳工具调用 Agent（`retrieve_products` 替代固定 RAG 流水线）
- RAG 检索：bge-base-zh-v1.5 embedding、metadata filter、must/exclude 加权重排
- 多轮对话上下文（内存存储，滑动窗口 10 轮）
- SSE 流式传输 + Android 聊天界面（商品卡片、流式文本）
- 离线检索评估体系（250 条 ground truth + `eval/run_retrieval_eval.py`）
- 后端能力扩展：`requests[]` 多子需求检索、`<C>` 结构化对比事件（SSE `compare`）

### 进行中（`PLAN.md` 第二节）

1. **Agent 行为验证与调优**：路由决策、检索质量、prompt/工具描述调优
2. **客户端对比表 UI**：消费后端 `compare` 事件，渲染结构化对比表格
3. **文档与 Demo**：README、技术文档、演示脚本

### 待后续推进（加分项）

- 购物车闭环、拍照找货/多模态、工程优化（语义缓存、首屏加速等）
