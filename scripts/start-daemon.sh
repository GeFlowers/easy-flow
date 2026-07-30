#!/usr/bin/env bash
#
# start-daemon.sh — 以守护（后台）模式启动 DeerFlow。
#
# 仅封装 serve.sh --daemon；保留该入口以兼容既有自动化调用。

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$REPO_ROOT/scripts/serve.sh" --dev --daemon "$@"
