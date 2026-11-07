---
name: claude-to-deerflow
description: "通过网络接口与 DeerFlow 人工智能平台交互。用户希望向 DeerFlow 发送消息进行研究或分析、创建对话、检查状态与健康情况、列出可用模型／技能／智能体、管理记忆、上传文件或委派复杂研究任务时使用。用户提到 deerflow、deer flow，或希望运行 DeerFlow 能处理的深度研究任务时也使用。"
---

# DeerFlow 技能

通过 HTTP（HyperText Transfer Protocol，超文本传输协议）API（Application Programming Interface，应用程序编程接口）与运行中的 DeerFlow 实例通信。DeerFlow 是基于 LangGraph 的人工智能平台，可编排子智能体执行研究、代码、网页浏览等任务。

## 架构

DeerFlow 在 Nginx 反向代理之后提供两个接口入口：

| 服务 | 直连端口 | 代理入口 | 用途 |
|----------------|-------------|----------------------------------|----------------------------------|
| 网关接口 | 8001 | `$DEERFLOW_GATEWAY_URL` | REST（Representational State Transfer，表述性状态转移）端点和嵌入式智能体运行时 |
| 兼容 LangGraph 的接口 | 8001 | `$DEERFLOW_LANGGRAPH_URL` | 智能体对话、运行和流式传输 |

## 环境变量

所有地址均可通过环境变量配置。**发送任何请求前先读取这些环境变量。**

| 变量 | 默认值 | 说明 |
|-------------------------|------------------------------------------|------------------------------------|
| `DEERFLOW_URL`          | `http://localhost:2026`                  | 统一代理基础地址             |
| `DEERFLOW_GATEWAY_URL`  | `${DEERFLOW_URL}`                        | 网关基础地址（模型、技能、记忆、上传） |
| `DEERFLOW_LANGGRAPH_URL`| `${DEERFLOW_URL}/api/langgraph`          | LangGraph 基础地址（对话、运行） |

调用 curl 时，始终按以下方式解析地址：

```bash
# 从环境变量解析基础地址（任何接口调用前首先执行）
DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
DEERFLOW_GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
DEERFLOW_LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"
```

## 可用操作

### 1. 健康检查

确认 DeerFlow 正在运行：

```bash
curl -s "$DEERFLOW_GATEWAY_URL/health"
```

### 2. 发送消息（流式）

这是主要操作：创建对话，并以流式接收智能体响应。

**第 1 步：创建对话**

```bash
curl -s -X POST "$DEERFLOW_LANGGRAPH_URL/threads" \
  -H "Content-Type: application/json" \
  -d '{}'
```

响应： `{"thread_id": "<uuid>", ...}`

**第 2 步：流式运行**

```bash
curl -s -N -X POST "$DEERFLOW_LANGGRAPH_URL/threads/<thread_id>/runs/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "assistant_id": "lead_agent",
    "input": {
      "messages": [
        {
          "type": "human",
          "content": [{"type": "text", "text": "在此填写消息"}]
        }
      ]
    },
    "stream_mode": ["values", "messages-tuple"],
    "stream_subgraphs": true,
    "config": {
      "recursion_limit": 1000
    },
    "context": {
      "thinking_enabled": true,
      "is_plan_mode": true,
      "subagent_enabled": true,
      "thread_id": "<thread_id>"
    }
  }'
```

响应是 SSE（Server-Sent Events，服务器发送事件）流。每个事件格式如下：
```
event: <event_type>
data: <json_data>
```

主要事件类型：
- `metadata`：运行元数据，包含 `run_id`。
- `values`：完整状态快照，包含 `messages` 数组。
- `messages-tuple`：增量消息更新（模型文本片段、工具调用和工具结果）。
- `end`：流式传输完成。

**上下文模式**（通过 `context` 设置）：
- 快速模式： `thinking_enabled: false, is_plan_mode: false, subagent_enabled: false`
- 标准模式： `thinking_enabled: true, is_plan_mode: false, subagent_enabled: false`
- 专业模式： `thinking_enabled: true, is_plan_mode: true, subagent_enabled: false`
- 超级模式： `thinking_enabled: true, is_plan_mode: true, subagent_enabled: true`

### 3. 继续对话

发送后续消息时，复用第 2 步的 `thread_id`，携带新消息发起另一个 POST 请求。

### 4. 列出模型

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/models"
```

返回： `{"models": [{"name": "...", "provider": "...", ...}, ...]}`

### 5. 列出技能

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/skills"
```

返回： `{"skills": [{"name": "...", "enabled": true, ...}, ...]}`

### 6. 启用／禁用技能

```bash
curl -s -X PUT "$DEERFLOW_GATEWAY_URL/api/skills/<skill_name>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

### 7. 列出智能体

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/agents"
```

返回： `{"agents": [{"name": "...", ...}, ...]}`

### 8. 获取记忆

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/memory"
```

返回用户上下文、事实以及历史对话摘要。

### 9. 上传文件到对话

```bash
curl -s -X POST "$DEERFLOW_GATEWAY_URL/api/threads/<thread_id>/uploads" \
  -F "files=@/path/to/file.pdf"
```

支持 PDF（Portable Document Format，便携式文档格式）、PPTX（PowerPoint Open XML Presentation，PowerPoint 开放式可扩展标记语言演示文稿）、XLSX（Excel Open XML Spreadsheet，Excel 开放式可扩展标记语言工作簿）、DOCX（Word Open XML Document，Word 开放式可扩展标记语言文档），自动转换为 Markdown。

### 10. 列出已上传文件

```bash
curl -s "$DEERFLOW_GATEWAY_URL/api/threads/<thread_id>/uploads/list"
```

### 11. 获取对话历史

```bash
curl -s "$DEERFLOW_LANGGRAPH_URL/threads/<thread_id>/history"
```

### 12. 列出对话

```bash
curl -s -X POST "$DEERFLOW_LANGGRAPH_URL/threads/search" \
  -H "Content-Type: application/json" \
  -d '{"limit": 20, "sort_by": "updated_at", "sort_order": "desc"}'
```

## 使用辅助脚本

发送消息并收集完整响应时，使用辅助脚本：

```bash
bash /path/to/skills/claude-to-deerflow/scripts/chat.sh "在此填写问题"
```

实现见 `scripts/chat.sh`。脚本会：
1. 检查健康状态。
2. 创建对话。
3. 流式运行并收集模型最终响应。
4. 输出结果。

## 解析服务器发送事件输出

流中返回服务器发送事件。从 `values` 事件提取模型最终响应：
- 找到最后一个 `event: values` 块。
- 解析其 `data` 数据。
- `messages` 数组包含全部消息，最后一个 `type: "ai"` 消息即响应。
- 该消息的 `content` 字段是模型文本回复。

## 错误处理

- 健康检查失败说明 DeerFlow 未运行，提醒用户启动。
- 流返回错误事件时，提取并展示错误信息。
- 常见问题：端口未开放、服务仍在启动、配置错误。

## 建议

- 简单问题使用快速模式，速度最快且不规划。
- 研究任务使用专业或超级模式，启用规划或子智能体。
- 可以先上传文件，再在消息中引用。
- 对话标识会持久保存，之后可以返回继续。
