# DeerFlow 本地配置与启动记录

日期：2026-08-28  
环境：Windows 11、Docker Desktop、Git Bash  
项目目录：`D:\Users\17396\Desktop\Learning\out\deer-flow`

## 目标

使用 VectorEngine 的 OpenAI 兼容接口完成 DeerFlow 本地配置，准备 Docker 开发环境，并验证前端、Gateway、模型配置与外部 API 的可用状态。

## 已执行的操作

### 1. 检查宿主机环境

确认以下工具和资源：

- Docker CLI 29.3.1 已安装。
- Docker Desktop 已安装，但检查开始时引擎未启动。
- Git Bash 已安装。
- Node.js 24.14.0，满足项目要求的 Node.js 22+。
- pnpm 11.19.0。
- uv 0.10.6。
- Python 3.12.13 可由 uv 使用。
- 16 个逻辑 CPU、约 15.3 GB 内存、D 盘约 490 GB 可用空间。
- 宿主机 PATH 中没有 GNU Make 和 nginx。

Docker 模式不依赖宿主机 nginx。由于宿主机没有 Make，本次通过仓库自带的 `scripts/run-with-git-bash.cmd` 和对应脚本直接执行等价操作。

### 2. 验证 VectorEngine API

配置的 Base URL：

```text
https://api.vectorengine.ai/v1
```

API Key 写入项目根目录 `.env` 的变量：

```text
VECTOR_ENGINE_API_KEY=sk-****（完整值仅保存在被 Git 忽略的 .env 中）
```

验证结果：

- `GET /v1/models` 曾成功返回模型目录，说明 Base URL 和 API Key 有效。
- 模型目录中确认存在 `gpt-5.4`，因此将其选为默认模型。
- 后续最小聊天请求和再次访问模型目录时，连接到服务商主机超时，HTTP 状态为 `000`；未收到 401、403 或模型参数错误。这表明当时是服务商连接或本机到该域名的网络波动，不能视为鉴权失败。

### 3. 创建 DeerFlow 配置

创建了以下被 Git 忽略的本地文件：

- `.env`：保存 `VECTOR_ENGINE_API_KEY`。
- `config.yaml`：DeerFlow 主配置。
- `frontend/.env`：标准 Docker/nginx 同源模式，无需前端密钥或 URL 覆盖。
- `extensions_config.json`：当前为空对象，暂不启用额外 MCP 服务。

`config.yaml` 的主要设置：

- 配置版本：26。
- 模型实现：`langchain_openai:ChatOpenAI`。
- 默认模型：`gpt-5.4`。
- API 地址：`https://api.vectorengine.ai/v1`。
- API Key 引用：`$VECTOR_ENGINE_API_KEY`。
- 请求超时：600 秒。
- 最大重试：2 次。
- 最大输出：4096 tokens。
- 视觉能力：启用。
- Web 搜索：DuckDuckGo，无需额外 API Key。
- Web Fetch：Jina AI Reader，无需额外 API Key。
- 图片搜索：DuckDuckGo Images。
- 文件读取和写入工具：启用。
- IM 渠道：全部关闭。

最初选择了 AIO Docker 容器沙箱，并成功拉取默认 sandbox 镜像。随后启动脚本发现 Windows Docker Desktop 没有 Git Bash 可见的 `/var/run/docker.sock`，无法使用 DooD 模式。为保证 Docker 开发栈能够启动，最终改为：

```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
```

这里的“本地沙箱”运行在 Gateway 容器内部；宿主机 Bash 保持关闭，配置中也移除了 Bash 工具。

### 4. 安装后端依赖并运行诊断

执行了等价于 `make doctor` 的命令：

```powershell
cd backend
$env:PYTHONUTF8='1'
uv run python ../scripts/doctor.py
```

首次运行创建了 `backend/.venv`，安装 220 个锁定依赖包。

诊断确认：

- `.env` 存在。
- `frontend/.env` 已补齐。
- `config.yaml` 版本正确且可以加载。
- 已配置 1 个模型。
- `VECTOR_ENGINE_API_KEY` 能被模型配置解析。
- `langchain-openai` 已安装。
- DuckDuckGo 搜索、Jina Reader 和图片搜索配置正确。
- 沙箱配置可识别。

诊断器仍把宿主机 nginx 缺失列为错误；Docker 模式使用 nginx 容器，因此这不是 Docker 启动阻塞。第一次诊断还遇到 Windows GBK 无法输出 `✓` 的 `UnicodeEncodeError`，通过启用 `PYTHONUTF8=1` 解决。

### 5. 初始化并启动 Docker 开发栈

执行了：

```powershell
cmd.exe /d /c scripts\run-with-git-bash.cmd ./scripts/docker.sh init
cmd.exe /d /c scripts\run-with-git-bash.cmd ./scripts/docker.sh start
```

完成事项：

- 启动 Docker Desktop 及 Linux 容器引擎。
- 拉取默认 AIO sandbox 镜像，镜像摘要为 `sha256:742062f99915e5495df8d4bfeaf40a93197c87c7c47b4e2407cd2b6356df8f48`。
- 首次拉取 `redis:7-alpine` 时发生 `unexpected EOF`，单独重试后成功。
- 构建 `deer-flow-dev-frontend` 镜像。
- 构建 `deer-flow-dev-gateway` 镜像。
- 创建并启动 Redis、Frontend、Gateway、Nginx 四个容器。

首次 Docker 构建耗时较长，主要原因是到 Debian、npm 和容器镜像源的下载速度较慢；镜像和依赖现已缓存。

## 首次验证结果（修复前）

验证时间点的容器状态：

| 容器 | 状态 |
| --- | --- |
| `deer-flow-nginx` | Running |
| `deer-flow-frontend` | Running |
| `deer-flow-gateway` | Running，但应用子进程启动失败 |
| `deer-flow-redis` | Running / Healthy |

HTTP 验证：

- `http://localhost:2026/` 返回 HTTP 200，前端可访问。
- `/api/*` 返回 HTTP 502，因为 Gateway 的 Uvicorn 应用没有完成导入。

Gateway 日志中的实际阻塞：

```text
ValueError: Found invalid Google-Style docstring.
```

错误来自：

```text
backend/packages/harness/deerflow/tools/builtins/clarification_tool.py
```

该文件对 `ask_clarification_tool` 使用了 `@tool(..., parse_docstring=True)`，但函数文档字符串不是合法的 Google 风格，因此当前锁定的 `langchain-core 1.3.3` 在 Gateway 导入阶段拒绝加载。这是仓库现有源码缺陷，不是 VectorEngine 或本地配置错误。

按照仓库 `backend/AGENTS.md`，修复后端代码必须新增回归测试并同步 README/AGENTS 文档。本次任务只修改本地配置和安装状态，没有擅自修改业务源码。

## 当时结论（修复前）

本地配置、模型凭据引用、后端依赖、Docker 镜像和四服务开发栈均已准备。前端入口可访问；项目完整聊天功能仍被现有 `clarification_tool.py` 文档字符串缺陷阻塞，需要单独完成一次带测试的代码修复。

## 后续常用命令

当前宿主机没有 Make，可使用：

```powershell
# 启动或重新构建
cmd.exe /d /c scripts\run-with-git-bash.cmd ./scripts/docker.sh start

# 查看 Gateway 日志
docker logs deer-flow-gateway --tail 200
Get-Content .\logs\gateway.log -Tail 200

# 查看容器状态
docker ps --filter "name=deer-flow-"

# 停止开发栈
cmd.exe /d /c scripts\run-with-git-bash.cmd ./scripts/docker.sh stop
```

安装 GNU Make 并加入 PATH 后，可以改用标准命令：

```bash
make docker-start
make docker-logs
make docker-stop
```

## 安全提醒

完整 API Key 曾直接出现在聊天消息中。即使 `.env` 已被 Git 忽略，也建议在 VectorEngine 后台轮换该 Key，然后只更新根目录 `.env` 中的 `VECTOR_ENGINE_API_KEY`，不要把完整 Key 写入 Markdown、Git 提交或截图。

## 2026-08-29：Gateway 启动故障修复

### 根因确认

使用当前锁定的 `langchain-core 1.3.3` 复现并确认：批量中文化提交
`68dfcd322` 破坏了使用 `@tool(parse_docstring=True)` 的 Google 风格工具文档
字符串。Gateway 在导入第一个损坏的 `ask_clarification_tool` 时退出，Nginx 因此
对 `/api/*` 返回 502。

全量静态审计结果：

- 后端共有 45 个启用了文档字符串解析的生产工具或测试夹具。
- 41 个生产工具的文档字符串无效。
- 2 个测试夹具存在同类问题。
- 问题提交之前，43 个当时已有的生产工具全部可以通过解析。

### 已完成的修复

- 建立隔离工作树和 `codex/fix-tool-docstrings` 分支进行修复。
- 先新增失败的回归测试，再恢复全部无效工具文档字符串。
- 保留所有 `parse_docstring=True`，没有通过关闭 Schema 解析绕过问题。
- 按当前函数签名恢复 `Args:` 参数说明，并删除涉及文件中的无意义占位注释。
- 将扫描范围扩展到 `backend/app`、`backend/packages`、`backend/scripts` 和
  `backend/tests`。
- 扫描器只识别真实导入或别名的 LangChain `tool` 装饰器；动态或 `**kwargs`
  形式的 `parse_docstring` 配置会直接失败，防止静默漏检。
- 注入参数按导入的类型注解识别，不再仅凭 `runtime` 等参数名称猜测。
- 删除两个仍引用已被历史提交移除的 `.agent` / `.github` 文档的陈旧测试。
- 更新根 `README.md`、`backend/AGENTS.md`、修复规范和实施计划。
- 修复提交 `7b7ba3aa` 已快进合并到本地 `main`。

### 验证结果

- 合并后聚焦测试：97 passed。
- 新增工具文档契约测试、原有工具 Schema 测试、澄清中间件测试、Gateway
  导入测试均通过。
- 去除文档字符串后的生产代码 AST 对比：0 个可执行语句变化。
- 独立代码审查复审结论：无 Critical / Important 问题，可以合并。
- Windows 全量后端测试：7525 passed、31 skipped、85 failed；失败主要是
  POSIX 权限、路径和 `sh` 假设在 Windows 上不成立，以及仓库既有的其他回归。
- 一次性 Linux/Docker 全量测试：7611 passed、27 skipped；最初仅有两个已删除
  文档的陈旧测试和测试镜像缺少 `git` 的环境失败。陈旧测试随后已修正，Git
  相关测试在 Windows 宿主机单独通过。
- `http://localhost:2026/`：HTTP 200。
- `http://localhost:2026/login`：HTTP 200。
- `http://localhost:2026/api/models`：HTTP 401，不再是 502；401 是未登录时的
  正常鉴权响应，证明 Nginx 已能连接 Gateway。
- Gateway 最近日志中的 `invalid Google-Style docstring`、Traceback 和应用启动
  失败匹配数：0。
- Gateway 容器内 Uvicorn 主进程和应用子进程均在运行。
- VectorEngine `GET /v1/models`：HTTP 200；当前 Base URL、网络和凭据有效。

### 仍需人工完成

旧 API Key 曾直接出现在聊天中。虽然当前验证仍然有效，但应登录 VectorEngine
控制台撤销旧 Key、创建新 Key，然后只更新根目录 `.env`。此操作需要服务商账号
会话，未在本次自动修复中代替用户执行。

### 最终清理与复核

- 确认 `codex/fix-tool-docstrings` 与 `main` 均指向提交 `7b7ba3aa`，且隔离
  工作树没有未提交文件后，移除了 `.worktrees/fix-tool-docstrings` 并删除本地
  临时分支。
- 在合并后的 `main` 上重新运行文档字符串契约、工具 Schema、澄清中间件和
  Gateway 导入测试：58 passed。
- 再次检查运行态：DeerFlow 的 Nginx、Gateway、Redis、Frontend 容器均在运行；
  `/` 和 `/login` 返回 HTTP 200，未登录访问 `/api/models` 返回正常的 HTTP 401。
- 使用仅保存在本地 `.env` 的凭据重新请求 VectorEngine `/v1/models`：HTTP 200，
  返回 533 个模型。检查过程中未输出或写入完整 API Key。

## 最终结论

DeerFlow 的本地配置、Docker 开发栈和 VectorEngine 接口目前均可用；阻塞
Gateway 启动的工具文档字符串缺陷已经修复，Nginx 到 Gateway 的 502 已消失。
浏览器可继续从 `http://localhost:2026/login` 登录使用。唯一不能代替用户完成的
事项是到 VectorEngine 控制台轮换曾在聊天中暴露的旧 API Key。
