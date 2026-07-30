#!/usr/bin/env bash
#
# nginx.sh — 使用本地开发配置在前台单独启动 nginx。
#
# 与 scripts/serve.sh 保持相同的前缀、配置和预建目录，避免单独启动与完整启动的权限行为不同。
#
# 用法：make nginx（或从任意目录执行 ./scripts/nginx.sh）

set -e

REPO_ROOT="$(builtin cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd -P)"
cd "$REPO_ROOT"

mkdir -p logs
mkdir -p temp/client_body_temp temp/proxy_temp temp/fastcgi_temp temp/uwsgi_temp temp/scgi_temp

exec nginx -g 'daemon off;' -c "$REPO_ROOT/docker/nginx/nginx.local.conf" -p "$REPO_ROOT"
