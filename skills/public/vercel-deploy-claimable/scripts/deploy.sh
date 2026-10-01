#!/bin/bash

# Vercel 部署脚本（经由可认领部署端点）
# 用法：./deploy.sh [project-path]
# 返回：包含 previewUrl、claimUrl、deploymentId、projectId 的 JSON

set -e

DEPLOY_ENDPOINT="https://claude-skills-deploy.vercel.com/api/deploy"

# 根据 package.json 识别框架；按特异性排序以避免通用依赖抢先匹配。
detect_framework() {
    local pkg_json="$1"

    if [ ! -f "$pkg_json" ]; then
        echo "null"
        return
    fi

    local content=$(cat "$pkg_json")

    # 检查依赖或开发依赖中是否出现指定包名。
    has_dep() {
        echo "$content" | grep -q "\"$1\""
    }

    # 匹配顺序有语义：先检查更具体的框架。

    if has_dep "blitz"; then echo "blitzjs"; return; fi

    if has_dep "next"; then echo "nextjs"; return; fi

    if has_dep "gatsby"; then echo "gatsby"; return; fi

    if has_dep "@remix-run/"; then echo "remix"; return; fi

    if has_dep "@react-router/"; then echo "react-router"; return; fi

    if has_dep "@tanstack/start"; then echo "tanstack-start"; return; fi

    if has_dep "astro"; then echo "astro"; return; fi

    if has_dep "@shopify/hydrogen"; then echo "hydrogen"; return; fi

    if has_dep "@sveltejs/kit"; then echo "sveltekit-1"; return; fi

    if has_dep "svelte"; then echo "svelte"; return; fi

    if has_dep "nuxt"; then echo "nuxtjs"; return; fi

    if has_dep "vitepress"; then echo "vitepress"; return; fi

    if has_dep "vuepress"; then echo "vuepress"; return; fi

    if has_dep "gridsome"; then echo "gridsome"; return; fi

    if has_dep "@solidjs/start"; then echo "solidstart-1"; return; fi

    if has_dep "@docusaurus/core"; then echo "docusaurus-2"; return; fi

    if has_dep "@redwoodjs/"; then echo "redwoodjs"; return; fi

    if has_dep "hexo"; then echo "hexo"; return; fi

    if has_dep "@11ty/eleventy"; then echo "eleventy"; return; fi

    if has_dep "@ionic/angular"; then echo "ionic-angular"; return; fi
    if has_dep "@angular/core"; then echo "angular"; return; fi

    if has_dep "@ionic/react"; then echo "ionic-react"; return; fi

    if has_dep "react-scripts"; then echo "create-react-app"; return; fi

    if has_dep "ember-cli" || has_dep "ember-source"; then echo "ember"; return; fi

    if has_dep "@dojo/framework"; then echo "dojo"; return; fi

    if has_dep "@polymer/"; then echo "polymer"; return; fi

    if has_dep "preact"; then echo "preact"; return; fi

    if has_dep "@stencil/core"; then echo "stencil"; return; fi

    if has_dep "umi"; then echo "umijs"; return; fi

    if has_dep "sapper"; then echo "sapper"; return; fi

    if has_dep "saber"; then echo "saber"; return; fi

    if has_dep "sanity"; then echo "sanity-v3"; return; fi
    if has_dep "@sanity/"; then echo "sanity"; return; fi

    if has_dep "@storybook/"; then echo "storybook"; return; fi

    if has_dep "@nestjs/core"; then echo "nestjs"; return; fi

    if has_dep "elysia"; then echo "elysia"; return; fi

    if has_dep "hono"; then echo "hono"; return; fi

    if has_dep "fastify"; then echo "fastify"; return; fi

    if has_dep "h3"; then echo "h3"; return; fi

    if has_dep "nitropack"; then echo "nitro"; return; fi

    if has_dep "express"; then echo "express"; return; fi

    if has_dep "vite"; then echo "vite"; return; fi

    if has_dep "parcel"; then echo "parcel"; return; fi

    # 没有识别出框架时显式返回 null，交由部署端采用默认处理。
    echo "null"
}

# 解析输入路径；默认将当前目录作为部署根。
INPUT_PATH="${1:-.}"

# 创建临时打包目录；cleanup 只删除本脚本创建的目录。
TEMP_DIR=$(mktemp -d)
TARBALL="$TEMP_DIR/project.tgz"
CLEANUP_TEMP=true

# 退出时回收临时目录；输入本就是 tarball 时不删除调用方文件。
cleanup() {
    if [ "$CLEANUP_TEMP" = true ]; then
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

echo "Preparing deployment..." >&2

# 识别输入是现有 .tgz 还是目录，只有目录才打包并可识别框架。
FRAMEWORK="null"

if [ -f "$INPUT_PATH" ] && [[ "$INPUT_PATH" == *.tgz ]]; then
    echo "Using provided tarball..." >&2
    TARBALL="$INPUT_PATH"
    CLEANUP_TEMP=false
elif [ -d "$INPUT_PATH" ]; then
    PROJECT_PATH=$(cd "$INPUT_PATH" && pwd)

    FRAMEWORK=$(detect_framework "$PROJECT_PATH/package.json")

    if [ ! -f "$PROJECT_PATH/package.json" ]; then
        HTML_FILES=$(find "$PROJECT_PATH" -maxdepth 1 -name "*.html" -type f)
        HTML_COUNT=$(echo "$HTML_FILES" | grep -c . || echo 0)

        if [ "$HTML_COUNT" -eq 1 ]; then
            HTML_FILE=$(echo "$HTML_FILES" | head -1)
            BASENAME=$(basename "$HTML_FILE")
            if [ "$BASENAME" != "index.html" ]; then
                echo "Renaming $BASENAME to index.html..." >&2
                mv "$HTML_FILE" "$PROJECT_PATH/index.html"
            fi
        fi
    fi

    echo "Creating deployment package..." >&2
    tar -czf "$TARBALL" -C "$PROJECT_PATH" --exclude='node_modules' --exclude='.git' .
else
    echo "Error: Input must be a directory or a .tgz file" >&2
    exit 1
fi

if [ "$FRAMEWORK" != "null" ]; then
    echo "Detected framework: $FRAMEWORK" >&2
fi

echo "Deploying..." >&2
RESPONSE=$(curl -s -X POST "$DEPLOY_ENDPOINT" -F "file=@$TARBALL" -F "framework=$FRAMEWORK")

if echo "$RESPONSE" | grep -q '"error"'; then
    ERROR_MSG=$(echo "$RESPONSE" | grep -o '"error":"[^"]*"' | cut -d'"' -f4)
    echo "Error: $ERROR_MSG" >&2
    exit 1
fi

PREVIEW_URL=$(echo "$RESPONSE" | grep -o '"previewUrl":"[^"]*"' | cut -d'"' -f4)
CLAIM_URL=$(echo "$RESPONSE" | grep -o '"claimUrl":"[^"]*"' | cut -d'"' -f4)

if [ -z "$PREVIEW_URL" ]; then
    echo "Error: Could not extract preview URL from response" >&2
    echo "$RESPONSE" >&2
    exit 1
fi

echo "" >&2
echo "Deployment successful!" >&2
echo "" >&2
echo "Preview URL: $PREVIEW_URL" >&2
echo "Claim URL:   $CLAIM_URL" >&2
echo "" >&2

echo "$RESPONSE"
