<h1 align="center">ChatGPT2API</h1>


<p align="center">ChatGPT2API 主要是对 ChatGPT 官网相关能力进行逆向整理与封装，提供面向 ChatGPT 图片生成、图片编辑、多图组图编辑场景的 OpenAI 兼容图片 API / 代理，并集成在线画图、号池管理、智能调度系统、多级限流、运维看板、多种账号导入方式与 Docker 自托管部署能力，支持 Windows 一键启动。</p>

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 严禁将本项目用于生成、传播或协助生成违法、暴力、色情、未成年人相关内容，或用于诈骗、欺诈、骚扰等非法或不当用途。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 使用本项目即视为你已充分理解并同意本免责声明全部内容；如因滥用、违规或违法使用造成任何后果，均由使用者自行承担。
> - 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用你自己的重要账号、常用账号或高价值账号进行测试。


## 功能一览

| 功能 | 状态 | 说明 |
|------|------|------|
| OpenAI 兼容 API | ✅ | `/v1/images/generations`、`/v1/images/edits`、`/v1/chat/completions`、`/v1/responses` |
| 在线画图工作台 | ✅ | 文生图、图生图、多图组图、编辑模式 |
| 号池管理 | ✅ | 导入/刷新/状态机/自动移除/健康档位调度 |
| 智能调度系统 | ✅ | 健康档位（healthy/warm/risky）+ 调度分 + 双模式 |
| 运维看板 | ✅ | 调度健康度、资源占用、用量统计、账号排行榜 |
| 代理池 | ✅ | 多代理管理、健康检查、自动隔离恢复 |
| 多 Worker 并发 | ✅ | 支持多进程利用多核 CPU（需 SQLite/Postgres） |
| Windows 一键启动 | ✅ | 启动/停止 bat 脚本，自动检测环境 |
| 存储后端 | ✅ | JSON / SQLite / PostgreSQL / Git |

## 升级到 2.1

v2.1.0 引入安全边界收紧（SSRF/文件下载/XFF）与韧性收口，**含 breaking changes**，升级前必读：

| 变更 | 影响 | 迁移动作 |
|------|------|---------|
| **SSRF 防护（图片抓取路径保留）** | 图片 URL 抓取前仍有协议白名单 + 内网 IP 校验（`services/ssrf_guard.py`，`api/image_inputs.py:261` 消费） | 默认拒绝内网；确需内网图床用 `CHATGPT2API_SSRF_ALLOW_PRIVATE_IPS=true` |
| **文件下载鉴权** | `/files/{path}` 需 auth-key（原公开端点） | 调用方请求头带 `Authorization: Bearer <auth-key>` |
| **XFF 伪造防护（已移除）** | v2.1.1 移除 XFF 处理；限流中间件在 v2.3.0 已重新接线（`api/app.py` S-R15），默认关闭 | 无需任何操作 |
| **账号导出时区** | 导出文件 `expired`/`last_refresh` 从 UTC+8 改 UTC ISO8601 | 解析导出文件方按 UTC 处理 |

**v2.1.1 新变化（当前状态）：**
- **性能优先**：移除 SecurityHeadersMiddleware/RequestSizeLimitMiddleware/MetricsMiddleware，减少中间件层数（限流已在 v2.3.0 重新接线；SSRF 校验保留在图片抓取路径）
- **企业内网场景**：CORS 默认 `*`，弱口令/密钥强度由配置在 production 下强制（弱口令拒绝启动）

## 升级到 2.0

v2.0.0 引入生产级安全默认值收紧与韧性闭环，**含 breaking changes**，升级前必读：

| 变更 | 影响 | 迁移动作 |
|------|------|---------|
| **CORS 默认收紧** | `config.cors_origins` 原默认 `["*"]`，生产环境（`CHATGPT2API_ENV=production`）下 `*` 启动告警 | 显式配置域名白名单，如 `"cors_origins": ["https://your-domain.com"]` |
| **`/metrics` 需鉴权** | Prometheus 端点不再公网匿名可访问 | 抓取时带 `Authorization: Bearer <auth-key>` 或 `?token=<auth-key>` |
| **活测试标记** | 需真实上游/活服务的测试默认排除 | 本地跑全量测试用 `pytest -m live` |
| **弱口令检测** | production 下 auth-key 为常见弱口令或 <12 位拒绝启动 | 设置强 auth-key |

**v2.0.0 新能力：**
- **TLS 连接池接入主流量**：上游调用与账号 OAuth 刷新复用池化 Session，消除每请求 TLS 握手
- **统一重试预算**：幂等 GET 指数退避、流式首字节前换号、流式开始后绝不重试（防重复扣费/出图）
- **上游熔断 + 熔断状态可视化**：账号页熔断列实时标注熔断中/半开账号，支持一键驱逐失效 token
- **统一错误反馈**：401 跳登录、429 限流提示、5xx 错误带 request-id，SSE 页面隐藏自动暂停
- **CI 质量门**：GitHub Actions 硬门（pytest + 前端 tsc/build）+ 软门提示（ruff/mypy/pip-audit 宽限分期偿还）+ 本地五道防线（`scripts/run_all_guards.py`：契约/SQL/慢查询/变异/压测）

## 架构图

```
┌──────────────────────────────────────────────────┐
│                   客户端                          │
│  OpenAI SDK / Cherry Studio / curl / Claude Code  │
└────────────┬────────────────────────────┬─────────┘
             │ Bearer Token               │
             ▼                            ▼
┌──────────────────────────────────────────────────┐
│           FastAPI 网关 (api/)                     │
│  ┌──────┬──────┬──────┬──────┬──────┬─────────┐ │
│  │ AI   │账号  │看板  │图片  │系统  │  CORS   │ │
│  └──────┴──────┴──────┴──────┴──────┴─────────┘ │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│           业务服务层 (services/)                   │
│  ┌──────────┬──────────┬──────────┬────────────┐ │
│  │账号池    │代理池    │智能调度  │ 图片任务   │ │
│  │(account) │(proxy)   │(scheduler)│ (image)   │ │
│  ├──────────┼──────────┼──────────┼────────────┤ │
│  │配置管理  │日志服务  │备份服务  │ 认证服务   │ │
│  └──────────┴──────────┴──────────┴────────────┘ │
└──────────────────────┬───────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────┐
│           存储层 (services/storage/)               │
│     JSON / SQLite / PostgreSQL / Git              │
└──────────────────────────────────────────────────┘
```

## 快速开始

> **新加入开发者 / AI 编码助手**：先读 [`docs/onboarding/README.md`](docs/onboarding/README.md)（60 秒速览 + 全套新人文档索引）；AI 助手再读 `.claude/skills/chatgpt2api-workflow/SKILL.md`（工作流与验收门禁）。改完代码跑 `scripts/run_all_guards.py` 做五道防线回归。

### Windows 一键启动（推荐）

首次运行先初始化配置（v2.1.0 起 `config.json` 不再入库，只有脱敏的 `config.example.json`）：

```bash
cp config.example.json config.json
# 编辑 config.json，把 auth-key 改为强随机值（≥24 位）
```

双击 `启动chatgpt2api.bat` 即可启动（自动检测 Python/uv、清理残留进程、崩溃自动重启）。
停止用 `停止chatgpt2api.bat`，或直接关闭启动窗口（自动清理进程与端口）。

### Docker 运行

```bash
# 本项目为内部定制化部署，从内部代码仓库获取源码后：
cd chatgpt2api
docker compose up -d
```

启动前先 `cp config.example.json config.json` 并设置强随机 `auth-key`（≥24 位，生产环境弱口令会拒绝启动），
也可以通过环境变量 `CHATGPT2API_AUTH_KEY` 覆盖。

- Web 面板：`http://localhost:23456`
- API 地址：`http://localhost:23456/v1`
- 运维看板：`http://localhost:23456/dashboard`（调度健康度/资源占用/用量/延迟，SSE 实时推送）
- 数据目录：`./data`

### WARP / FlareSolverr 稳定代理部署

如果图片链路经常遇到 Cloudflare 拦截，可以启用附带的 WARP + Privoxy + FlareSolverr 方案：

```bash
cp .env.example .env
docker compose -f docker-compose.warp.yml up -d --build
```

该 compose 会启动：

- `warp-proxy`：提供 WARP SOCKS5 出口。
- `privoxy`：把 WARP SOCKS5 转成 HTTP 代理。
- `flaresolverr`：刷新 Cloudflare clearance。
- `init-config`：幂等写入 `proxy_runtime` 默认配置。
- `app`：启动 ChatGPT2API 主服务。

默认只让上游 OpenAI / ChatGPT 请求走稳定代理，账号邮箱、CPA 等辅助链路不会被强制接管。账号自身配置的代理优先级最高，其次是稳定代理运行时，再其次是显式代理和旧版全局代理。

可在 `.env` 中调整端口和代理运行时参数，也可在后台设置页的「稳定代理运行时」面板手动保存、测试代理和测试 clearance。

### 本地开发

启动后端（项目根目录）：

```bash
uv sync
uv run main.py
```

启动前端（开发模式）：

```bash
cd web
npm install
npm run dev
```

生产构建前端（webpack，注意必须用 `--webpack`，Turbopack 在中文路径下会崩溃）：

```bash
cd web
npm run build
```

### 存储后端配置

支持通过环境变量 `STORAGE_BACKEND` 切换存储方式：

- `json` - 本地 JSON 文件（默认）
- `sqlite` - 本地 SQLite 数据库
- `postgres` - 外部 PostgreSQL（需配置 `DATABASE_URL`）
- `git` - Git 私有仓库（需配置 `GIT_REPO_URL` 和 `GIT_TOKEN`）

示例：使用 PostgreSQL

```yaml
environment:
  - STORAGE_BACKEND=postgres
  - DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## 功能

### API 兼容能力

- 兼容 `POST /v1/images/generations` 图片生成接口
- 兼容 `POST /v1/images/edits` 图片编辑接口
- 兼容面向图片场景的 `POST /v1/chat/completions`
- 兼容面向图片场景的 `POST /v1/responses`
- `GET /v1/models` 返回 `gpt-image-2`、`codex-gpt-image-2`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、
  `gpt-5-mini`
- 支持通过 `n` 返回多张生成结果
- 支持生成可编辑 PPT 文件
- 支持生成可编辑 PSD 文件
- 支持 Codex 中的画图接口逆向，仅 `Plus` / `Team` / `Pro` 订阅可用，模型别名为 `codex-gpt-image-2`，如有需要可自行在其他场景映射回
  `gpt-image-2`，用于和官网画图区分；也就意味着同一账号会同时有官网和 Codex 两份生图额度

### 在线画图功能

- 内置在线画图工作台，支持生成、图片编辑与多图组图编辑
- 支持 `gpt-image-2`、`codex-gpt-image-2`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` 模型选择
- 编辑模式支持参考图上传
- 前端支持多图生成交互
- 本地保存图片会话历史，支持回看、删除和清空
- 支持服务端缓存图片URL
- 图片生成进度追踪，超时后可继续等待
- 图片懒加载与滚动位置记忆，优化大量图片场景性能

### 号池管理功能

- 自动刷新账号邮箱、类型、额度和恢复时间（异步进度追踪）
- 轮询可用账号执行图片生成与图片编辑
- 遇到 Token 失效类错误时自动剔除无效 Token
- 智能调度系统：健康档位（healthy/warm/risky）+ 调度分 + 账号级优先级 + 双模式（round_robin / remaining_quota）
- 多级限流：全局 RPM + 单 IP RPM 限流中间件
- 运维看板：调度健康度、资源占用、用量统计、账号排行榜
- 多 Worker 并发：支持配置多进程利用多核 CPU
- 定时检查限流账号并自动刷新
- 支持密码重新登录恢复异常账号，刷新后可自动重登
- 支持网页端配置全局 HTTP / HTTPS / SOCKS5 / SOCKS5H 代理
- 支持 WARP / FlareSolverr 稳定代理运行时
- 支持搜索、筛选、批量刷新、导出、手动编辑和清理账号
- 支持四种导入方式：本地 CPA JSON 文件导入、远程 CPA 服务器导入、`sub2api` 服务器导入、`access_token` 导入
- 支持在设置页配置 `sub2api` 服务器，筛选并批量导入其中的 OpenAI OAuth 账号

### 生产部署建议

#### 多 Worker 部署

```yaml
# docker-compose.yml 中设置环境变量
environment:
  - STORAGE_BACKEND=sqlite        # 多 Worker 必须使用共享存储！
  - DATABASE_URL=sqlite:////app/data/accounts.db
  - CHATGPT2API_WORKERS=4          # 建议设为 CPU 核心数
```

> **⚠️ 重要**：workers > 1 时**必须使用 SQLite 或 Postgres 存储后端**，否则各进程持有独立账号副本导致数据混乱。
> JSON 存储后端会自动回退到 workers=1 并给出警告。

#### 限流配置（已接线，默认 0 = 关闭）

`rate_limit_rpm` / `rate_limit_per_ip_rpm` 已接线到 `RateLimitMiddleware`（v2.3.0 起恢复注册）。
- `0`（默认）= 关闭限流；
- 设为正整数 N 表示全局 / 单 IP 每分钟最多 N 个请求，超出返回 429。
- 注意：多 worker 下进程内限流不共享，全局精确限流需配 Redis（`redis_url`）。

##### 多 Worker 精确限流一键化（3.3.2，可选；5.4 已实测）

多 worker（`workers>1`）时，各进程的限流计数/聊天缓存/熔断器状态各自独立（状态分裂）。
启用 Redis 共享状态即可让计数跨进程一致：

```bash
# 1) 本地起 Redis（Docker）：docker compose -f docker-compose.local.yml up -d
# 2) 一键接线：校验连通性并幂等写入 config.json 的 redis_url
python scripts/init_redis_state.py                 # 默认 redis://127.0.0.1:6379/0
# 3) 重启服务后 shared_state 自动走 Redis 实现（不可用时静默降级 Local）
uv run pytest test/test_shared_state.py            # Local / Redis 工厂降级两实现全过
```

**5.4 实测结论**：
- 2 worker + Redis + `rate_limit_rpm=5`：前 5 请求放行、第 6 起 429（跨进程精确限流生效）
- Redis 运行中断连：限流自动降级本进程本地滑窗，**不 500 不崩**（rate_limit 捕获异常回退）；降级后多 worker 各自计数，限流放宽是降级的已知取舍
- 依赖：需 `redis` 包（已入 pyproject/uv.lock）；降级路径由 test_shared_state.py 覆盖

或直接设环境变量 `CHATGPT2API_REDIS_URL=redis://host:6379/0`（覆盖 config.json），无需改配置。

#### 环境变量覆盖

| 环境变量 | 对应配置项 | 默认值 |
|----------|-----------|--------|
| `CHATGPT2API_SCHEDULER_MODE` | scheduler_mode | round_robin |
| `CHATGPT2API_RATE_LIMIT_RPM` | rate_limit_rpm | 0 |
| `CHATGPT2API_RATE_LIMIT_PER_IP_RPM` | rate_limit_per_ip_rpm | 0 |
| `CHATGPT2API_WORKERS` | workers | 1 |
| `STORAGE_BACKEND` | 存储后端 | json |
| `DATABASE_URL` | 数据库连接 | 自动 SQLite |

#### 高并发压测参考

- 单 Worker + JSON 存储：约 2000 req/min
- 4 Worker + SQLite 存储：约 8000 req/min（实测 7912 req/min，0 崩溃）
- 多实例 + Postgres + Redis：万级 req/min（需额外部署）

### 安全说明（企业内网自用，性能优先）

本项目面向企业内网部署，安全层由调用方系统自行处理。已移除或关闭的中间件和防护：
- **限流中间件**：默认关闭（`rate_limit_rpm=0`），可配置开启；**安全响应头**、**请求体大小限制**、**请求指标中间件**、**SSRF 防护**——已移除
- **请求追踪头**：`X-Request-ID` / `X-Response-Time-Ms` 由轻量中间件注入（不额外计算指标，仅定位用）
- **CORS 配置驱动**：`cors_origins` 配置允许来源（默认 `*`，内网无需收紧）
- **弱口令检测**：auth-key 为常见弱口令或 <12 位时，开发环境警告、`CHATGPT2API_ENV=production` 拒绝启动
- **上游熔断**：文本/图片调用链路接入熔断器，账号连续失败 5 次熔断 30s，半开 3 次成功恢复；上游抖动时快速失败换号，避免雪崩

### 质量保障（CI/CD）

- **CI 质量门**（`.github/workflows/ci.yml`）：硬门 pytest + 前端 tsc + build；软门 ruff/mypy/pip-audit（continue-on-error，存量债分期偿还）；本地五道防线 `scripts/run_all_guards.py`（契约守卫/SQL 审查/慢查询猎杀/变异探针/极限施压）
- **活测试隔离**：需真实上游/活服务的测试打 `pytest.mark.live`，CI 默认排除（稳定不触网）；本地手动 `uv run pytest -m live` 运行
- **运行测试**：`uv run pytest test/`（默认排除 live/redis）

### 实验性 / 规划中

- 详细状态说明见：[功能清单](./docs/feature-status.en.md)

## 效果展示

<table width="100%">
  <tr>
    <td width="50%"><img src="https://i.ibb.co/Jj8nfwwP/image.png" alt="image" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/pqf235v/image-edit.png" alt="image edit" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/tPcqtVfd/chery-studio.png" alt="chery studio" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/PsT9YHBV/account-pool.png" alt="account pool" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/rRWLG08q/new-api.png" alt="new api" border="0"></td>
  </tr>
</table>

## API

所有 AI 接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

<details>
<summary><code>GET /v1/models</code></summary>
<br>

返回当前暴露的图片模型列表。

```bash
curl http://localhost:23456/v1/models \
  -H "Authorization: Bearer <auth-key>"
```

<details>
<summary>说明</summary>
<br>

| 字段   | 说明                                                                                                         |
|:-----|:-----------------------------------------------------------------------------------------------------------|
| 返回模型 | `gpt-image-2`、`codex-gpt-image-2`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` |
| 接入场景 | 可接入 Cherry Studio、New API 等上游或客户端                                                                          |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/generations</code></summary>
<br>

OpenAI 兼容图片生成接口，用于文生图。

```bash
curl http://localhost:23456/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "一只漂浮在太空里的猫",
    "n": 1,
    "response_format": "b64_json"
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                | 说明                                                 |
|:------------------|:---------------------------------------------------|
| `model`           | 图片模型，当前可用值以 `/v1/models` 返回结果为准，推荐使用 `gpt-image-2` |
| `prompt`          | 图片生成提示词                                            |
| `n`               | 生成数量，当前后端限制为 `1-4`                                 |
| `response_format` | 当前请求模型中包含该字段，默认值为 `b64_json`                       |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/edits</code></summary>
<br>

OpenAI 兼容图片编辑接口，可上传图片文件，也可按官方 JSON 格式传入图片链接并生成编辑结果。

```bash
curl http://localhost:23456/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -F "model=gpt-image-2" \
  -F "prompt=把这张图改成赛博朋克夜景风格" \
  -F "n=1" \
  -F "image=@./input.png"
```

也可以直接传图片 URL：

```bash
curl http://localhost:23456/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-image-2",
    "prompt": "把这张图改成赛博朋克夜景风格",
    "images": [
      {"image_url": "https://example.com/input.png"}
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段          | 说明                                            |
|:------------|:----------------------------------------------|
| `model`     | 图片模型， `gpt-image-2`                           |
| `prompt`    | 图片编辑提示词                                       |
| `n`         | 生成数量，当前后端限制为 `1-4`                            |
| `image`     | 需要编辑的图片文件，使用 multipart/form-data 上传           |
| `images`    | JSON 图片引用数组，支持 `{"image_url": "https://..."}` |
| `image_url` | 表单模式下也可直接传图片链接，支持重复字段传多张图                     |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/chat/completions</code></summary>
<br>

面向文本、网页搜索与图片场景的 Chat Completions 兼容接口，不是完整通用聊天代理。

```bash
curl http://localhost:23456/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "生成一张雨夜东京街头的赛博朋克猫"
      }
    ],
    "n": 1
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                   | 说明                                                                           |
|:---------------------|:-----------------------------------------------------------------------------|
| `model`              | 文本、搜索或图片模型；搜索模型会触发网页搜索兼容逻辑                                                   |
| `messages`           | 消息数组，支持文本、搜索和图片请求内容                                                          |
| `n`                  | 图片生成数量，按当前实现解析为图片数量                                                          |
| `stream`             | 文本、搜索和图片场景均支持，仍在测试                                                           |
| `tools`              | 文本场景支持 `web_search` / `web_search_preview` / `web_search_preview_2025_03_11` |
| `web_search_options` | 传入时会触发网页搜索兼容逻辑                                                               |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/responses</code></summary>
<br>

面向文本、网页搜索和图片生成工具调用的 Responses API 兼容接口，不是完整通用 Responses API 代理。

```bash
curl http://localhost:23456/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-5",
    "input": "生成一张未来感城市天际线图片",
    "tools": [
      {
        "type": "image_generation"
      }
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段       | 说明                                                                                      |
|:---------|:----------------------------------------------------------------------------------------|
| `model`  | 响应中会回显该模型字段，搜索和图片生成会走对应兼容逻辑                                                             |
| `input`  | 输入内容；搜索使用最后一条用户文本，图片生成需能解析出提示词                                                          |
| `tools`  | 支持 `image_generation`、`web_search`、`web_search_preview`、`web_search_preview_2025_03_11` |
| `stream` | 已实现，但仍在测试                                                                               |

<br>
</details>
</details>

## 说明

本项目为内部定制化部署版本，基于内部需求做了生产级增强（智能调度、熔断、连接池、运维看板等）。
源码与更新通过内部渠道分发，不对外公开仓库。
