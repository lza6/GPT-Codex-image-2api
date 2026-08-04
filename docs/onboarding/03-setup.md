# 03 · 本地环境搭建（Windows）

> 目标：从 clone 到跑通测试 + 服务起来，约 10 分钟。macOS/Linux 跳过 bat 部分，直接用命令行。

## 前置要求（精确版本）

| 依赖 | 版本 | 验证命令 |
|------|------|---------|
| Python | **≥ 3.13**（pyproject `requires-python` 锁定） | `python --version` |
| uv | 最新 | `uv --version`（无则 `pip install uv`） |
| Node.js | ≥ 20（前端才需要；CI 用 Node 20，Docker 用 22-alpine） | `node --version` |
| Docker | 可选（容器部署才需要） | `docker --version` |

## 步骤

```bash
# 1. 克隆
git clone <内部仓库地址> chatgpt2api && cd chatgpt2api

# 2. 后端依赖（自动创建 .venv，走阿里云镜像源 —— pyproject 已配）
uv sync

# 3. 配置文件（仓库不提交 config.json，首次自行创建）
#    最小配置：{"auth-key": "本地开发随便填，≥12 位"}
#    完整字段参考 .env.example 或问项目方要一份脱敏版
cp .env.example .env   # 可选：环境变量方式覆盖

# 4. 验证测试（默认排除 live/redis，不触网）
uv run pytest

# 5. 启动服务
uv run python main.py
# → http://localhost:23456        （API + 已构建前端 web_dist/）
# → http://localhost:23456/docs   （Swagger）

# 6. 前端（仅当任务涉及 web/）
cd web && npm install && npm run dev
# → http://localhost:3000 （dev 模式，0.0.0.0 监听）
```

## Windows 一键启动（替代步骤 5）

双击 `启动chatgpt2api.bat` —— 自动检测 Python/uv、清理 23456 残留进程、崩溃自动重启（N1/N2 节点）。停止用 `停止chatgpt2api.bat`。

⚠️ 不要用编辑器重存这两个 bat 文件：必须保持 **GBK + CRLF + 无 BOM**（`chcp 65001` 会破坏中文显示）。

## Docker 三套 compose

| 文件 | 用途 | 关键差异 |
|------|------|---------|
| `docker-compose.yml` | 生产部署 | 拉 `ghcr.io/basketikun/chatgpt2api:latest`，STORAGE_BACKEND=json |
| `docker-compose.local.yml` | 本地构建验证 | 本地 build，STORAGE_BACKEND=sqlite + `DATABASE_URL=sqlite:////app/data/accounts.db` |
| `docker-compose.warp.yml` | CF 清障 | init-config 初始化 proxy_runtime + WARP/Privoxy/FlareSolverr 清障链 |

```bash
docker compose up -d                    # 生产镜像，23456:80
docker compose -f docker-compose.local.yml up -d --build   # 本地构建验证
```

挂载点：`./data:/app/data`（运行时数据）+ `./config.json:/app/config.json`（配置，**不烤进镜像**）。

## 环境变量全表

### 核心

| 变量 | 必填 | 说明 |
|------|------|------|
| `CHATGPT2API_AUTH_KEY` | ✅ | API 认证密钥；production 下 <12 位拒绝启动（建议 ≥24 位强随机） |
| `STORAGE_BACKEND` | 否 | `json`（默认）/ `sqlite` / `postgres` / `git` |
| `DATABASE_URL` | 条件必填 | sqlite/postgres 后端时；如 `postgresql://user:pass@host:5432/db`、`sqlite:////app/data/accounts.db` |
| `GIT_REPO_URL` / `GIT_TOKEN` / `GIT_BRANCH` / `GIT_FILE_PATH` | git 后端必填 | Git 存储后端四件套 |
| `CHATGPT2API_BASE_URL` | 否 | 生成图片 URL 用的外部地址 |
| `CHATGPT2API_ENV` | 否 | `development`（默认）/ `production`；production 强制强 auth-key + CORS=* 警告 |
| `CHATGPT2API_CORS_ORIGINS` | 否 | 逗号分隔，默认 `*`；生产建议显式收紧 |

### 调度与限流（覆盖 config.json）

| 变量 | 默认 | 说明 |
|------|------|------|
| `CHATGPT2API_SCHEDULER_MODE` | round_robin | 调度模式：`round_robin` / `remaining_quota` |
| `CHATGPT2API_RATE_LIMIT_RPM` | 0（不限） | 全局每分钟请求数上限 |
| `CHATGPT2API_RATE_LIMIT_PER_IP_RPM` | 0（不限） | 单 IP 每分钟请求数上限 |
| `CHATGPT2API_WORKERS` | 1 | Worker 进程数；>1 要求 sqlite/postgres 后端 |

### 代理运行时与 CF 清障（`scripts/init_proxy_config.py` 写入 config.json）

| 变量 | 默认 | 说明 |
|------|------|------|
| `CHATGPT2API_PROXY_RUNTIME_ENABLED` | true | 代理运行时开关 |
| `CHATGPT2API_PROXY_RUNTIME_EGRESS_MODE` | single_proxy | 出口模式 |
| `CHATGPT2API_PROXY_RUNTIME_PROXY_URL` | `http://privoxy:8118` | 主代理 |
| `CHATGPT2API_PROXY_RUNTIME_RESET_STATUS_CODES` | 403 | 触发会话重置的上游状态码 |
| `CHATGPT2API_PROXY_RUNTIME_CLEARANCE_ENABLED` | true | CF clearance 刷新开关 |
| `CHATGPT2API_PROXY_RUNTIME_CLEARANCE_MODE` | flaresolverr | 清障模式 |
| `CHATGPT2API_FLARESOLVERR_URL` | `http://flaresolverr:8191` | FlareSolverr 地址 |
| `CHATGPT2API_CONFIG_FILE` | `/app/config.json` | init 脚本写入目标 |
| `WARP_LICENSE_KEY` | 空 | Cloudflare WARP+ License（可选） |

### 备份

| 变量 | 说明 |
|------|------|
| config.json `backup.passphrase` | 备份加解密口令（OpenSSL + HMAC；CHATGPT2API_BACKUP_PASSPHRASE 为内部子进程传参，勿直接设置） |

## 验收清单（全绿才算搭好）

- [ ] `uv run pytest` 通过（会有 skip，无 fail/error；4 个 image_tasks_api 全量跑偶发失败为已知竞态，单独跑应全过）
- [ ] `curl http://localhost:23456/v1/models -H "Authorization: Bearer <auth-key>"` 返回 200
- [ ] `curl "http://localhost:23456/metrics?token=<auth-key>"` 有 Prometheus 文本输出（v2.0.0 起 /metrics 需鉴权，裸 curl 返回 401 是**正确**行为）
- [ ] `curl http://localhost:23456/api/storage/info -H "Authorization: Bearer <auth-key>"` 能看到当前后端类型
- [ ] （前端任务）`cd web && npm run build` 成功（webpack，产物到 `web/out` + `web_dist/`）

## 常见搭建问题

| 症状 | 解法 |
|------|------|
| `uv sync` 拉包慢 | pyproject 已配阿里云镜像；公司网再配 `UV_INDEX_URL` |
| 启动报 schema 校验错 | 错误信息带 config.json 行号，按行号修；多半是手抖改了字段名 |
| 启动警告 "workers 回退到 1" | `STORAGE_BACKEND=json` 却配了 workers>1；换 sqlite/postgres 或接受单 worker |
| 端口被占 | 跑 `停止chatgpt2api.bat`，或 `netstat -ano \| findstr :23456` 找到 PID 杀掉 |
| bat 启动中文乱码 | 文件被编辑器转成了 UTF-8，用项目方原版恢复 |
| 前端构建失败（中文路径） | 已知问题：Turbopack 在中文路径下失败，构建已固定 `next build --webpack`，别改回 |
