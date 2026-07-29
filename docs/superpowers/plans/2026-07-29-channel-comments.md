# IM 通道中文注释补全实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `backend/app/channels/` 全部 Python 文件补充准确的中文 docstring 和复杂逻辑注释，不改变运行行为。

**Architecture:** 按共享基础设施、调度器、平台适配器三个边界顺序处理。每个文件先识别缺失或低价值注释，再仅补充职责、约束和设计原因；每个任务结束后运行静态检查及相关测试。

**Tech Stack:** Python 3.12、FastAPI、asyncio、langgraph-sdk、ruff、pytest

## Global Constraints

- 所有新增或改写的代码注释使用中文。
- Python 主要使用 docstring；复杂语句使用独立行内注释。
- 不复述代码，不修改运行逻辑，不重命名符号。
- 标识符、API 名称、协议字段、事件名、命令、路径和必须精确匹配的文本保持原文。
- 所有工作在当前 Git 分支完成，不创建新分支或 worktree。

---

### Task 1: 共享消息与存储基础设施

**Files:**
- Modify: `backend/app/channels/__init__.py`
- Modify: `backend/app/channels/base.py`
- Modify: `backend/app/channels/commands.py`
- Modify: `backend/app/channels/connection_identity.py`
- Modify: `backend/app/channels/message_bus.py`
- Modify: `backend/app/channels/run_policy.py`
- Modify: `backend/app/channels/runtime_config_store.py`
- Modify: `backend/app/channels/store.py`

**Interfaces:**
- Consumes: 现有 `InboundMessage`、`OutboundMessage`、`Channel`、`ChannelStore` 与策略注册接口。
- Produces: 仅产生中文说明，不改变任何接口签名或运行语义。

- [ ] **Step 1: 审计缺失说明**

使用 AST 与人工阅读识别无 docstring 的模块、类、方法和函数，并标记涉及身份绑定、持久化键、队列生命周期和策略默认值的复杂逻辑。

- [ ] **Step 2: 补充中文 docstring 与必要行内注释**

每条说明必须至少回答职责、边界或设计原因之一；类似下面的注释不得出现：

```python
# 获取线程 ID
thread_id = get_thread_id(...)
```

应说明映射键或回退规则，例如：

```python
# topic_id 缺失时退化为会话级键，使私聊中的连续消息复用同一条 DeerFlow 线程。
```

- [ ] **Step 3: 运行静态检查**

Run: `cd backend && uvx ruff check app/channels`

Expected: PASS，无新增 lint 错误。

- [ ] **Step 4: 运行基础通道测试**

Run: `cd backend && uv run pytest tests/test_channels.py -q`

Expected: PASS。

### Task 2: ChannelManager 调度与流式边界

**Files:**
- Modify: `backend/app/channels/manager.py`
- Modify: `backend/app/channels/service.py`

**Interfaces:**
- Consumes: Task 1 中保持不变的消息、存储和策略接口。
- Produces: 对线程映射、并发锁、SSE 累积、附件归属和身份复核约束的中文说明。

- [ ] **Step 1: 审计复杂状态路径**

重点检查线程创建锁、同线程运行锁、入站去重、`runs.wait`/`runs.stream` 分流、`messages-tuple` 文本累积、附件归属与错误恢复。

- [ ] **Step 2: 补充中文 docstring**

为缺失说明的函数和方法补充职责与关键不变量，避免逐项复述参数。

- [ ] **Step 3: 补充复杂逻辑注释**

只解释锁粒度、事件命名差异、增量与累计文本合并、所有者隔离及回退路径的原因。

- [ ] **Step 4: 运行调度器测试**

Run: `cd backend && uv run pytest tests/test_channels.py -q`

Expected: PASS。

### Task 3: 平台适配器

**Files:**
- Modify: `backend/app/channels/dingtalk.py`
- Modify: `backend/app/channels/discord.py`
- Modify: `backend/app/channels/feishu.py`
- Modify: `backend/app/channels/feishu_run_policy.py`
- Modify: `backend/app/channels/github.py`
- Modify: `backend/app/channels/slack.py`
- Modify: `backend/app/channels/telegram.py`
- Modify: `backend/app/channels/wechat.py`
- Modify: `backend/app/channels/wecom.py`

**Interfaces:**
- Consumes: Task 1 与 Task 2 保持不变的 Channel、MessageBus 和 ChannelManager 契约。
- Produces: 对平台消息 ID、话题映射、卡片更新、重试、文件下载和线程边界的中文说明。

- [ ] **Step 1: 逐平台审计**

识别每个平台与通用 Channel 契约之间的转换点，以及 SDK 线程模型、回调线程、消息编辑和文件下载中的非直观约束。

- [ ] **Step 2: 补充中文 docstring/JSDoc 等价说明**

Python 文件统一使用 docstring；已有准确英文说明按上下文翻译，不改动外部协议字面量。

- [ ] **Step 3: 补充平台特有复杂逻辑注释**

重点覆盖飞书卡片映射与同线程队列、Telegram 原地编辑、Slack Socket Mode 线程键、钉钉流式卡片、微信/企业微信媒体处理。

- [ ] **Step 4: 运行平台测试**

Run: `cd backend && uv run pytest tests/test_channels.py tests/test_dingtalk_channel.py tests/test_github_channel.py -q`

Expected: PASS。

### Task 4: 批次总体验证

**Files:**
- Verify: `backend/app/channels/*.py`
- Verify: `backend/AGENTS.md`
- Verify: `README.md`

**Interfaces:**
- Consumes: Tasks 1–3 的纯注释变更。
- Produces: 可证明无行为变更且注释质量符合设计的第一批结果。

- [ ] **Step 1: 检查差异性质**

Run: `git diff --word-diff=porcelain -- backend/app/channels`

Expected: 差异仅包含注释、docstring 与其必要格式调整。

- [ ] **Step 2: 检查格式**

Run: `cd backend && uvx ruff format --check app/channels`

Expected: PASS。

- [ ] **Step 3: 运行批次测试**

Run: `cd backend && uv run pytest tests/test_channels.py tests/test_dingtalk_channel.py tests/test_github_channel.py -q`

Expected: PASS。

- [ ] **Step 4: 审阅文档同步需求**

纯注释变更不改变用户行为或架构；若审阅确认无行为变化，则不修改 `README.md` 或 `backend/AGENTS.md`，并在批次记录中注明原因。
