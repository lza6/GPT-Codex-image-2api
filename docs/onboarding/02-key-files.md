# 02 · 关键文件地图（20 个）+ 危险修改清单

## 入口与配置

| # | 文件 | 为什么重要 | 何时读 |
|---|------|-----------|--------|
| 1 | `main.py` | 应用入口：多 Worker 决策（JSON 后端强制回退 workers=1）、`PROMETHEUS_MULTIPROC_DIR` 初始化、uvicorn 启动、data/ 可写性检测。**端口 23456 唯一定义点** | 第一天 |
| 2 | `api/app.py` | FastAPI app 工厂：6 个 router 注册 + 中间件（X-Request-ID 注入 → 限流 → CORS） | 第一天 |
| 3 | `config.json`（117 行） | 全部运行时配置：调度模式、限流、代理、图片任务、缓存、备份。**仓库不提交，首次自建** | 搭建日 |
| 4 | `services/config.py` | 配置加载 + schema 校验（报错带行号）+ 环境变量覆盖（`CHATGPT2API_*` 全表在此）。改 config.json 结构必同步此处 | 改配置前 |
| 5 | `pyproject.toml` | 依赖清单、pytest 标记定义（live/redis/unit + 默认 `-m 'not live and not redis'`）、ruff（E/F/I/UP，line-length 120）、mypy、阿里云镜像源 | 加依赖前 |

## 后端核心

| # | 文件 | 为什么重要 | 何时读 |
|---|------|-----------|--------|
| 6 | `api/ai.py` | OpenAI 兼容端点全家桶（11 个）：`/v1/models`、`/v1/images/generations`、`/v1/images/edits`、`/v1/chat/completions`、`/v1/responses`、`/v1/messages`、`/v1/search`、`/v1/ppt|psd/generations`、`/v1/editable-file-tasks`、`/files/{path}` | 第一周 |
| 7 | `services/account_service.py` | **调度大脑**：`_account_health_tier`（healthy/warm/risky）+ `_account_dispatch_score` + 账号状态机 + JWT 过期解析。8/8 调度单测守护 | 改调度前 |
| 8 | `services/circuit_breaker.py` | 上游熔断（连续失败 5 次熔断，30s 半开）+ 分级重试。`record_success` 调用位置是历史 P1 修复点 | 改重试前 |
| 9 | `services/openai_backend_api.py` | 上游 ChatGPT 调用封装（curl-cffi TLS 指纹伪装），会话复用出口 | 排查上游问题 |
| 10 | `services/session_pool.py` | TLS 连接池：Session 按代理配置缓存复用，降延迟尾巴（N9） | 性能调优 |
| 11 | `services/retry_budget.py` | 重试预算：`retry_idempotent_get` + `can_retry_stream`（SSE 已 emitted 后禁止重试） | 改流式路径 |
| 12 | `services/protocol/openai_v1_image_generations.py` | 请求/响应转换 + SSE 流。**前后端契约源头** | 改字段前 |
| 13 | `services/image_task_service.py` | 图片任务生命周期：轮询、硬超时（SSE 流可配上限）、重试 | 改任务逻辑 |
| 14 | `services/storage/base.py` + `factory.py` | 存储抽象（6 个抽象方法：load/save accounts、load/save auth_keys、health_check、get_backend_info）；json/sqlite/postgres/git 经 factory 切换 | 加后端前 |
| 15 | `services/metrics_service.py` + `services/prometheus_metrics.py` | Prometheus 指标（metrics_middleware.py 已删除，X-Request-ID 头改在 api/app.py 中间件注入）；request_id 经 contextvars 全链路传递 | 改观测性 |

## 前端

| # | 文件 | 为什么重要 | 何时读 |
|---|------|-----------|--------|
| 16 | `web/src/app/` | 8 个页面：accounts / dashboard / image / image-manager / logs / proxy-pool / settings / debug | 前端任务 |
| 17 | `web/src/lib/` + `web/src/store/` | axios API 封装 + zustand 状态；**字段名必须与 protocol/ 输出对齐** | 前端任务 |
| 18 | `web/package.json` | Next 16.2.3 + React 19.2.5 + Tailwind v4；构建固定 `next build --webpack`（Turbopack 在中文路径下失败，历史修复） | 构建问题 |

## 测试与部署

| # | 文件 | 为什么重要 | 何时读 |
|---|------|-----------|--------|
| 19 | `test/test_contracts.py` + `scripts/contract_probe.py` | **契约回归双保险**：改 API 字段后两个都要跑（probe 需活服务） | 改 API 后 |
| 20 | `.github/workflows/ci.yml` | CI 双 job：backend-quality（ruff/mypy/pytest/pip-audit）+ frontend-build（tsc + webpack build） | 提交前 |

## 危险修改清单（改前必须理解后果）

| 文件/区域 | 风险 | 原因 |
|-----------|------|------|
| `main.py` 端口/worker 逻辑 | 🔴 高 | 端口 23456 与 Docker/bat/前端/文档全套绑定（N15）；worker 回退逻辑防数据丢失 |
| `services/account_service.py` 调度算法 | 🔴 高 | 影响全部请求路由；8/8 调度单测必须保持绿 |
| `services/circuit_breaker.py` 状态机 | 🔴 高 | 误标 success 曾导致坏账号被当好账号用（P1） |
| `services/storage/base.py` 接口签名 | 🔴 高 | 4 个后端实现同时受影响，需全量回归 |
| `api/app.py` 中间件装配顺序 | 🟡 中 | X-Request-ID 注入 / 限流(默认关) / CORS 作用域；metrics_middleware 已删勿引用 |
| `config.json` 字段删除/改名 | 🟡 中 | schema 校验拒绝启动；需同步 `services/config.py` + `.env.example` + compose 注释 |
| `api/errors.py` 错误格式 | 🟡 中 | 前端按此解析；改动需契约探测验证 |
| `启动chatgpt2api.bat` | 🟡 中 | 必须保持 **GBK 编码 + CRLF + 无 BOM**，否则中文乱码/启动失败 |
| `services/protocol/*` 响应字段 | 🟡 中 | 前后端契约源头，改字段跑双验证 |
| `utils/pow.py`、`utils/sentinel.py`、`utils/turnstile.py` | 🟡 中 | 上游逆向基础设施，改动影响所有上游请求 |

## 安全区（可自由改，正常 PR 即可）

- `web/src/` 页面样式、交互、新组件（字段名除外）
- `test/` 新增测试
- `docs/` 文档
- `utils/` 新增工具函数（不改既有函数签名）
- `services/` 新增独立服务模块（经 factory/依赖注入接入，不改既有调度路径）
