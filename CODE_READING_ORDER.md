# DeerFlow 代码阅读顺序

这是一条面向新人的项目代码主线。建议从上到下阅读；每一节先看入口文件，再沿着“谁调用谁”继续深入。文中的链接均指向仓库内的代码或文档。

## 代码总览

先用这张图建立项目边界：

```text
浏览器 / 外部 IM
        │
        ▼
Nginx（统一入口）
        │
        ▼
Gateway API（FastAPI）
        │
        ▼
Harness Client / Lead Agent（LangGraph）
        │
        ├── Middleware
        ├── Tools / MCP / Skills
        ├── Sandbox
        ├── Subagents
        └── Persistence / Memory
        │
        ▼
SSE / API 响应 → Frontend 工作区
```

## 1. 根目录：先看服务如何拼起来

阅读目标：知道 DeerFlow 不是一个单独的 Python 服务，而是由 Gateway、Harness、Frontend、Nginx 和可选 Provisioner 组成的全栈系统。

1. [根目录 AGENTS.md](AGENTS.md)：了解项目定位、服务拓扑、目录职责和模块阅读入口。
2. [README.md](README.md)：快速确认用户看到的能力，以及“配置 → 启动 → 对话”的整体行为。
3. [根 Makefile](Makefile)：追踪 `make dev`、`make start`、`make up` 等命令最终启动哪些服务。
4. [开发环境 compose 文件](docker/docker-compose-dev.yaml)：查看本地开发时 Gateway、Frontend、Nginx 的连接方式。
5. [生产 compose 文件](docker/docker-compose.yaml)：对照开发环境，理解生产容器和服务边界。
6. [Nginx 配置](docker/nginx/nginx.conf)：确认浏览器请求如何转发到 Frontend 和 Gateway。

读完这一节，应能回答：浏览器访问哪个入口？`/api` 请求去哪？Agent 代码和 Web API 为什么分在两个 backend 层次？

## 2. Backend 分层：先理解 Harness / App 边界

阅读目标：明确“通用 Agent 框架”和“DeerFlow 应用接入层”的依赖方向。

1. [Backend AGENTS.md](backend/AGENTS.md) 的 [Harness / App Split](backend/AGENTS.md#harness--app-split) 小节：这是后端最重要的边界说明。
2. [Harness 包](backend/packages/harness/deerflow/__init__.py)：从包入口认识可复用的 Agent 运行时。
3. [App 包](backend/app/__init__.py)：认识 Gateway、IM Channel、Scheduler 等 DeerFlow 应用层代码。
4. [Backend pyproject.toml](backend/pyproject.toml)：查看两个层次共享的依赖、入口和测试配置。
5. [Backend Makefile](backend/Makefile)：了解后端开发、测试、格式化命令。

阅读时始终遵守一个方向：`app → harness` 可以，`harness → app` 不可以。这样后面阅读 Agent 时不会把 Gateway 的业务代码误认为 Harness 的一部分。

## 3. Gateway 启动：从 HTTP 请求进入系统

阅读目标：知道 FastAPI 如何创建应用、挂载路由、准备运行时单例，以及一次 run 如何被启动。

1. [Gateway 应用入口](backend/app/gateway/app.py)：从 FastAPI app、生命周期和路由注册开始。
2. [Gateway 依赖注入](backend/app/gateway/deps.py)：查看 checkpointer、run manager、stream bridge、模型 provider 等运行时对象如何取得。
3. [Gateway 服务层](backend/app/gateway/services.py)：重点阅读输入规范化、run 配置构造、后台任务启动和流式输出。
4. [Agent 路由](backend/app/gateway/routers/agents.py)：了解 Agent 列表和 Agent 配置如何暴露给客户端。
5. [Run 路由](backend/app/gateway/routers/runs.py)：跟踪创建 run、读取 run 状态和消费结果的 HTTP 边界。
6. [Thread 路由](backend/app/gateway/routers/threads.py)：理解会话线程、消息历史和 LangGraph thread_id 的关系。
7. [Thread Run 路由](backend/app/gateway/routers/thread_runs.py)：查看以 thread 为中心的运行接口。

推荐的调用追踪顺序是：`routers/runs.py` → `services.py` → `deps.py` → Harness Client。不要一开始逐个阅读所有 Router；它们大多是围绕同一组服务的薄适配层。

## 4. Harness Client：Gateway 如何调用 Agent

阅读目标：理解 App 层如何把 HTTP 请求转换为 Harness 层可以执行的 LangGraph run。

1. [Embedded Client](backend/packages/harness/deerflow/client.py)：查看 Gateway 使用的 Harness 客户端接口。
2. [Agent 目录](backend/packages/harness/deerflow/agents)：浏览 lead agent、middleware、memory 等 Agent 组成部分。
3. [Agent 工厂与构建入口](backend/packages/harness/deerflow/agents/factory.py)：沿着 Agent 创建过程继续阅读（如果目录结构变化，以该目录下的实际工厂文件为准）。
4. [运行时目录](backend/packages/harness/deerflow/runtime)：查看执行上下文、运行状态和事件相关抽象。
5. [持久化目录](backend/packages/harness/deerflow/persistence)：理解 checkpoint、run event 和线程状态的保存位置。

这一节的核心问题是：Gateway 传入的 `thread_id`、`assistant_id`、`context` 和 `stream_mode`，最终如何进入 Agent 的运行配置，并影响一次 LangGraph 执行。

## 5. Lead Agent：阅读一次对话真正执行的主链路

阅读目标：理解模型、消息状态、工具调用和 middleware 如何组成“超级 Agent”。

1. [Lead Agent 相关代码](backend/packages/harness/deerflow/agents)：先浏览目录，再定位 lead agent 的构建文件。
2. [Agent Middleware](backend/packages/harness/deerflow/agents/middlewares)：按注册顺序阅读 middleware；它们负责上下文、摘要、工具限制、循环检测、记忆和安全终止等横切行为。
3. [配置目录](backend/packages/harness/deerflow/config)：查看 Agent 创建时读取的模型、工具、上下文、摘要和预算配置。
4. [模型工厂](backend/packages/harness/deerflow/models/factory.py)：了解模型 provider 如何按配置实例化。
5. [模型 provider 实现](backend/packages/harness/deerflow/models)：需要追踪具体 provider 时，再从工厂跳到对应实现。
6. [消息与 Agent 工具类型](backend/packages/harness/deerflow/tools/types.py)：理解模型输出的 tool call 如何被转成工具执行请求。

建议重点观察这条循环：

```text
用户消息 → Agent 状态 → 模型调用 → AIMessage/tool_calls
       ↑                         ↓
       └── ToolMessage ← 工具执行
```

先搞清这条循环，再看每个 middleware 的细节；否则容易把 middleware 当成独立功能，而忽略它们都在改变同一次 Agent run 的状态或事件。

## 6. Tools、Sandbox、MCP、Skills：Agent 如何获得能力

阅读目标：理解“模型能做什么”不是写死在 Agent 节点里，而是由工具注册、沙箱、MCP 和 Skills 共同决定。

### 6.1 工具注册与内置工具

1. [工具总入口](backend/packages/harness/deerflow/tools/tools.py)：查看工具集合如何构建。
2. [工具类型定义](backend/packages/harness/deerflow/tools/types.py)：理解工具名称、参数和运行上下文。
3. [内置工具目录](backend/packages/harness/deerflow/tools/builtins)：从 `task`、`setup_agent`、`tool_search`、`present_file` 等工具入手。
4. [通用工具同步逻辑](backend/packages/harness/deerflow/tools/sync.py)：查看工具配置变化如何同步到运行时。

### 6.2 Sandbox：工具在哪里执行

1. [Sandbox 目录](backend/packages/harness/deerflow/sandbox)：先看统一接口，再看具体 provider。
2. [Sandbox 相关说明](backend/AGENTS.md#sandbox-system-packagesharnessdeerflowsandbox)：了解 workspace、容器和 provisioner 的边界。
3. [Provisioner 服务](docker/provisioner/app.py)：需要理解 Kubernetes / provisioner 模式时再进入这里。

### 6.3 MCP：外部工具如何接入

1. [MCP 客户端](backend/packages/harness/deerflow/mcp/client.py)：查看单个 MCP server 的连接与调用。
2. [MCP 会话池](backend/packages/harness/deerflow/mcp/session_pool.py)：理解连接复用和生命周期。
3. [MCP 工具适配](backend/packages/harness/deerflow/mcp/tools.py)：查看 MCP tools 如何转换成 Agent tools。
4. [MCP Router](backend/app/gateway/routers/mcp.py)：追踪 Web 配置接口。
5. [MCP 示例配置](extensions_config.example.json)：查看外部配置如何声明 MCP server。

### 6.4 Skills：可组合的提示词与工具说明

1. [Skills 运行时代码](backend/packages/harness/deerflow/skills)：了解 Skill 的加载、扫描和激活。
2. [公共 Skills](skills/public)：查看项目自带 Skill 的实际目录结构。
3. [Skill 配置](backend/packages/harness/deerflow/config/skills_config.py)：追踪 Skills 是否启用以及加载策略。
4. [Skills Router](backend/app/gateway/routers/skills.py)：了解前端如何读取和管理 Skills。

## 7. Subagent：主 Agent 如何委派任务

阅读目标：理解 lead agent 和子 Agent 的边界，以及委派任务如何回到主运行流。

1. [Subagent 配置](backend/packages/harness/deerflow/subagents/config.py)：查看子 Agent 的运行参数。
2. [Subagent 注册表](backend/packages/harness/deerflow/subagents/registry.py)：了解可用子 Agent 如何登记。
3. [Subagent 执行器](backend/packages/harness/deerflow/subagents/executor.py)：追踪委派、执行、状态和结果收集。
4. [内置通用子 Agent](backend/packages/harness/deerflow/subagents/builtins/general_purpose.py)：看一个典型的子 Agent。
5. [内置 Bash Agent](backend/packages/harness/deerflow/subagents/builtins/bash_agent.py)：对比具有更明确工具边界的子 Agent。
6. [Task 工具](backend/packages/harness/deerflow/tools/builtins/task_tool.py)：从主 Agent 的工具调用入口回看委派过程。

## 8. Memory、Persistence、Reflection：状态如何跨请求保留

阅读目标：区分短期对话状态、长期记忆、运行事件和 checkpoint，不把它们混为一个“数据库层”。

1. [Memory Middleware](backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py)：先看记忆何时进入 Agent 上下文。
2. [Memory 系统](backend/packages/harness/deerflow/agents/memory)：查看记忆抽取、读取、更新和 backend 接口。
3. [Persistence 系统](backend/packages/harness/deerflow/persistence)：理解 LangGraph 状态和运行记录如何保存。
4. [Reflection 系统](backend/packages/harness/deerflow/reflection)：查看对话后的总结、反思或状态更新。
5. [Memory Router](backend/app/gateway/routers/memory.py)：从 HTTP 入口回看记忆管理。
6. [数据库迁移](backend/packages/harness/deerflow/persistence/migrations)：当需要理解表结构或历史兼容时阅读。

## 9. Frontend：从页面进入 API 和流式消息

阅读目标：理解浏览器如何创建 thread、发起 run、消费 SSE，再把 Agent 事件渲染成聊天界面。

1. [Frontend AGENTS.md](frontend/AGENTS.md)：先看 App Router、目录职责和数据流说明。
2. [Frontend 页面目录](frontend/src/app)：定位工作区、聊天页和 scheduled task 页面。
3. [Workspace 组件](frontend/src/components/workspace)：理解工作区布局、输入框、消息列表和侧边栏。
4. [Workspace 消息组件](frontend/src/components/workspace/messages)：查看文本、工具调用、子任务、计划和附件如何渲染。
5. [API Client](frontend/src/core/api/api-client.ts)：追踪前端请求如何进入 Gateway。
6. [API Fetcher](frontend/src/core/api/fetcher.ts)：查看认证、错误处理和请求封装。
7. [Stream Mode](frontend/src/core/api/stream-mode.ts)：理解 `values`、`messages-tuple` 等流模式。
8. [Agent API](frontend/src/core/agents/api.ts)：查看 Agent 列表和配置请求。
9. [Agent Hooks](frontend/src/core/agents/hooks.ts)：理解 React 组件如何读取 Agent 数据。
10. [输入框](frontend/src/components/workspace/input-box.tsx)：从用户提交消息回到 run 创建请求。
11. [消息列表](frontend/src/components/workspace/messages/message-list.tsx)：从流式事件进入最终 UI 的落点开始回溯。

推荐的前端调用追踪顺序是：页面 → `workspace-container` → `input-box` → `core/api` → Gateway run API；反向追踪响应时则从 `stream-mode` → 消息状态 → `message-list`。

## 10. IM Channels 与 Scheduler：非浏览器入口

阅读目标：了解 Web 之外的消息和定时任务如何复用同一套 Agent 运行生命周期。

1. [Channel 基类](backend/app/channels/base.py)：查看不同 IM 平台共享的接口。
2. [Channel 服务](backend/app/channels/service.py)：理解消息接收、路由和回复发送的公共流程。
3. [Channel Manager](backend/app/channels/manager.py)：查看平台连接的生命周期管理。
4. [Channel Message Bus](backend/app/channels/message_bus.py)：追踪平台消息如何进入应用内部。
5. [具体 Channel 实现](backend/app/channels)：需要理解某个平台时，再打开 `feishu`、`slack`、`telegram`、`discord`、`dingtalk`、`wechat` 或 `wecom`。
6. [Scheduler 服务](backend/app/scheduler/service.py)：查看定时任务如何创建并启动非交互式 Agent run。
7. [Scheduled Task Router](backend/app/gateway/routers/scheduled_tasks.py)：追踪定时任务的 API 管理接口。
8. [Scheduled Task 前端核心代码](frontend/src/core/scheduled-tasks)：查看任务编辑、cron 和 API 状态管理。

这里最值得注意的是复用关系：Channel 和 Scheduler 是不同入口，但最终都要经过 Gateway / Harness 的 run 生命周期，而不是各自实现一套 Agent。

## 11. 用测试反向确认理解

阅读目标：用测试验证你对边界和调用关系的理解，而不是只停留在文件浏览。

1. [Backend 测试](backend/tests)：优先搜索 `gateway`、`agent`、`middleware`、`sandbox`、`subagents` 和 `persistence`。
2. [Frontend 测试](frontend/tests)：优先搜索 API client、stream、workspace 和消息渲染。
3. [根目录 Skills 测试](tests/skills)：理解公共 Skill 的约定和可验证行为。
4. [Harness 边界测试](backend/tests): 搜索 `harness_boundary`，确认 App 与 Harness 的依赖方向。
5. [Backend 开发规范](backend/AGENTS.md#test-driven-development-tdd--mandatory)：结合测试命令和测试目录继续阅读。

每当你读完一个子系统，可以问自己三个问题：它的入口是什么？它依赖谁？它把结果交给谁？能在测试中找到对应断言时，说明这条代码链路已经基本读通。

## 一条最短主线

如果只想先读通一次普通对话，按下面顺序打开文件：

1. [根 Makefile](Makefile)
2. [开发 compose](docker/docker-compose-dev.yaml)
3. [Nginx 配置](docker/nginx/nginx.conf)
4. [Gateway app](backend/app/gateway/app.py)
5. [Run Router](backend/app/gateway/routers/runs.py)
6. [Gateway services](backend/app/gateway/services.py)
7. [Embedded Client](backend/packages/harness/deerflow/client.py)
8. [Agent 目录](backend/packages/harness/deerflow/agents)
9. [Middleware 目录](backend/packages/harness/deerflow/agents/middlewares)
10. [工具注册](backend/packages/harness/deerflow/tools/tools.py)
11. [Frontend API Client](frontend/src/core/api/api-client.ts)
12. [Frontend Stream Mode](frontend/src/core/api/stream-mode.ts)
13. [Workspace Input](frontend/src/components/workspace/input-box.tsx)
14. [Workspace Message List](frontend/src/components/workspace/messages/message-list.tsx)

这条短线读完后，再根据兴趣进入 Tools、Sandbox、MCP、Skills、Subagent、Memory、IM 或 Scheduler 专题。
