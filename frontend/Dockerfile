# 前端 Dockerfile
# 构建 Next.js 生产产物，并提供精简运行时镜像。

ARG PNPM_STORE_PATH=/root/.local/share/pnpm/store
ARG NPM_REGISTRY

# ── 基础阶段：共享设置 ────────────────────────────────────────────────────────
FROM node:22-alpine AS base
ARG PNPM_STORE_PATH
ARG NPM_REGISTRY
# 在安装 pnpm 前配置 corepack registry，使受限网络中的包管理器下载也能成功；
# COREPACK_NPM_REGISTRY 控制 corepack 获取包管理器的位置。
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      export COREPACK_NPM_REGISTRY="${NPM_REGISTRY}"; \
    fi && \
    corepack enable && corepack install -g pnpm@10.26.2
RUN pnpm config set store-dir ${PNPM_STORE_PATH}
# 受限网络可选覆盖 npm registry（例如 NPM_REGISTRY=https://registry.npmmirror.com）。
RUN if [ -n "${NPM_REGISTRY}" ]; then pnpm config set registry "${NPM_REGISTRY}"; fi
WORKDIR /app
COPY frontend ./frontend

# ── 构建阶段：安装并编译 Next.js ──────────────────────────────────────────────
FROM base AS builder
RUN cd /app/frontend && pnpm install --frozen-lockfile
# 跳过环境变量校验；运行时变量由 nginx/容器注入。
# About 页面使用的应用版本标记。夜间 CI 传入
# APP_VERSION=<base>-nightly.<date>-<sha>；发布/本地构建留空，前端回退到 package.json 的版本。
ARG APP_VERSION=""
ENV NEXT_PUBLIC_APP_VERSION=$APP_VERSION
RUN cd /app/frontend && SKIP_ENV_VALIDATION=1 pnpm build

# ── 生产阶段：使用预构建产物的最小运行时 ──────────────────────────────────────
FROM node:22-alpine AS prod
ARG PNPM_STORE_PATH
ARG NPM_REGISTRY
RUN if [ -n "${NPM_REGISTRY}" ]; then \
      export COREPACK_NPM_REGISTRY="${NPM_REGISTRY}"; \
    fi && \
    corepack enable && corepack install -g pnpm@10.26.2
RUN pnpm config set store-dir ${PNPM_STORE_PATH}
RUN if [ -n "${NPM_REGISTRY}" ]; then pnpm config set registry "${NPM_REGISTRY}"; fi
WORKDIR /app
COPY --from=builder /app/frontend ./frontend
EXPOSE 3000
CMD ["sh", "-c", "cd /app/frontend && pnpm exec next start"]
