#!/usr/bin/env bash
# 正常关闭本项目的前后端和数据库容器，保留数据库卷。
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf '用法：bash scripts/stop.sh\n' >&2
  exit 2
fi

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$PROJECT_ROOT/backend/.venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
  printf '缺少后端虚拟环境，无法安全验证进程身份。\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT/backend"
"$PYTHON" -X utf8 -m server.local_services stop
cd "$PROJECT_ROOT"
docker compose --env-file "$PROJECT_ROOT/.env" -p deer-flow-dev -f "$PROJECT_ROOT/deploy/postgres/compose.yaml" stop postgres
