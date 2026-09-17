#!/usr/bin/env bash
#
# serve.sh — DeerFlow 统一服务启动器
#
# 用法：
#   ./scripts/serve.sh [--dev|--prod] [--daemon] [--stop|--restart]
#
# 模式：
#   --dev       开发模式，启用热重载（默认）
#   --prod      生产模式，使用预构建前端且不热重载
#   --daemon    使用 nohup 在后台运行全部服务，启动后退出
#
# 操作：
#   --skip-install  跳过依赖安装，加快重启
#   --stop      停止全部运行中服务后退出
#   --restart   先停止全部服务，再按给定模式启动
#
# 示例：
#   ./scripts/serve.sh --dev                 # Gateway dev, hot reload
#   ./scripts/serve.sh --prod                # Gateway prod
#   ./scripts/serve.sh --dev --daemon        # Gateway dev, background
#   ./scripts/serve.sh --stop                # Stop all services
#   ./scripts/serve.sh --restart --dev       # Restart dev services
#
# 脚本会切换到仓库根目录，因此调用位置不影响路径解析。

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

# ── 加载 .env ────────────────────────────────────────────────────────────────

if [ -f "$REPO_ROOT/.env" ]; then
    set -a
    source "$REPO_ROOT/.env"
    set +a
fi

# 选择可执行的 Python 3；Windows/Git Bash 下依次回退不同命令名。
_pick_python() {
    local candidate
    for candidate in python3 python py; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info.major >= 3 else 1)' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

# ── 参数解析 ─────────────────────────────────────────────────────────────────

DEV_MODE=true
DAEMON_MODE=false
SKIP_INSTALL=false
ACTION="start"   # start | stop | restart

for arg in "$@"; do
    case "$arg" in
        --dev)     DEV_MODE=true ;;
        --prod)    DEV_MODE=false ;;
        --daemon)  DAEMON_MODE=true ;;
        --skip-install) SKIP_INSTALL=true ;;
        --stop)    ACTION="stop" ;;
        --restart) ACTION="restart" ;;
        *)
            echo "Unknown argument: $arg"
            echo "Usage: $0 [--dev|--prod] [--daemon] [--skip-install] [--stop|--restart]"
            exit 1
            ;;
    esac
done

# ── 停止辅助逻辑 ──────────────────────────────────────────────────────────────

# 所有 deer-flow worktree（主检出与关联 worktree）均使用 8001/3000 开发端口，
# 因而需要能够回收任一检出的服务；否则本检出的 `make stop`/`make dev` 无法接管同级
# worktree 占用的端口。DEERFLOW_ROOTS 是允许处理的根目录集合，集合外的进程（如另一个
# 项目占用 3000）绝不触及。按路径长度从长到短排序，使嵌套的关联 worktree 归属准确。
DEERFLOW_ROOTS="$(
    {
        printf '%s\n' "$REPO_ROOT"
        git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null |
            awk '/^worktree /{print $2}'
    } | awk 'NF && !seen[$0]++ {print length($0)"\t"$0}' | sort -rn | sed 's/^[0-9]*\t//'
)"

# 判断 PID 是否在任一 deer-flow worktree 根目录下打开文件或以其为 cwd；路径末尾的
# 斜杠避免将 ".../deer-flow-notes" 这类同级目录误判为 ".../deer-flow"。
_is_deerflow_pid() {
    local pid=$1 files root

    # 守护子进程从 run_service 继承 DEERFLOW_DAEMON_ROOT。Linux 上检查 /proc 环境
    # 可识别 lsof 漏掉的 next-server 等进程；macOS 无 /proc 时回退到 lsof。
    if [ -r "/proc/$pid/environ" ] &&
        tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -Fxq "DEERFLOW_DAEMON_ROOT=$REPO_ROOT"; then
        return 0
    fi

    files=$(lsof -b -w -p "$pid" 2>/dev/null) || return 1
    while IFS= read -r root; do
        [ -n "$root" ] || continue
        case "$files" in
            *"$root"/*) return 0 ;;
        esac
    done <<< "$DEERFLOW_ROOTS"
    return 1
}

# 在回收其他 worktree 的端口前显式报告，避免停止（或启动前停止）时静默中断他人进程。
_report_reclaimed_ports() {
    local port pid files root owner
    for port in 8001 3000; do
        for pid in $(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null); do
            _is_deerflow_pid "$pid" || continue
            files=$(lsof -b -w -p "$pid" 2>/dev/null)
            case "$files" in *"$REPO_ROOT"/*) continue ;; esac  # this worktree — normal
            owner=""
            while IFS= read -r root; do
                [ -n "$root" ] || continue
                case "$files" in *"$root"/*) owner="$root"; break ;; esac
            done <<< "$DEERFLOW_ROOTS"
            echo "  ↻ Reclaiming port $port from another worktree: ${owner:-?}"
            break
        done
    done
}

# 仅终止同时匹配命令特征与仓库归属的进程，避免按名称误杀其他项目。
_kill_repo_processes() {
    local pattern=$1
    local pid
    local pids=""

    while IFS= read -r pid; do
        if [ -n "$pid" ] && _is_deerflow_pid "$pid"; then
            case " $pids " in
                *" $pid "*) ;;
                *) pids="$pids $pid" ;;
            esac
        fi
    done < <(pgrep -f "$pattern" 2>/dev/null || true)

    if [ -n "$pids" ]; then
        kill $pids 2>/dev/null || true
    fi
}

# 对仍占用服务端口且归属仓库的进程执行最终强制清理。
_kill_repo_port() {
    local port=$1
    local pid
    local pids=""

    while IFS= read -r pid; do
        if [ -n "$pid" ] && _is_deerflow_pid "$pid"; then
            case " $pids " in
                *" $pid "*) ;;
                *) pids="$pids $pid" ;;
            esac
        fi
    done < <(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)

    if [ -n "$pids" ]; then
        kill -9 $pids 2>/dev/null || true
    fi
}

# 按可用工具探测监听端口；lsof 缺失时回退 ss，再回退 netstat。
_is_port_listening() {
    local port=$1

    if command -v lsof >/dev/null 2>&1; then
        if lsof -nP -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1; then
            return 0
        fi
    fi

    if command -v ss >/dev/null 2>&1; then
        if ss -ltn "( sport = :$port )" 2>/dev/null | tail -n +2 | grep -q .; then
            return 0
        fi
    fi

    if command -v netstat >/dev/null 2>&1; then
        if netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|[.:])${port}$"; then
            return 0
        fi
    fi

    return 1
}

# 以温和退出优先、强制端口回收兜底的顺序停止本项目服务。
stop_all() {
    echo "Stopping all services..."
    _report_reclaimed_ports
    _kill_repo_processes "uvicorn app.gateway.app:app"
    _kill_repo_processes "next dev"
    _kill_repo_processes "next start"
    _kill_repo_processes "next-server"
    sleep 1
    # 对仍占用服务端口的残留进程强制清理。
    _kill_repo_port 8001
    _kill_repo_port 3000
    ./scripts/cleanup-containers.sh deer-flow-sandbox 2>/dev/null || true
    echo "✓ All services stopped"
}

# ── 操作路由 ─────────────────────────────────────────────────────────────────

if [ "$ACTION" = "stop" ]; then
    stop_all
    exit 0
fi

ALREADY_STOPPED=false
if [ "$ACTION" = "restart" ]; then
    stop_all
    sleep 1
    ALREADY_STOPPED=true
fi

# 启动横幅使用的模式标签。
if $DEV_MODE; then
    MODE_LABEL="DEV (Gateway runtime, hot-reload enabled)"
else
    MODE_LABEL="PROD (Gateway runtime, optimized)"
fi

if $DAEMON_MODE; then
    MODE_LABEL="$MODE_LABEL [daemon]"
fi

# 根据模式选择前端启动命令；生产预览生成进程内认证密钥。
if $DEV_MODE; then
    FRONTEND_CMD="pnpm run dev"
else
    if ! PYTHON_BIN="$(_pick_python)"; then
        echo "Python is required to generate BETTER_AUTH_SECRET."
        exit 1
    fi
    FRONTEND_CMD="env BETTER_AUTH_SECRET=$($PYTHON_BIN -c 'import secrets; print(secrets.token_hex(16))') pnpm run preview"
fi

# 运行时路径默认值：本地 `make dev` 从 `backend/` 启动 Gateway，因此将 DeerFlow
# 自有状态固定在预期后端目录，并在 uvicorn 构建热重载排除规则前创建该目录。
if [ -z "$DEER_FLOW_PROJECT_ROOT" ]; then
    export DEER_FLOW_PROJECT_ROOT="$REPO_ROOT"
fi

BACKEND_RUNTIME_HOME="$REPO_ROOT/backend/.deer-flow"
if [ -z "$DEER_FLOW_HOME" ]; then
    export DEER_FLOW_HOME="$BACKEND_RUNTIME_HOME"
fi

mkdir -p "$DEER_FLOW_HOME" "$BACKEND_RUNTIME_HOME"
DEER_FLOW_HOME="$(cd "$DEER_FLOW_HOME" && pwd -P)"
BACKEND_RUNTIME_HOME="$(cd "$BACKEND_RUNTIME_HOME" && pwd -P)"
export DEER_FLOW_HOME

# 仅前台开发模式启用 uvicorn 热重载，并排除运行时高频写入目录。
if $DEV_MODE && ! $DAEMON_MODE; then
    GATEWAY_EXTRA_FLAGS="--reload --reload-include='*.yaml' --reload-include='.env' --reload-exclude='*.pyc' --reload-exclude='__pycache__' --reload-exclude='$DEER_FLOW_HOME' --reload-exclude='$BACKEND_RUNTIME_HOME'"
else
    GATEWAY_EXTRA_FLAGS=""
fi

# ── 停止既有服务（restart 已停止时跳过） ──────────────────────────────────────

if ! $ALREADY_STOPPED; then
    stop_all
    sleep 1
fi

# ── 配置检查 ─────────────────────────────────────────────────────────────────

if ! { \
        [ -n "$DEER_FLOW_CONFIG_PATH" ] && [ -f "$DEER_FLOW_CONFIG_PATH" ] || \
        [ -f backend/config.yaml ] || \
        [ -f config.yaml ]; \
    }; then
    echo "✗ No DeerFlow config file found."
    echo "  Run 'make setup' (recommended) or 'make config' to generate config.yaml."
    exit 1
fi

"$REPO_ROOT/scripts/config-upgrade.sh"

# ── 安装依赖 ─────────────────────────────────────────────────────────────────

# 为 extras 探测器选择可执行的 Python。Windows/Git Bash 中 `python3` 可能解析到
# WindowsApps 的 Microsoft Store 别名；它虽在 PATH 中，却无法从 Bash 执行。
DETECT_PYTHON="$(_pick_python || true)"

# 从 UV_EXTRAS 或 config.yaml 解析 uv extras（如 postgres），避免每次重启时 `uv sync`
# 清除可选依赖。详见 scripts/detect_uv_extras.py 与 Issue #2754。探测器按
# `^[A-Za-z][A-Za-z0-9_-]*$` 白名单校验名称，因此下方未加引号的展开仅包含有效 uv 参数。
#
# 有意不重定向 stderr，以让用户看到白名单警告（如 "ignoring invalid UV_EXTRAS entry ';'"）
# 与探测器崩溃（如意外的 Python 错误）。`|| true` 防止 `set -e` 因探测失败终止开发启动；
# 此时仅得到空 UV_EXTRAS_FLAGS，即“不使用 extras”。
UV_EXTRAS_FLAGS=""
if [ -n "$DETECT_PYTHON" ]; then
    UV_EXTRAS_FLAGS=$("$DETECT_PYTHON" "$REPO_ROOT/scripts/detect_uv_extras.py" || { echo "[serve.sh] detect_uv_extras.py failed (exit $?) — proceeding without extras" >&2; echo ""; })
fi

if ! $SKIP_INSTALL; then
    echo "Syncing dependencies..."
    if [ -n "$UV_EXTRAS_FLAGS" ]; then
        echo "  • uv extras: $UV_EXTRAS_FLAGS"
    fi
    # `--all-packages` 将 extras 传递至 workspace 成员（尤其 deerflow-harness），
    # postgres extras 依赖该行为，详见 PR #2584。此处有意不加引号以展开多个 `--extra X` 参数对。
    (cd backend && uv sync --quiet --all-packages $UV_EXTRAS_FLAGS) || { echo "✗ Backend dependency install failed"; exit 1; }
    (cd frontend && pnpm install --silent) || { echo "✗ Frontend dependency install failed"; exit 1; }
    echo "✓ Dependencies synced"
else
    echo "⏩ Skipping dependency install (--skip-install)"
fi

# ── 启动横幅 ─────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  Starting DeerFlow"
echo "=========================================="
echo ""
echo "  Mode: $MODE_LABEL"
echo ""
echo "  Services:"
echo "    Gateway     → localhost:8001  (REST API + agent runtime)"
echo "    Frontend    → localhost:3000  (Next.js)"
echo ""

# ── 清理处理器 ────────────────────────────────────────────────────────────────

# 接收信号时移除 trap 再停止服务，防止清理过程被同一信号递归打断。
cleanup() {
    local status="${1:-0}"
    trap - INT TERM
    echo ""
    stop_all
    exit "$status"
}

trap 'cleanup 130' INT
trap 'cleanup 143' TERM

# ── 服务启动辅助逻辑 ──────────────────────────────────────────────────────────

# 启动单个服务，守护模式使用 nohup，并等待指定端口就绪后才继续下游服务。
run_service() {
    local name="$1" cmd="$2" port="$3" timeout="$4"

    if _is_port_listening "$port"; then
        echo "✗ $name cannot start because port $port is already in use."
        echo "  If it belongs to this worktree, run 'make stop'; otherwise free the port manually."
        cleanup 1
    fi

    echo "Starting $name..."
    if $DAEMON_MODE; then
        # 给守护进程打标，使每个子进程（pnpm → next → next-server）均继承
        # DEERFLOW_DAEMON_ROOT，供停止时的 _is_deerflow_pid 安全识别。
        nohup env DEERFLOW_DAEMON_ROOT="$REPO_ROOT" sh -c "$cmd" > /dev/null 2>&1 &
    else
        sh -c "$cmd" &
    fi

    ./scripts/wait-for-port.sh "$port" "$timeout" "$name" || {
        local logfile="logs/$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-').log"
        echo "✗ $name failed to start."
        [ -f "$logfile" ] && tail -20 "$logfile"
        cleanup 1
    }
    echo "✓ $name started on localhost:$port"
}

# ── 启动服务 ─────────────────────────────────────────────────────────────────

mkdir -p logs

# 1. Gateway API：先启动，供后续代理健康检查使用。
run_service "Gateway" \
    "cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 $GATEWAY_EXTRA_FLAGS > ../logs/gateway.log 2>&1" \
    8001 30

# 2. Frontend：在 Gateway 启动后运行。
run_service "Frontend" \
    "cd frontend && $FRONTEND_CMD > ../logs/frontend.log 2>&1" \
    3000 120

# ── 就绪信息 ─────────────────────────────────────────────────────────────────

echo ""
echo "=========================================="
echo "  ✓ DeerFlow is running!  [$MODE_LABEL]"
echo "=========================================="
echo ""
echo "  🌐 http://localhost:3000"
echo ""
echo "  API proxy: Next.js rewrites /api/* to Gateway (8001)"
echo ""
echo "  📋 Logs: logs/{gateway,frontend}.log"
echo ""

if $DAEMON_MODE; then
    echo "  🛑 Stop: make stop"
    # 已脱离前台，后续无需保留信号清理 trap。
    trap - INT TERM
else
    echo "  Press Ctrl+C to stop all services"
    wait
fi
