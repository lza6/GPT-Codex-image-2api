ARG BUILDPLATFORM
ARG TARGETPLATFORM
ARG TARGETARCH

FROM --platform=$BUILDPLATFORM node:22-alpine AS web-build

WORKDIR /app/web

COPY web/package.json ./
RUN npm install

COPY VERSION /app/VERSION
COPY CHANGELOG.md /app/CHANGELOG.md
COPY web ./
RUN NEXT_PUBLIC_APP_VERSION="$(cat /app/VERSION)" npm run build


FROM --platform=$TARGETPLATFORM python:3.13-slim AS app

ARG TARGETPLATFORM
ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# 安装系统依赖
# - git: Git 存储后端需要
# - libpq-dev: PostgreSQL 客户端库
# - gcc: 编译 psycopg2-binary 需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libpq-dev \
    gcc \
    openssl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY main.py ./
# D-B1：config.json 被 .gitignore 排除不在 git 树中，CI 构建时不存在。
# 用 config.example.json 兜底；用户以 volume 挂载真实 config.json 覆盖（docker-compose 已配）。
# 注意：不得写 `COPY config.json*`——glob 匹配为空在 Docker/BuildKit 直接报
# "no source files were specified"，反而让 CI 必失败（审查 HIGH-1）。
COPY config.example.json ./config.json
COPY VERSION ./
COPY api ./api
COPY services ./services
COPY utils ./utils
COPY scripts ./scripts
COPY --from=web-build /app/web/out ./web_dist

# E6/P1-4：非 root 运行——内网自用也避免容器内提权面；data/ 由 volume 挂载
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

# E6/P1-5：健康检查 + 优雅停机
# 探测端点：GET / 若返回首页（或任何 200）视为存活；4xx/连接失败均算不健康
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:80/', timeout=4).status < 400 else 1)" || exit 1

EXPOSE 80

# stop_grace_period：给 uvicorn 优雅停机时间（收尾在途请求、归还连接池）
STOPSIGNAL SIGTERM

CMD ["uv", "run", "python", "main.py"]
