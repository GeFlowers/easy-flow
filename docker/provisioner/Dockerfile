FROM python:3.12-slim-bookworm

ARG APT_MIRROR
ARG PIP_INDEX_URL

# 受限网络可选覆盖 apt 镜像（例如 APT_MIRROR=mirrors.aliyun.com）。
RUN if [ -n "${APT_MIRROR}" ]; then \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
      sed -i "s|deb.debian.org|${APT_MIRROR}|g" /etc/apt/sources.list 2>/dev/null || true; \
    fi

# 安装 provisioner 运行所需的系统依赖，并清理 apt 索引以控制镜像体积。
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 provisioner 运行依赖；可通过 PIP_INDEX_URL 适配受限网络。
RUN pip install --no-cache-dir \
    ${PIP_INDEX_URL:+--index-url "$PIP_INDEX_URL"} \
    fastapi \
    "uvicorn[standard]" \
    kubernetes

WORKDIR /app
COPY app.py .

EXPOSE 8002

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
