#!/usr/bin/env bash
# 预拉取 DeerFlow 沙箱容器镜像

set -uo pipefail

echo "=========================================="
echo "  Pre-pulling Sandbox Container Image"
echo "=========================================="
echo ""

# 尝试从 config.yaml 提取镜像，兼容已启用和被注释的 sandbox 配置节
IMAGE=""
CONFIGURED=1
if [ -f "config.yaml" ]; then
    # 查找 sandbox 配置节下未被注释的 image 字段
    IMAGE=$(grep -A 20 "^sandbox:" config.yaml 2>/dev/null | grep "^  image:" | awk '{print $2}' | head -1 || true)
fi

if [ -z "$IMAGE" ]; then
    # 注意：不要使用 :latest。镜像站的 :latest 仍指向 1.9.3 之前的旧摘要，
    # 缺少 required-secrets 技能依赖的 /v1/bash/* 路由（见 #3921/#3922）。
    # 使用该标签会失去预拉取脚本的意义，因此版本必须固定为 1.9.3 或更高。
    IMAGE="enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
    CONFIGURED=0
    echo "Using default image: $IMAGE"
else
    echo "Using configured image: $IMAGE"
fi

echo ""

if command -v container >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
    echo "Detected Apple Container on macOS, pulling image..."
    container image pull "$IMAGE" || echo "⚠ Apple Container pull failed, will try Docker"
fi

if command -v docker >/dev/null 2>&1; then
    echo "Pulling image using Docker..."
    if docker pull "$IMAGE"; then
        echo ""
        echo "✓ Sandbox image pulled successfully"
    else
        echo ""
        echo "⚠ Failed to pull sandbox image (this is OK for local sandbox mode)"
    fi
else
    echo "✗ Neither Docker nor Apple Container is available"
    echo "  Please install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi

if [ "$CONFIGURED" -eq 0 ]; then
    echo ""
    echo "⚠ NOTE: pulling this image does not make the sandbox use it."
    echo "  config.yaml has no uncommented 'sandbox.image', so AioSandboxProvider"
    echo "  falls back to its own built-in default at runtime, which is still"
    echo "  pinned to ':latest' (frozen on an old pre-1.9.3 digest — see #3921)."
    echo "  To actually run on $IMAGE, add it explicitly:"
    echo ""
    echo "    sandbox:"
    echo "      image: $IMAGE"
fi
