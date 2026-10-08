# DeerFlow 2.0.0 学习版

这是基于 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) **2.0.0** 整理的简化项目，目标是让学习者看清一条完整链路：用户发出问题，后端运行代理，模型调用工具，结果流式显示在页面上。

本项目是在原代码上删减、调整并修复的学习分支，不是上游 2.0.0 的逐字副本，也不保证与其全部配置兼容。前后端版本号中的 `learning` 用来区分本学习版；第三方依赖的版本不代表 DeerFlow 的来源版本。

## 原项目与学习版

DeerFlow 2.0.0 原项目包含网页应用、主代理与子代理、技能和工具、沙箱、上下文压缩、长期记忆，以及多种模型服务、部署与集成方式。它不是只用于联网搜索的聊天程序，而是让模型通过工具处理文件、执行任务和生成产物的代理应用。

| 部分 | 学习版保留或简化的内容 | 代码入口 |
| --- | --- | --- |
| 网页界面 | 根路径直接进入登录页，保留聊天、附件、代理管理及设置；不恢复宣传首页或静态演示模式 | [页面](frontend/src/app)、[组件](frontend/src/components) |
| 主代理与中间件 | 模型选择、上下文准备、工具调用、运行边界和流式执行 | [代理](backend/deerflow/agents)、[运行时](backend/deerflow/runtime) |
| 子代理 | 保留任务委派与后台执行，不是每次聊天都会启动子代理 | [子代理](backend/deerflow/subagents) |
| 技能与工具 | 保留技能加载、存储、审查与代码工具；移除了此前选定的技能评测资源 | [技能资源](skills/public)、[技能实现](backend/deerflow/skills)、[工具](backend/deerflow/tools) |
| 沙箱与附件 | 默认使用后端进程所在环境的本地沙箱；保留线程目录隔离、文档转 Markdown 和图片输入 | [沙箱](backend/deerflow/sandbox)、[附件接口](backend/app/gateway/routers/conversations)、[转换工具](backend/deerflow/utils) |
| 数据存储 | 应用数据、运行记录和对话检查点使用 PostgreSQL；流式事件桥接使用外部 Redis | [应用持久化](backend/deerflow/persistence)、[检查点](backend/deerflow/runtime/checkpointer)、[流桥接](backend/deerflow/runtime/stream_bridge) |
| 长期记忆 | 保留用户画像、历史摘要和独立事实；与对话检查点分开存储 | [记忆](backend/deerflow/agents/memory) |
| 调用追踪 | 保留 Langfuse 和 LangSmith，按环境配置开启 | [追踪](backend/deerflow/tracing) |
| 扩展业务 | 保留定时任务、外部消息渠道、工具服务连接和鉴权，不因默认关闭而删除业务代码 | [定时任务](backend/app/scheduler)、[消息渠道](backend/app/channels)、[工具服务](backend/deerflow/mcp)、[鉴权](backend/app/gateway/auth) |
| 部署 | 只维护 `make docker-start` 这一种启动方式，不提供本机多进程或热重载部署流程 | [部署](docker)、[启动脚本](scripts) |

“未启用”不等于“代码不存在”。例如，`community` 中仍有可按配置选用的搜索或沙箱适配器，网页文档和博客也仍保留；它们不是当前默认启动链路。学习版没有宣称删掉所有扩展能力。

## 总体结构

前端使用 React 和 Next.js；后端使用 FastAPI 提供接口，LangGraph 编排代理执行，LangChain 连接模型和工具。Nginx 将页面与后端接口统一到同一个访问地址。

```text
浏览器 → Nginx → 前端页面
              → 后端网关 → 主代理 → 模型与工具
                           ├─ PostgreSQL：持久数据与检查点
                           ├─ Redis：流式事件缓冲与转发
                           └─ 后端数据目录：附件、产物与长期记忆
```

| 目录 | 看什么 |
| --- | --- |
| [frontend/src/app](frontend/src/app) | 页面路由、登录与聊天入口 |
| [frontend/src/core](frontend/src/core) | 请求、流式消息、设置、通知等前端业务逻辑 |
| [frontend/src/components](frontend/src/components) | 可复用界面组件 |
| [backend/app/gateway](backend/app/gateway) | 接口、认证、请求处理与运行入口 |
| [backend/deerflow](backend/deerflow) | 代理、工具、沙箱、记忆和持久化核心 |
| [backend/deerflow/config](backend/deerflow/config) | 每个配置字段的类型及默认值 |
| [skills/public](skills/public) | 给模型使用的技能说明和资源，不等同于工具函数 |
| [docker](docker)、[scripts](scripts) | 镜像、反向代理和启动命令 |

## 启动

需要 Docker、Make 和外部 Redis。Windows 的启动脚本通过 Git Bash 执行，因此还需要安装 Git。首次构建会下载依赖，需要能够访问镜像和软件包源。

1. 将根目录 `.env.example` 复制为 `.env`，将 `config.example.yaml` 复制为 `config.yaml`。
2. 将 `extensions_config.example.json` 复制为 `extensions_config.json`，将 `frontend/.env.example` 复制为 `frontend/.env`。
3. 在 `.env` 中填写模型密钥、数据库密码和 Redis 地址；在 `config.yaml` 中填写自己有权限调用的模型及服务地址。数据库连接密码与容器初始化密码必须一致。
4. 启动 Redis。示例使用 `host.docker.internal:6379` 访问宿主机服务，服务必须允许后端容器连接；不要将无认证的 Redis 暴露到公网。
5. 在根目录执行：

```bash
make docker-start
```

访问 `http://localhost:2026`。没有管理员时按页面提示完成初始化，之后登录进入工作区。

查看日志使用 `make docker-logs`。日常暂停并保留容器时，在根目录执行：

```bash
docker compose --env-file .env -p deer-flow-dev -f docker/docker-compose-dev.yaml stop
```

**`make docker-stop` 当前执行的是删除服务容器，不是普通暂停。执行前必须备份后端文件；数据库卷保留并不代表附件和长期记忆也保留。**

示例配置默认开启文档转换和长期记忆，但关闭命令执行、定时任务和追踪服务。你已有的私有配置不会被本次整理覆盖。工具还会受技能白名单等策略限制，配置了工具不代表每次调用都会提供它。

## 数据与安全

- 当前部署只有 PostgreSQL 使用持久卷，前后端不挂载源码，不支持热重载。Redis 在部署之外单独维护。
- **上传文件、生成产物、文件型长期记忆及自动生成的登录签名密钥在后端容器内。删除或重建容器前必须备份；数据库持久化不会替你保存这些文件。** 配置变更需要重建时也应先处理数据保留。
- 本地沙箱不是独立虚拟机。路径检查能约束文件工具，但开启任意命令执行后，不应把它当作处理不可信代码的强隔离环境。
- Langfuse、LangSmith 默认关闭；开启后可能向相应平台上传模型输入、输出及工具内容。真实凭据只能放进私有 `.env`，不能放进前端或示例文件。
- 这是学习项目。公开部署前应额外处理传输加密、数据库密码、登录签名密钥、网络边界和备份。

## 建议阅读顺序

1. 从[聊天页面](frontend/src/app/workspace/chats/[thread_id]/page.tsx)看消息如何提交，再看[前端对话逻辑](frontend/src/core/threads)。
2. 从[网关接口](backend/app/gateway/routers/conversations)看请求如何创建运行，再看[运行执行器](backend/deerflow/runtime/runs/worker.py)。
3. 看[主代理](backend/deerflow/agents/lead_agent)如何装配模型、工具与中间件。
4. 结合一个具体工具，追踪[沙箱](backend/deerflow/sandbox)、[记忆](backend/deerflow/agents/memory)或[持久化](backend/deerflow/persistence)的调用链。

## 核心实现速读

### 一次对话如何运行

前端[对话逻辑](frontend/src/core/threads)提交消息，后端[会话接口](backend/app/gateway/routers/conversations)创建运行，再由[执行器](backend/deerflow/runtime/runs/worker.py)调用代理图。模型可以直接回答，也可以先请求工具、读取工具结果后再继续回答。一次对话可能包含多次模型调用，不是一个请求只调用一次模型。

执行器订阅三类事件：`messages` 是模型生成的消息增量，`values` 是状态快照，`custom` 是工具进度等自定义事件。当前网页链路通过 Redis 桥接事件，再经 SSE（Server-Sent Events，服务器发送事件）持续传给前端；刷新或断连后的恢复还依赖运行记录与检查点，而不是只靠浏览器保存消息。

### 中间件与工具

[主代理](backend/deerflow/agents/lead_agent/agent.py)根据配置装配[中间件](backend/deerflow/agents/middlewares)，分别在代理运行前后、模型调用前后或工具执行时处理目录准备、动态上下文、摘要、安全检查与记忆更新。它们不是独立聊天代理，具体启用项及顺序以装配代码为准。

模型收到的是工具名称、参数定义和用途说明；只有模型提出调用请求，后端才执行对应函数。技能里的 `allowed-tools`、代理工具组和运行模式会进一步筛选工具，规则见[技能工具策略](backend/deerflow/skills/tool_policy.py)。因此，技能说明、已配置工具与实际调用工具是三个不同概念。

### 登录与用户隔离

[认证模块](backend/app/gateway/auth)校验登录凭据，浏览器通过 Cookie 携带登录令牌。状态变更请求还要通过 CSRF（Cross-Site Request Forgery，跨站请求伪造）防护。后端将认证身份绑定到[请求级用户上下文](backend/deerflow/runtime/user_context.py)，供数据仓储与文件路径解析使用；不能靠客户端提交一个用户编号来取得别人的数据。

### 附件与图片

[上传接口](backend/app/gateway/routers/conversations/uploads.py)校验文件数量、大小和文件名，将附件保存到当前用户的线程目录。开启文档转换后，[转换模块](backend/deerflow/utils/file_conversion.py)为支持的办公文档生成 Markdown，模型可以使用文件工具读取。转换不保证完整保留文档排版或自动让模型看见文档里的所有图片。

独立上传的图片通过[图片中间件](backend/deerflow/agents/middlewares/view_image_middleware.py)附加到支持视觉的模型请求；模型使用[看图工具](backend/deerflow/tools/builtins/view_image_tool.py)时，则先校验文件并登记，再传入后续模型调用。传入图片数据与仅传文件路径并不等价。

### 检查点、上下文与长期记忆

[检查点](backend/deerflow/runtime/checkpointer)保存代理执行状态，用于继续会话和恢复运行；模型上下文是本次实际发送的消息，可由[摘要中间件](backend/deerflow/agents/middlewares/summarization_middleware.py)压缩。两者都不等于[长期记忆](backend/deerflow/agents/memory)：长期记忆从对话中提取用户画像、历史摘要和独立事实，供后续会话使用。

记忆更新不是每次都改写全部内容：模型提出更新方案，后端再按更新标记、可信度和维护规则决定保存哪些内容。当前文件型记忆与附件一样需要单独备份，不会因为 PostgreSQL 持久化而自动得到保护。

### 配置与调用追踪

项目配置由[配置加载器](backend/deerflow/config/app_config.py)读取。支持重载的字段可在后续读取时生效，但连接池、运行基础设施和创建时注入的环境变量不能假定会随文件修改即时更新；修改私有环境文件后，普通容器重启也不会刷新原先注入的环境变量。

[追踪工厂](backend/deerflow/tracing/factory.py)创建 Langfuse 或 LangSmith 回调，主代理将其放进运行配置的 `callbacks`。框架在模型、工具及代理执行时通知这些回调，由处理器上报追踪。普通函数不会因安装了追踪库就自动显示为独立节点。

后端详细文档已收敛到本说明，具体接口、字段和默认值直接查看对应源码；前端网页文档仍保留，旧版教程与本学习版有差异时以当前配置和实现为准。

维护源码时，前端函数说明使用 `/** 中文说明 */`，行注释使用 `// 中文说明`；后端说明字符串使用 `'''中文说明'''`，行注释使用 `# 中文说明`。配置和脚本使用各自语言支持的注释形式。保留 `Args:`、`Returns:`、`Raises:` 等结构标签，标签后的说明使用中文，避免破坏工具说明解析。代码标识、必要的检查指令和第三方许可证不强行翻译；模型提示词与接口响应字符串属于运行数据，不是源码注释。

## 来源与许可

感谢 [ByteDance DeerFlow](https://github.com/bytedance/deer-flow) 及其贡献者。本项目保留[原许可证](LICENSE)，以 MIT（Massachusetts Institute of Technology，麻省理工学院）许可证分发；简化整理不改变原作者署名与许可要求。
