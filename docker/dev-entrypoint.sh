#!/usr/bin/env sh
#
# DeerFlow Gateway 开发入口——运行于 docker-compose-dev 的 gateway 容器中。
# 由 docker/docker-compose-dev.yaml 的内联 `command:` 提取（PR #2767，回应 Issue #2754 的评审）。
#
# 职责：
#   1. 从 UV_EXTRAS 解析 `--extra X` 参数（逗号或空白分隔），与本地 `make dev` 的
#      scripts/detect_uv_extras.py 保持一致。
#   2. 用 [A-Za-z][A-Za-z0-9_-]* 校验每个 extra，防止 `.env` 中的 Shell 元字符进入 `uv sync`。
#   3. 执行 `uv sync --all-packages`，确保 workspace 成员的 extras（尤其 deerflow-harness 的
#      postgres extra）被安装，详见 PR #2584。
#   4. 自愈：首次同步失败时重建 .venv 并仅重试一次。
#   5. 将进程交给带热重载的 uvicorn，以替换当前 Shell 并令 uvicorn 成为容器 PID 1。
#
# 固定使用 /bin/sh 而非 bash，因为 Alpine 基础镜像可能没有 bash；全程仅使用 POSIX 语法。

set -e

# `--print-extras` 是试运行入口：解析并校验 UV_EXTRAS，将得到的 `--extra X` 参数输出到
# stdout 后退出。它供 backend/tests/test_dev_entrypoint.py 单测与临时排障使用。
PRINT_EXTRAS_ONLY=0
if [ "${1:-}" = "--print-extras" ]; then
    PRINT_EXTRAS_ONLY=1
fi

# 保持旧命令行为：将 stdout 和 stderr 同时重定向至宿主挂载日志文件
# （../logs/gateway.log → /app/logs/gateway.log）。--print-extras 时不重定向，
# 以便测试运行器捕获 stdout。
if [ "$PRINT_EXTRAS_ONLY" = "0" ]; then
    exec >/app/logs/gateway.log 2>&1
fi

# ── 解析 extras ─────────────────────────────────────────────────────────────

EXTRAS_FLAGS=""
if [ -n "${UV_EXTRAS:-}" ]; then
    # 先将逗号规范为空格，再通过未加引号的 `for` 按空白拆分。
    for raw in $(printf '%s' "$UV_EXTRAS" | tr ',' ' '); do
        [ -z "$raw" ] && continue
        # 拒绝非标识符形式的值：首字符非字母，或包含非 [A-Za-z0-9_-] 字符。
        case "$raw" in
            [!A-Za-z]* | *[!A-Za-z0-9_-]*)
                echo "[startup] UV_EXTRAS entry '$raw' is invalid (must match [A-Za-z][A-Za-z0-9_-]*) — aborting" >&2
                exit 1
                ;;
        esac
        EXTRAS_FLAGS="$EXTRAS_FLAGS --extra $raw"
    done
fi

if [ "$PRINT_EXTRAS_ONLY" = "1" ]; then
    # 移除前导空格后输出并退出，保持试运行结果整洁。
    printf '%s\n' "${EXTRAS_FLAGS# }"
    exit 0
fi

if [ -n "$EXTRAS_FLAGS" ]; then
    echo "[startup] uv extras:$EXTRAS_FLAGS"
fi

# 将运行时自有文件排除在 uvicorn 热重载监听之外。每个排除路径必须在 uvicorn 启动前存在，
# 才会被 watchfiles 识别为目录而非普通 glob；Python 3.12 对绝对 glob 会抛出
# NotImplementedError 并导致启动崩溃（#3459 / #3454）。因此此处也必须创建 `sandbox`，
# 而不能只创建 `.deer-flow`。
: "${DEER_FLOW_HOME:=/app/backend/.deer-flow}"
export DEER_FLOW_HOME
mkdir -p "$DEER_FLOW_HOME" /app/backend/.deer-flow /app/backend/sandbox

# ── 同步依赖（带自愈） ────────────────────────────────────────────────────────

cd /app/backend

# `--all-packages` 将 extras 传递至 workspace 成员（PR #2584）。docker-compose-dev
# 默认将流桥接至 Redis（DEER_FLOW_STREAM_BRIDGE_REDIS_URL），故始终安装 `--extra redis`；
# 它在其他部署中仍是可选项。为保持 --print-extras 仅输出 UV_EXTRAS 派生参数的契约，
# redis 不放入 EXTRAS_FLAGS。`$EXTRAS_FLAGS` 有意不加引号，使每个 `--extra X` 成为独立参数。
# shellcheck disable=SC2086 # word-splitting is intentional here
if ! uv sync --all-packages --extra redis $EXTRAS_FLAGS; then
    echo "[startup] uv sync failed; recreating .venv and retrying once"
    uv venv --allow-existing .venv
    # shellcheck disable=SC2086
    uv sync --all-packages --extra redis $EXTRAS_FLAGS
fi

# ── 交由 uvicorn 接管 ────────────────────────────────────────────────────────

PYTHONPATH=. exec uv run uvicorn app.gateway.app:app \
    --host 0.0.0.0 --port 8001 \
    --reload \
    --reload-include='*.yaml' \
    --reload-include='.env' \
    --reload-exclude=/app/backend/sandbox \
    --reload-exclude="$DEER_FLOW_HOME" \
    --reload-exclude=/app/backend/.deer-flow
