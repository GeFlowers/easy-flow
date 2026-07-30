#!/usr/bin/env bash
#
# cleanup-containers.sh - 清理 DeerFlow 沙箱容器
#
# 同时处理 Docker 与 Apple Container 运行时；命令不存在时跳过，以兼容不同平台，
# 且仅按传入前缀筛选，避免误停无关容器。
#

set -e

PREFIX="${1:-deer-flow-sandbox}"

# 终端输出颜色；不影响命令的退出状态。
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # 关闭颜色

echo "Cleaning up sandbox containers with prefix: ${PREFIX}"

# 仅停止名称匹配前缀的 Docker 容器；Docker CLI 不可用时安全跳过。
cleanup_docker() {
    if command -v docker &> /dev/null; then
        echo -n "Checking Docker containers... "
        DOCKER_CONTAINERS=$(docker ps -q --filter "name=${PREFIX}" 2>/dev/null || echo "")

        if [ -n "$DOCKER_CONTAINERS" ]; then
            echo ""
            echo "Found Docker containers to clean up:"
            docker ps --filter "name=${PREFIX}" --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
            echo "Stopping Docker containers..."
            echo "$DOCKER_CONTAINERS" | xargs docker stop 2>/dev/null || true
            echo -e "${GREEN}✓ Docker containers stopped${NC}"
        else
            echo -e "${GREEN}none found${NC}"
        fi
    else
        echo "Docker not found, skipping..."
    fi
}

# 仅停止名称匹配前缀的 Apple Container 容器；该运行时不存在时安全跳过。
cleanup_apple_container() {
    if command -v container &> /dev/null; then
        echo -n "Checking Apple Container containers... "

        # 使用 JSON 列表，避免依赖面向人类的表格输出格式。
        CONTAINER_LIST=$(container list --format json 2>/dev/null || echo "[]")

        if [ "$CONTAINER_LIST" != "[]" ] && [ -n "$CONTAINER_LIST" ]; then
            # 从配置 ID 中提取匹配前缀的容器，保持与 Docker 的筛选边界一致。
            CONTAINER_IDS=$(echo "$CONTAINER_LIST" | python3 -c "
import json
import sys
try:
    containers = json.load(sys.stdin)
    if isinstance(containers, list):
        for c in containers:
            if isinstance(c, dict):
                # Apple Container uses 'id' field which contains the container name
                cid = c.get('configuration').get('id', '')
                if '${PREFIX}' in cid:
                    print(cid)
except:
    pass
" 2>/dev/null || echo "")

            if [ -n "$CONTAINER_IDS" ]; then
                echo ""
                echo "Found Apple Container containers to clean up:"
                echo "$CONTAINER_IDS" | while read -r cid; do
                    echo "  - $cid"
                done

                echo "Stopping Apple Container containers..."
                echo "$CONTAINER_IDS" | while read -r cid; do
                    container stop "$cid" 2>/dev/null || true
                done
                echo -e "${GREEN}✓ Apple Container containers stopped${NC}"
            else
                echo -e "${GREEN}none found${NC}"
            fi
        else
            echo -e "${GREEN}none found${NC}"
        fi
    else
        echo "Apple Container not found, skipping..."
    fi
}

# 依次覆盖两种运行时；其中一种失败不应阻断另一种清理。
cleanup_docker
cleanup_apple_container

echo -e "${GREEN}✓ Container cleanup complete${NC}"
