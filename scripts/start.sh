#!/usr/bin/env bash
# 启动项目数据库及本机前后端；不进行依赖安装、构建或数据清理。
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf '用法：bash scripts/start.sh\n' >&2
  exit 2
fi

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
PYTHON="$PROJECT_ROOT/backend/.venv/Scripts/python.exe"
if [ ! -f "$PYTHON" ]; then
  printf '缺少后端虚拟环境，请先安装项目依赖。\n' >&2
  exit 1
fi

cd "$PROJECT_ROOT"
docker compose --env-file "$PROJECT_ROOT/.env" -p deer-flow-dev -f "$PROJECT_ROOT/deploy/postgres/compose.yaml" up -d --no-recreate --wait postgres
cd "$PROJECT_ROOT/backend"
"$PYTHON" -X utf8 -m server.local_services start
