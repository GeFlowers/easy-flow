# 后端 Dockerfile — 多阶段构建
# 阶段 1（builder）：使用 build-essential 编译原生 Python 扩展
# 阶段 2（dev）：保留工具链，供开发容器启动时执行 uv sync
# 阶段 3（runtime）：生产镜像不含编译工具链，减少体积与攻击面

# UV 源镜像；受限网络无法访问 ghcr.io 时可覆盖。
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7.20
FROM ${UV_IMAGE} AS uv-source

# ── 阶段 1：构建器 ────────────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ARG NODE_MAJOR=22
ARG APT_MIRROR
ARG UV_INDEX_URL
# 要安装的可选 extras（例如 PostgreSQL 支持使用 "postgres"）
# 用法：docker build --build-arg UV_EXTRAS=postgres,discord ...
ARG UV_EXTRAS

# 受限网络可选覆盖 apt 镜像（例如 APT_MIRROR=mirrors.aliyun.com）。
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# 安装构建工具与 Node.js；原生 Python 扩展需要 build-essential。
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    gnupg \
    ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv；源镜像可由 UV_IMAGE build-arg 覆盖。
COPY --from=uv-source /uv /uvx /usr/local/bin/

# 设置统一工作目录，后续 COPY 与命令均以此为边界。
WORKDIR /app

# 复制后端源码进入构建阶段。
COPY backend ./backend

# 通过缓存挂载安装依赖。Docker Compose 默认将流桥接到 Redis（DEER_FLOW_STREAM_BRIDGE_REDIS_URL），
# 故始终安装 `redis`；非 Docker 精简安装中它仍是可选项。UV_EXTRAS 存在时（逗号或空白分隔）
# 再安装指定可选依赖。
RUN --mount=type=cache,target=/root/.cache/uv \
    sh -c 'cd backend && \
    set -f; \
    extras_flags=""; \
    for extra in $(printf "%s" "$UV_EXTRAS" | tr "," " "); do \
        case "$extra" in \
            [!A-Za-z]* | *[!A-Za-z0-9_-]*) \
                echo "UV_EXTRAS entry $extra is invalid (must match [A-Za-z][A-Za-z0-9_-]*)" >&2; \
                exit 1; \
                ;; \
        esac; \
        extras_flags="$extras_flags --extra $extra"; \
    done; \
    UV_INDEX_URL=${UV_INDEX_URL:-https://pypi.org/simple} uv sync --extra redis $extras_flags'

# 在缺少 locale 配置、默认编码非 UTF-8 的精简容器中，强制 UTF-8 可避免中文/emoji 的 UnicodeEncodeError。
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# ── 阶段 2：开发 ──────────────────────────────────────────────────────────────
# 保留构建器的编译工具链，使开发容器启动时的 `uv sync` 能构建源码分发包。
FROM builder AS dev

# 安装 Docker CLI；DooD 通过宿主 Docker socket 启动沙箱容器时需要它。
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

EXPOSE 8001

CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]

# ── 阶段 3：运行时 ────────────────────────────────────────────────────────────
# 不含 build-essential 的干净镜像，可减少约 200 MB 体积和攻击面。
FROM python:3.12-slim-bookworm AS runtime

ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# 从构建器复制 Node.js 运行时，为 MCP 服务器提供 npx。
COPY --from=builder /usr/bin/node /usr/bin/node
COPY --from=builder /usr/lib/node_modules /usr/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/bin/npx

# 安装 Docker CLI；DooD 通过宿主 Docker socket 启动沙箱容器时需要它。
COPY --from=docker:cli /usr/local/bin/docker /usr/local/bin/docker

# 安装 uv；源镜像可由 UV_IMAGE build-arg 覆盖。
COPY --from=uv-source /uv /uvx /usr/local/bin/

# 设置运行时工作目录。
WORKDIR /app

# 从构建器复制后端及已构建虚拟环境，运行时不再编译依赖。
COPY --from=builder /app/backend ./backend

# 暴露 Gateway API 端口。
EXPOSE 8001

# 默认启动命令；docker-compose 可按部署拓扑覆盖。
CMD ["sh", "-c", "cd backend && PYTHONPATH=. uv run --no-sync uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001"]
