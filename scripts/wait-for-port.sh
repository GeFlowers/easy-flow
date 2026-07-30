#!/usr/bin/env bash
#
# wait-for-port.sh - 等待 TCP 端口开始监听
#
# 用法：./scripts/wait-for-port.sh <port> [timeout_seconds] [service_name]
#
# 参数：
#   port             - 要等待的 TCP 端口（必填）
#   timeout_seconds  - 最长等待秒数（默认：60）
#   service_name     - 输出消息中的服务名称（默认："Service"）
#
# 退出码：
#   0 - 端口正在监听
#   1 - 等待超时

PORT="${1:?Usage: wait-for-port.sh <port> [timeout] [service_name]}"
TIMEOUT="${2:-60}"
SERVICE="${3:-Service}"

case "$PORT" in
    ''|*[!0-9]*)
        echo "Port must be a numeric TCP port: $PORT" >&2
        exit 1
        ;;
esac

if [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "Port must be between 1 and 65535: $PORT" >&2
    exit 1
fi

elapsed=0
interval=1

# 按 Windows、macOS/Linux 常用工具依次探测端口；缺少某个工具时继续回退。
is_port_listening() {
    if command -v powershell.exe >/dev/null 2>&1; then
        if WAIT_FOR_PORT_PORT="$PORT" powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "\$ErrorActionPreference='SilentlyContinue'; \$Port = [int]\$env:WAIT_FOR_PORT_PORT; if (Get-NetTCPConnection -LocalPort \$Port -State Listen) { exit 0 } else { exit 1 }" >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v lsof >/dev/null 2>&1; then
        if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v ss >/dev/null 2>&1; then
        if ss -ltn "( sport = :$PORT )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
    fi

    if command -v netstat >/dev/null 2>&1; then
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${PORT}$"; then
            return 0
        fi
    fi

    return 1
}

while ! is_port_listening; do
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo ""
        echo "✗ $SERVICE failed to start on port $PORT after ${TIMEOUT}s"
        exit 1
    fi
    printf "\r  Waiting for %s on port %s... %ds" "$SERVICE" "$PORT" "$elapsed"
    sleep "$interval"
    elapsed=$((elapsed + interval))
done

printf "\r  %-60s\r" ""   # 清除等待进度行
