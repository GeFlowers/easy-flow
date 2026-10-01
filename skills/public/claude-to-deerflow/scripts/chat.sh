#!/usr/bin/env bash
# chat.sh — 向 DeerFlow 发送消息并收集流式响应。
# 用法：
#   bash chat.sh "你的问题"
#   bash chat.sh "你的问题" <thread_id>          # 继续已有会话
#   bash chat.sh "你的问题" "" pro                # 指定运行模式
#   DEERFLOW_URL=http://host:2026 bash chat.sh "你好"   # 指定服务地址
# 环境变量：
#   DEERFLOW_URL          — 统一代理基地址（默认：http://localhost:2026）
#   DEERFLOW_GATEWAY_URL  — 网关接口基地址（默认：$DEERFLOW_URL）
#   DEERFLOW_LANGGRAPH_URL — LangGraph 接口基地址（默认：$DEERFLOW_URL/api/langgraph）
# 模式：flash、standard、pro（默认）、ultra

set -euo pipefail

DEERFLOW_URL="${DEERFLOW_URL:-http://localhost:2026}"
GATEWAY_URL="${DEERFLOW_GATEWAY_URL:-$DEERFLOW_URL}"
LANGGRAPH_URL="${DEERFLOW_LANGGRAPH_URL:-$DEERFLOW_URL/api/langgraph}"
MESSAGE="${1:?Usage: chat.sh <message> [thread_id] [mode]}"
THREAD_ID="${2:-}"
MODE="${3:-pro}"

# --- 健康检查：请求前快速失败，避免创建无效会话 ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${GATEWAY_URL}/health" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "000" ] || [ "$HTTP_CODE" -ge 400 ]; then
  echo "ERROR: DeerFlow is not reachable at ${GATEWAY_URL} (HTTP ${HTTP_CODE})" >&2
  echo "Make sure DeerFlow is running. Start it with: cd <deerflow-dir> && make docker-start" >&2
  exit 1
fi

# --- 创建或复用 thread ---
if [ -z "$THREAD_ID" ]; then
  THREAD_RESP=$(curl -s -X POST "${LANGGRAPH_URL}/threads" \
    -H "Content-Type: application/json" \
    -d '{}')
  THREAD_ID=$(echo "$THREAD_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['thread_id'])" 2>/dev/null)
  if [ -z "$THREAD_ID" ]; then
    echo "ERROR: Failed to create thread. Response: ${THREAD_RESP}" >&2
    exit 1
  fi
  echo "Thread: ${THREAD_ID}" >&2
fi

# --- 按模式构建上下文 ---
case "$MODE" in
  flash)
    CONTEXT='{"thinking_enabled":false,"is_plan_mode":false,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  standard)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":false,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  pro)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":true,"subagent_enabled":false,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  ultra)
    CONTEXT='{"thinking_enabled":true,"is_plan_mode":true,"subagent_enabled":true,"thread_id":"'"$THREAD_ID"'"}'
    ;;
  *)
    echo "ERROR: Unknown mode '${MODE}'. Use: flash, standard, pro, ultra" >&2
    exit 1
    ;;
esac

# --- 为 JSON 转义消息，避免用户输入破坏请求体 ---
ESCAPED_MSG=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MESSAGE")

# --- 构建请求体 ---
BODY=$(cat <<ENDJSON
{
  "assistant_id": "lead_agent",
  "input": {
    "messages": [
      {
        "type": "human",
        "content": [{"type": "text", "text": ${ESCAPED_MSG}}]
      }
    ]
  },
  "stream_mode": ["values", "messages-tuple"],
  "stream_subgraphs": true,
  "config": {
    "recursion_limit": 1000
  },
  "context": ${CONTEXT}
}
ENDJSON
)

# --- 流式执行并提取最终响应 ---
# 收集完整 SSE 输出，再解析最后一个 values 事件以取得智能体响应。
TMPFILE=$(mktemp)
trap "rm -f '$TMPFILE'" EXIT

curl -s -N -X POST "${LANGGRAPH_URL}/threads/${THREAD_ID}/runs/stream" \
  -H "Content-Type: application/json" \
  -d "$BODY" > "$TMPFILE"

# 解析 SSE 输出：提取最后一个 "event: values" 数据块并取得最终智能体消息。
python3 - "$TMPFILE" "$GATEWAY_URL" "$THREAD_ID" << 'PYEOF'
import json
import sys

sse_file = sys.argv[1] if len(sys.argv) > 1 else None
gateway_url = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://localhost:2026"
thread_id = sys.argv[3] if len(sys.argv) > 3 else ""
if not sse_file:
    sys.exit(1)

with open(sse_file, "r") as f:
    raw = f.read()

# 解析 SSE 事件。
events = []
current_event = None
current_data_lines = []

for line in raw.split("\n"):
    if line.startswith("event:"):
        if current_event and current_data_lines:
            events.append((current_event, "\n".join(current_data_lines)))
        current_event = line[len("event:"):].strip()
        current_data_lines = []
    elif line.startswith("data:"):
        current_data_lines.append(line[len("data:"):].strip())
    elif line == "" and current_event:
        if current_data_lines:
            events.append((current_event, "\n".join(current_data_lines)))
        current_event = None
        current_data_lines = []

# 处理缓冲区中剩余的数据。
if current_event and current_data_lines:
    events.append((current_event, "\n".join(current_data_lines)))

import posixpath

def extract_response_text(messages):
    """与 manager.py 中的 _extract_response_text 保持一致，提取澄清中断或普通智能体消息。"""
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        msg_type = msg.get("type")
        # 处理 ask_clarification 中断：工具消息的名称为 ask_clarification。
        if msg_type == "tool" and msg.get("name") == "ask_clarification":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
        # 处理普通智能体消息。
        if msg_type == "ai":
            content = msg.get("content", "")
            if isinstance(content, str) and content:
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        parts.append(block)
                text = "".join(parts)
                if text:
                    return text
    return ""

def extract_artifacts(messages):
    """与 manager.py 中的 _extract_artifacts 保持一致，只提取最近一次响应产生的文件。"""
    artifacts = []
    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "human":
            break
        if msg.get("type") == "ai":
            for tc in msg.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("name") == "present_files":
                    paths = tc.get("args", {}).get("filepaths", [])
                    if isinstance(paths, list):
                        artifacts.extend(p for p in paths if isinstance(p, str))
    return artifacts

def artifact_url(virtual_path):
    # virtual_path 示例：/mnt/user-data/outputs/file.md。
    # 接口路径：{gateway}/api/threads/{thread_id}/artifacts/{去除开头斜杠后的路径}。
    path = virtual_path.lstrip("/")
    return f"{gateway_url}/api/threads/{thread_id}/artifacts/{path}"

def format_artifact_text(artifacts):
    urls = [artifact_url(p) for p in artifacts]
    if len(urls) == 1:
        return f"Created File: {urls[0]}"
    return "Created Files:\n" + "\n".join(urls)

# 查找最后一个包含消息的 "values" 事件。
result_messages = None
for event_type, data_str in reversed(events):
    if event_type != "values":
        continue
    try:
        data = json.loads(data_str)
    except json.JSONDecodeError:
        continue
    if "messages" in data:
        result_messages = data["messages"]
        break

if result_messages is not None:
    response_text = extract_response_text(result_messages)
    artifacts = extract_artifacts(result_messages)
    if artifacts:
        artifact_text = format_artifact_text(artifacts)
        response_text = (response_text + "\n\n" + artifact_text) if response_text else artifact_text
    if response_text:
        print(response_text)
    else:
        print("(No response from agent)", file=sys.stderr)
        sys.exit(1)
else:
    # 检查是否存在错误事件。
    for event_type, data_str in events:
        if event_type == "error":
            print(f"ERROR from DeerFlow: {data_str}", file=sys.stderr)
            sys.exit(1)
    print("No AI response found in the stream.", file=sys.stderr)
    if len(raw) < 2000:
        print(f"Raw SSE output:\n{raw}", file=sys.stderr)
    sys.exit(1)
PYEOF

echo ""
echo "---"
echo "Thread ID: ${THREAD_ID}" >&2
