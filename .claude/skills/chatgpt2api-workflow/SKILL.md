---
name: chatgpt2api-workflow
description: ChatGPT2API 项目的完整开发工作流。用于新功能开发、API 接入、配置修改、看板扩展、账号池/代理池/熔断器/可观测性/事件总线/任务队列/Provider 路由/ORM 相关改动时，确保架构一致性和生产级质量。
---

# ChatGPT2API 开发工作流

> 在本项目做任何改动前**必须先读本技能**，判断是否过时（对照实际代码），过时则更新本技能，未过时则按本技能编码。

## 何时使用

- 新增 API 接口/路由
- 新增配置项
- 新增前端页面/看板
- 修改账号调度/代理池/熔断器/限流/可观测性
- 修改启动脚本/部署配置
- 新增后端模块或修改架构层（事件总线/任务队列/Provider 路由/ORM 存储/共享状态）

## 项目架构（当前真实状态，v2.36.0）

```
chatgpt2api/
├── api/                      # FastAPI 路由层
│   ├── app.py                # 应用入口 + CORS 中间件 + 限流中间件 + 路由注册 + lifespan
│   ├── ai.py                 # OpenAI 兼容 AI 接口 (/v1/*)
│   ├── accounts.py           # 账号管理 CRUD + 刷新 + 批量操作 + 分组 + 回收站(trash/restore/clear) + 详情/tags/export-csv
│   ├── dashboard.py          # 看板 API (scheduler/ops/usage/latency/stream/metrics/capacity + events/adaptive_scheduler/cost)
│   ├── image_inputs.py       # 图片输入解析/校验/SSRF 防护消费
│   ├── image_tasks.py        # 图片任务提交/轮询
│   ├── kookeey.py            # kookeey 代理流量看板 API
│   ├── providers.py          # Provider 列表 API（get /api/providers）
│   ├── proxy_pool.py         # 代理池管理 API (proxies/egress-ip/probe-ip)
│   ├── rate_limit.py         # 限流中间件（Local/Redis 双实现，默认 0 关闭）
│   ├── response_cache.py     # 请求级响应缓存（TTL+Cache-Control+?refresh=1+写操作 invalidate，预注册 5 端点）
│   ├── support.py            # 鉴权(require_identity/require_admin) + 工具函数
│   ├── system.py             # 设置/日志/图片/备份/健康端点
│   └── errors.py             # 异常处理器
├── services/                 # 业务逻辑层
│   ├── account_service.py    # 账号池 + 智能调度(健康档位/调度分/least_used) + 熔断器接入 + provider 过滤 + 回收站联动
│   ├── account_warmup.py     # 新账号预热（首次登录/冷却后重新激活）
│   ├── account_lifetime.py   # 账号寿命预测（EWMA 失败率+连续失效窗口双信号）
│   ├── adaptive_scheduler.py # 自适应调度器（按运行指标自动切换调度模式，最短驻留守卫防抖动）
│   ├── alert_service.py      # 告警服务（去重窗口+多通道+恢复事件）
│   ├── auto_healer.py        # 自动修复引擎（Auto-Healing 2.0：会话重建/磁盘清理/熔断探测等 6 修复器）
│   ├── audit_service.py      # 审计日志（独立天文件+按天轮转+require_admin 统一埋点）
│   ├── auth_service.py       # 认证服务（admin/user 双角色，hmac 密钥验证）
│   ├── backup_service.py     # 备份服务（CF R2/WebDAV）
│   ├── circuit_breaker.py    # 上游熔断器状态机（CLOSED/OPEN/HALF_OPEN）
│   ├── config.py             # 配置加载 + schema 校验（1071行）
│   ├── config_watcher.py     # 配置热加载（mtime 轮询 + CONFIG_CHANGED 事件）
│   ├── content_filter.py     # 内容过滤
│   ├── cost_service.py       # 成本优化（usage_agg 用量+provider 分布+kookeey 流量三源合并）
│   ├── cpa_service.py        # CPA 服务
│   ├── diagnostic_engine.py  # 智能诊断引擎（ABC + 7 诊断检查器 + DiagnosticEngine）
│   ├── editable_file_task_service.py  # 可编辑文件任务服务
│   ├── event_bus.py          # 事件总线（同步/异步双模式，死信队列，线程安全）
│   ├── event_bus_init.py     # 事件总线订阅注册
│   ├── image_failure.py      # 图片失败分类中枢（classify_image_exception 熔断判定单一来源）
│   ├── image_pipeline.py     # 异步图片处理管道（下载+处理+缓存+并发限流）
│   ├── image_service.py      # 图片服务
│   ├── image_storage_service.py  # 图片存储服务（local/R2/WebDAV 多后端，R2 用 AWS SigV4 签名）
│   ├── image_tags_service.py # 图片标签服务
│   ├── image_task_service.py # 图片任务服务（状态机+resume_poll+in-flight 守卫）
│   ├── kookeey_service.py    # kookeey 代理流量/出口IP探测/画像
│   ├── log_index.py          # 日志倒排索引（增量构建，加速查询）
│   ├── log_service.py        # 日志服务（按天轮转切分+多文件增量+惰性迁移）
│   ├── metrics_service.py    # 指标收集 + Prometheus 导出
│   ├── model_service.py      # 模型服务
│   ├── oauth_login_service.py # OAuth 登录
│   ├── openai_backend_api.py # OpenAI 上游后端 API（139K，核心长文件）
│   ├── openai_oauth.py       # OpenAI OAuth 工具
│   ├── otp_login_service.py  # OTP 登录服务（Graph 取件优先/98faka 兜底）
│   ├── prometheus_metrics.py # Prometheus 指标定义
│   ├── provider_scheduler.py # 各 Provider 独立调度池（Phase 2：调度分池）
│   ├── proxy_pool.py         # 代理池管理(持久化到 data/proxies.json)
│   ├── proxy_service.py      # 代理配置/CF clearance/kookeey 每号住宅 IP + 常规请求粘性 IP（get_profile）
│   ├── quota_service.py      # 配额服务
│   ├── request_context.py    # 请求上下文
│   ├── retry_budget.py       # 统一重试预算（幂等 GET 指数退避/流式首字节前换号至多1次）
│   ├── router_service.py     # 模型→Provider 路由分发（Phase 3，前缀匹配+精确匹配）
│   ├── session_cache.py      # 三级会话缓存（L1 内存 LRU + L2 Redis + L3 存储层）
│   ├── session_pool.py       # TLS 连接池复用（自适应扩容/缩容，key 含账号标识+指纹）
│   ├── shared_state.py       # 多 worker 共享状态抽象层（Local/Redis 双实现）
│   ├── ssrf_guard.py         # SSRF 防护（协议白名单+内网 IP 段校验）
│   ├── sub2api_service.py    # Sub2API 服务
│   ├── task_queue.py         # 轻量异步任务队列（优先级调度+FIFO+状态查询+取消）
│   ├── task_queue_init.py    # 任务队列处理器注册
│   ├── tracing.py            # 轻量请求追踪（trace_id 全链路 + 慢请求告警）
│   ├── trash_service.py      # 账号回收站（剔除/删除记录 + 统计 + 原因，线程安全原子落盘）
│   ├── usage_agg.py          # 日志聚合缓存（按小时桶增量聚合+90天窗口+原子落盘）
│   ├── usage_forecast.py     # 用量预测
│   ├── protocol/             # 协议层
│   │   ├── conversation.py       # 核心会话逻辑（含图片透传上游直链）
│   │   ├── openai_v1_chat_complete.py  # Chat Completions
│   │   ├── openai_v1_image_generations.py  # 图片生成（seed 透传）
│   │   ├── openai_v1_image_edit.py   # 图片编辑
│   │   ├── openai_v1_models.py      # 模型列表
│   │   ├── openai_v1_response.py    # Responses API
│   │   ├── anthropic_v1_messages.py # Anthropic 兼容
│   │   ├── openai_search.py    # 搜索
│   │   ├── chat_completion_cache.py # 聊天缓存
│   │   ├── error_response.py   # 错误响应
│   │   └── web_search_tool.py  # 网页搜索工具
│   ├── providers/            # 多提供商地基（Phase 1/4）
│   │   ├── base.py           # ProviderMeta 元信息模型
│   │   └── registry.py       # 注册表+归一化+校验
│   └── storage/              # 存储后端
│       ├── base.py           # 泛型仓储接口（Repository Protocol）+ AsyncStorageBackend 异步基类
│       ├── json_storage.py   # JSON 文件存储（含原子写）
│       ├── database_storage.py # SQLite/Postgres 存储（含 ORM 层）
│       ├── async_database.py # 异步数据库后端（sqlalchemy.ext.asyncio + aiosqlite/asyncpg）
│       ├── async_bridge.py   # 同步→异步桥接适配器（STORAGE_ASYNC_ENABLED 启用）
│       ├── git_storage.py    # Git 仓库存储
│       └── factory.py        # 工厂模式创建存储后端
├── web/                      # Next.js 前端 (webpack 构建，中文路径必须 --webpack)
│   └── src/
│       ├── app/              # 页面路由
│       │   ├── dashboard/    # 运维看板 (调度/熔断/用量/延迟/SSE/寿命预测/容量/Provider)
│       │   ├── proxy-pool/   # IP 池管理
│       │   ├── accounts/     # 号池管理 (含熔断状态/寿命徽章/批量操作/时间线/分组)
│       │   ├── image/        # 在线画图 (seed/负向提示/宽高比预设)
│       │   ├── image-manager/ # 图片管理
│       │   ├── debug/        # 调试面板
│       │   ├── login/        # 登录
│       │   ├── logs/         # 日志管理 (含审计 tab)
│       │   └── settings/     # 系统设置 (含 CPA/Sub2API/备份/第三方应用/图片透传)
│       ├── components/
│       │   ├── top-nav.tsx   # 顶部导航
│       │   ├── ui/           # UI 组件库 (async-button/skeleton/badge/dialog/sheet 等20个)
│       │   └── ...
│       └── lib/
│           ├── api.ts        # API 请求封装 + 类型定义 (1358行)
│           ├── request.ts    # 统一请求拦截器 (401 跳转/错误处理)
│           └── ...
├── services/protocol/        # 协议层
├── scripts/                  # 工具脚本
│   ├── contract_guard.py     # 契约守卫：断链检测+快照 diff
│   ├── contract_probe.py     # 契约探测
│   ├── sql_audit.py          # SQL 安全审查
│   ├── slow_query_report.py  # 慢查询报告
│   ├── mutation_probe.py     # 变异探针
│   ├── stress_test.py        # 极限施压
│   ├── run_all_guards.py     # 六道防线一键执行（契约/SQL/慢查询/变异/压测/文档同步）
│   ├── docs_sync_check.py    # 文档同步检查：VERSION 与 SKILL/CLAUDE/workflow_status/verification-registry 内嵌版本号一致性
│   ├── e2e_smoke.cjs         # E2E 冒烟 (playwright-core + 系统 Edge)
│   ├── refresh_spec.py       # 规格保鲜
│   ├── verify_backup_roundtrip.py # 备份往返验证
│   ├── revive_abnormal.py    # 批量救号脚本
│   ├── run_live_tests.py     # live 测试执行器
│   ├── web_stamp.ps1         # 前端指纹智能重建
│   └── ...
├── docs/                     # 文档
│   ├── verification-registry.md # 验证登记表（当前已验证基线）
│   ├── project-spec.md       # 项目规格
│   ├── golden-examples.md    # 黄金范例
│   ├── onboarding/           # 新人文档
│   └── ...
├── e2e/                      # Playwright E2E 全链路（真实前后端 + 系统 Edge；使用说明见 docs/e2e.md）
│   ├── specs/                # 用例：login / dashboard / accounts / batch-notify
│   ├── pages/                # Page Object（LoginPage/DashboardPage/AccountsPage/SettingsPage）
│   ├── global-setup.ts       # 起后端(23456)+前端(3000)并轮询等就绪，进程退出时清理
│   ├── playwright.config.ts  # testDir/globalSetup/单 worker/msedge/CI 开关
│   └── package.json          # test/test:headed/report 脚本（独立依赖）
├── config.json               # 运行时配置 (启动时 schema 校验)
├── main.py                   # 启动入口 (多 worker, JSON 存储自动回退 workers=1)
├── 启动chatgpt2api.bat        # Windows 一键启动 (GBK+CRLF 无 BOM)
├── 停止chatgpt2api.bat        # Windows 停止服务
├── VERSION                   # 当前版本号 (v2.36.0)
├── CHANGELOG.md              # 变更日志
└── workflow_status.md        # 工作流状态（当前轮次完成清单+防线状态）
```

## 核心模块关键逻辑

### 1. 智能调度（services/account_service.py）

- 健康档位：healthy / warm / risky（状态 + 错误率 + 配额 + 近期错误）
- 调度分：基础分 + 配额占比 + 成功加成 - 失败惩罚 - 冷却惩罚
- 选取顺序：优先级 > 档位 > 调度分
- **v2.32.0 least_used（雨露均沾）**：`scheduler_mode=least_used` 时选 `last_used_at` 最久远账号，避免集中突刺单号，让免费号分布更接近真人
- **v2.30.0 自适应调度器**：`scheduler_adaptive_enabled=true` 时 `AdaptiveScheduler.tick()` 按运行指标（并发/成功率/模型多样性）自动切 weighted_random/least_load/predictive/affinity，最短驻留 120s 防抖动
- **熔断器接入**：`get_available_access_token` 里，熔断账号跳过；`record_success` **必须在 `_is_image_account_available` 确认后调用**（历史 bug：在返回后立即调用导致误判）
- **Provider 过滤**：`_account_matches_provider` 按 provider 字段过滤调度池
- **账号分组**：支持 group 分组字段（JSON/SQLite 自动持久化）
- **账号列表缓存**：`_ACCOUNT_LIST_CACHE_TTL` = 5s，减少重复查询

### 2. 熔断器（services/circuit_breaker.py + services/protocol/conversation.py）

- 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED
- 连续失败 5 次熔断，30s 冷却，半开 3 次成功恢复
- 全局注册表 `circuit_breaker_registry` 按 token 管理
- **`record_failure` 判定必须用正向白名单 `is_upstream_instability_error`**（5xx/超时/TLS/连接），**禁止用 `not is_token_invalid_error` 反向白名单**——否则业务拒绝(moderation 400/prompt 违规)会误记，恶意用户可熔断健康账号造成拒绝服务
- **v2.10.0 统一**：`image_failure.classify_image_exception` + `should_record_circuit_failure` 为熔断判定单一事实来源，`conversation.stream_text_deltas` 与 `openai_search` 统一走此路径
- 换号时取号调用必须包 try/except 转 `RuntimeError("no available text account")`（候选空抛 ModelUnavailableError，契约统一）

### 3. 可观测性（services/metrics_service.py + services/prometheus_metrics.py + api/app.py）

- `/metrics` Prometheus 端点（**需鉴权**：Authorization header 或 `?token=`，防公网暴露账号规模）
- 中间件注入 `X-Request-ID` + `X-Response-Time-Ms`
- 扩展指标：熔断状态机 `chatgpt2api_circuit_breaker_transitions{from,to}`、调度选取 `chatgpt2api_scheduler_pick_total{tier}`、寿命预测 `chatgpt2api_lifetime_risk{risk}`
- `/api/dashboard/usage` 用量统计：读 `services/usage_agg.py` 聚合缓存（按小时桶增量聚合+后台线程每 60s ingest），不再每次全量扫 logs
- **中间件异常路径必须 `status = 500` 默认值**，response 存在才注入头（历史 P0 bug）

### 4. SSE 实时推送（api/dashboard.py `/api/dashboard/stream`）

- EventSource 无法传 header，用 `?token=` 查询参数鉴权
- `event_generator` 必须外层 `try/except asyncio.CancelledError` 处理客户端断开（历史 P1 bug）

### 5. TLS 连接池（services/session_pool.py）

- 按 (代理配置, impersonate, verify, **token 末 8 位账号标识**, **fp_key 指纹标识**) 缓存 Session，复用 TCP/TLS 连接
- 5 分钟 TTL，最多 200 个配置，最小保留 5 个空闲连接，自适应扩容/缩容
- 池化 Session 带 `_chatgpt2api_pooled` 标记，`close()` 转 `release()` 不拆连接（历史 P0 修复）
- **同代理多账号必须 key 含账号标识，否则 Authorization 串号**（历史 B1 实证）

### 6. 代理池（services/proxy_pool.py）

- 持久化到 `data/proxies.json`，重启自动加载
- 三种调度：轮询 / 加权 / 最少连接
- 健康检查 + 自动隔离恢复

### 7. 安全策略（企业内网自用，性能优先）

- **中间件现状**（`api/app.py` 核实）：限流 `RateLimitMiddleware` **已接线**（默认 0 关闭，S-R15）；CORS 配置驱动；`inject_request_headers` 注入 X-Request-ID/X-Response-Time-Ms。已移除 SecurityHeadersMiddleware / RequestSizeLimitMiddleware / MetricsMiddleware——对应 config 的 `max_request_body_mb_*` 死配置已一并彻底移除
- **SSRF 防护仍在**：图片 URL 抓取走 `services/ssrf_guard.py`（协议白名单 + 内网 IP 段校验，`api/image_inputs.py` 消费），`CHATGPT2API_SSRF_ALLOW_PRIVATE_IPS` 可回退（默认拒绝内网）
- **CORS 配置驱动**：`config.cors_origins`（默认 `*`），企业内网场景无需收紧
- **弱口令检测**：auth-key 常见弱口令或 <12 位，development 警告、production（`CHATGPT2API_ENV=production`）拒绝启动
- **限流中间件**：默认 0 关闭；配置 rpm>0 且 Redis 可用时跨进程精确限流；Redis 断连自动降级本地滑窗，不 500 不崩

### 8. 事件总线（services/event_bus.py，v2.24.0 Pub/Sub 增强）

- EventType 枚举（26 事件类型）+ Event.source/severity 增强字段 + subscribe_all 通配符订阅
- 异步消费者（asyncio.Queue + 后台协程），publish_async 入队 / publish_sync 同步；死信队列 `data/event_dead_letter.jsonl`
- 事件统计（发布计数/severity 分布/handler 耗时/死信计数/消费者深度）+ Prometheus 4 指标
- **v2.31.0 持久化**：`api/app.py` 事件订阅写入 `data/events.jsonl`（行数裁剪），`GET /api/events/stream` SSE 实时推送 + `GET /api/dashboard/events` 读取最近事件（同源）
- **初始化**：`api/app.py` lifespan 调用 `event_bus_init.register_subscribers()` 注册所有订阅

### 9. 任务队列（services/task_queue.py）

- 基于优先级的轻量异步任务队列
- 优先级：CRITICAL(0) 用户请求 > HIGH(1) 账号刷新 > NORMAL(2) 日志清理 > LOW(3) 备份
- 同优先级 FIFO，任务状态查询与取消
- 初始化：`api/app.py` lifespan 调用 `task_queue_init.register_task_handlers()` 注册处理器

### 10. 多提供商架构（地基 Phase 1-3/4）

- **Phase 1**（地基）：ProviderMeta 元信息 + 注册表 + 账号入库自动 provider 字段
- **Phase 2**（调度分池）：`services/provider_scheduler.py` 各 provider 独立调度池
- **Phase 3**（路由分发）：`services/router_service.py` 模型名前缀匹配 → provider 路由
- **Phase 4**（前端切换器，未完成）：账号列表/设置页/图片工作台切换 provider
- 当前仅 `chatgpt` 已接入（enabled=True），`grok` 占位（enabled=False，UI 灰显"即将支持"）

### 11. 共享状态层（services/shared_state.py）

- 多 worker 共享状态抽象层：LocalBackend（进程内 dict，单 worker 默认）/ RedisBackend（可选）
- 解决多 worker 状态分裂：限流计数、聊天缓存、熔断器状态
- Redis 不可用时静默降级 Local 并打日志
- **红线**：多 worker 状态只走本层，禁止模块级可变全局变量跨请求持有

### 12. 统一重试预算（services/retry_budget.py）

- 规则：幂等 GET（_get_me/_get_conversation 等）指数退避最多 N 次；流式首字节前连接失败换账号最多 1 次
- 流式开始后绝不重试——重复请求会重复扣费/重复出图，只断流报错

### 13. 异步图片管道（services/image_pipeline.py）

- asyncio 协程，非阻塞下载 + CPU 密集操作转线程池
- 内存缓存（TTL 自动过期）+ 并发限流（Semaphore 默认 5）
- 批量处理保持输入顺序

### 14. CI/CD 质量门

- `.github/workflows/ci.yml`：backend(ruff/mypy/pytest/pip-audit) + frontend(tsc/build)
- **活测试标记**：需真实上游/活服务的测试打 `pytest.mark.live`（11 个文件），`pyproject.toml` 默认 `addopts = "-m 'not live and not redis'"` 排除
- **环境污染隔离**：`test/conftest.py` autouse fixture 固定 `CHATGPT2API_AUTH_KEY`，防模块级 setdefault 污染
- 本地跑活测试：`uv run pytest -m live`
- lint/mypy/pip-audit 存量大，`continue-on-error` 提示不阻断，逐步清零

### 15. 图片透传上游直链（v2.9.2+）

- config.json 配置 `image_passthrough_enabled`（默认 True）/ `image_passthrough_ttl_secs`（默认 3600）
- 三处生图下载点按开关分流
- resume-poll 续轮询同步接入透传（经评审补充）
- 上游直链有 TTL，过期后按原下载逻辑回退

## 开发规范

### 新增 API 路由

1. 在 `api/` 下新建文件，实现 `create_router()`
2. 在 `api/app.py` 导入并 `app.include_router()`
3. 鉴权用 `require_identity()` 或 `require_admin()`
4. 同步调用用 `run_in_threadpool` 包装
5. 新增端点立即加入 `scripts/contract_guard.py` 的 DYNAMIC_KEY_ENDPOINTS 或 SNAPSHOT_ENDPOINTS

### 新增配置项（必须 6 步全做，缺一不可 — 历史教训：加配置不接线，RateLimit 形同虚设）

1. `config.json` 加默认值
2. `services/config.py` 加 `@property` 读取（含环境变量覆盖 `CHATGPT2API_*`）
3. `get()` 方法暴露该配置
4. `_validate_schema` 加类型校验
5. `web/src/lib/api.ts` 的 `SettingsConfig` 加字段
6. `web/src/app/settings/store.ts` 的 `normalizeConfig` 加默认值 + `config-card.tsx` 加 UI
7. **接线验证**：配置项是否实际被消费代码读取（如限流配置必须 `add_middleware`，否则配置形同虚设）

### 新增前端页面

1. `web/src/app/` 创建目录 + `page.tsx`
2. `useAuthGuard()` 钩子鉴权
3. `web/src/components/top-nav.tsx` 加导航项
4. `web/src/lib/api.ts` 加类型和请求函数
5. **构建必须 webpack**：`cd web && npm run build`（package.json 已配 `--webpack`），中文路径 Turbopack 会崩
6. 显式检查新增按钮/菜单有真实后端 API 调用（否则是假功能，触发终局门禁）

### 新增后端模块

1. 小文件职责单一（参考 metrics_service/circuit_breaker/session_pool/task_queue/event_bus 模式）
2. 线程安全（Lock/RLock）
3. 全局单例放文件末尾
4. 若需要跨模块通知，走事件总线（`event_bus.publish`）而非直接函数调用——解耦模块减少循环依赖
5. 若需要异步后台处理，走任务队列（`task_queue.enqueue`）而非自行起线程——统一生命周期管理
6. 若需要多 worker 共享状态，走 `shared_state.get_shared_state()`——禁止模块级可变全局变量
7. 写单元测试到 `test/`

### 新增事件/任务

1. **事件类型**：`services/event_bus.py` 的 `ALL_EVENTS` 列表加新常量
2. **订阅注册**：`services/event_bus_init.py` 加 `subscribe()` 调用
3. **任务处理器**：`services/task_queue_init.py` 加 `register_handler()` 调用
4. 事件/任务 handler 抛异常走死信队列/任务失败，不冒泡到发布者

### 新增 Provider

1. `services/providers/registry.py` 注册 ProviderMeta（name/display_name/enabled/models）
2. `services/providers/base.py` 无需改（frozen dataclass 通用）
3. 调度分池自动适配（`provider_scheduler.py` 读注册表，不硬编码）
4. 路由规则自动适配（`router_service.py` 用 `_DEFAULT_RULES` 或 config.json router_rules）
5. 前端自动显示（`api/providers.py` 端点+注册表）

### 新增存储后端

1. 实现 `services/storage/base.py` 的 `Repository` Protocol
2. `services/storage/factory.py` 加分支
3. 参考 `json_storage.py`/`database_storage.py` 已有实现

## 验收清单（每次改动后必做）

### 启动验证
- [ ] `uv run python -c "from api.app import create_app; app=create_app()"` 无报错
- [ ] 服务启动后关键 API 返回 200

### 构建验证
- [ ] `cd web && npm run build` 成功（webpack）
- [ ] `rm -rf web_dist && cp -r web/out web_dist`（若前端改动）

### 契约验证
- [ ] 后端 API 返回结构与前端类型字段完全对齐（用真实 TestClient 调用对比）
- [ ] TypeScript `npx tsc --noEmit` 0 错误

### 单元测试
- [ ] `uv run pytest test/ -q --ignore=<HTTP集成测试>` 通过
- [ ] 新增逻辑有对应测试

### 代码审查（零容忍）
- [ ] 无 `dir()` 判断局部变量（用默认值 + try/finally）
- [ ] 熔断器 record_success 在可用性确认后调用
- [ ] SSE 有 CancelledError 处理
- [ ] 无未使用导入
- [ ] 异常路径有指标/追踪/日志
- [ ] 配置项接线已验证（定义 ≠ 生效，必须消费方实际读取）
- [ ] 事件/任务 handler 抛异常不冒泡到发布者
- [ ] 多 worker 共享状态走 shared_state 层，不跨请求持有模块级全局变量
- [ ] 时间比较统一 aware(UTC)，禁止 naive/aware 混合（历史 OTP 静默吞 bug）

### v2.18+ 新增功能专项检查（涉及下列区域时必做）

- [ ] **回收站**（`services/trash_service.py` + `api/accounts.py` trash/restore/clear）：剔除/删除账号有记录；恢复回池；上限裁剪生效；新端点已 git add 且契约守卫覆盖
- [ ] **雨露均沾调度**（`_pick_least_used`）：`scheduler_mode=least_used` 生效，last_used_at 最久远者优先；与其它模式互斥
- [ ] **粘性 IP**（`proxy_service.get_profile`）：仅 `kookeey.proxy_enabled=true` 生效；常规对话/生图请求自动接入；按量计费提示保留
- [ ] **R2 图片存储**（`image_storage_service.R2Client`）：r2_* 四配置齐全才启用，缺配置降级 local 不 500；SigV4 签名上传/读取/删除/列对象
- [ ] **事件流 SSE**（`/api/events/stream` + `/api/dashboard/events`）：`?token=` 鉴权；events.jsonl 持久化 + 行数裁剪
- [ ] **响应缓存**（`api/response_cache.py`）：预注册 5 端点 TTL 生效；`?refresh=1` 强刷；写操作 invalidate
- [ ] **自适应调度器**（`adaptive_scheduler.py`）：最短驻留守卫防抖动；模式切换有指标
- [ ] **配置热加载**（`config_watcher.py`）：config.json mtime 变化触发 CONFIG_CHANGED 事件
- [ ] **智能诊断/自动修复**（`diagnostic_engine.py` + `auto_healer.py`）：诊断 7 检查器 + 修复 6 修复器有测试

### 六道防线（每次改动后跑 `scripts/run_all_guards.py` 一键全过 — 仅重跑改动区域，未碰区域沿用验证登记表结论）

1. **契约守卫** `scripts/contract_guard.py`：前端 /api 引用与后端路由差集（断链检测）+ 端点字段签名快照 diff。改 API 字段后必跑；新增端点加进 SNAPSHOT_ENDPOINTS 或 DYNAMIC_KEY_ENDPOINTS
2. **SQL 安全审查** `scripts/sql_audit.py`：注入面/事务边界/多 worker 守卫静态扫描
3. **慢查询猎杀** `scripts/slow_query_report.py`：data/ 规模盘点 × 全量扫描热点交叉
4. **变异探针** `scripts/mutation_probe.py`：对关键阈值/判断做种子变异，验证测试真能抓住回归（抓不住的补测试，不许直接跳过）
5. **极限施压** `scripts/stress_test.py`：并发突刺 + 慢存储注入 + 存储并发写一致性（TestClient 进程内，不影响生产）
6. **文档同步** `scripts/docs_sync_check.py`：VERSION 与 SKILL.md/CLAUDE.md/workflow_status/verification-registry 内嵌版本号一致，防 bump VERSION 漏同步文档

报告落盘 `reports/<防线>/`（已 gitignore）。任何防线 FAIL 不许交付。

### E2E 冒烟验收（前端改动后跑 `scripts/e2e_smoke.cjs`）

真实浏览器验证前端交互链（playwright-core + 系统 Edge channel，免下载浏览器）：
1. 起后端：`CHATGPT2API_AUTH_KEY=<临时key> uv run python main.py`（23456）
2. 起前端：`cd web && npm run dev`（3000）
3. 跑：`cd web && NODE_PATH=./node_modules E2E_AUTH_KEY=<临时key> node ../scripts/e2e_smoke.cjs`
4. 断言：登录跳转 / logs 账号筛选 / accounts 时间线抽屉 / dashboard 档位筛选 / 账号密码导入，10/10 PASS
5. 收尾：停两服务，删除 E2E 期间注入的测试数据（`data/usage_agg.json` 可删除让下次启动重建）

### 终局交付门禁（声称"完成"前必须逐项打勾）

- [ ] **需求追踪**：本轮需求在 workflow_status.md 有矩阵行，每行有证据（文件/命令/测试），无证据标"未闭环"
- [ ] **反向批判**：主动写出"我自己最可能错在哪"，至少攻击 3 个假设并逐一验证或修复
- [ ] **假功能扫描**：前端新增按钮/开关/菜单必须有点击后的真实后端调用证据（契约守卫断链=0）
- [ ] **六道防线全绿**：run_all_guards.py PASS（仅重跑改动区域）
- [ ] **回归全绿**：pytest 全量（排除 live）passed/0 failed；前端 tsc 0 错误 + build 成功
- [ ] **文档同步**：README/CHANGELOG/onboarding/workflow_status/verification-registry 与新行为一致；新脚本进 docs
- [ ] **无伪实现**：TODO/FIXME/占位返回/mock 充数 = 未闭环；做不到的写明外部限制与降级行为
- [ ] **边界声明**：无法实测的部分（真实上游、付费 API）写明"已做到哪步/缺什么外部条件/无该条件时如何降级"

### Reviewer 门禁（独立审查必须这么跑）

- 有罪推定：假设每行新代码有缺陷，直到证据证明否则
- 评估成品不评估意图：TODO=未处理，FIXME=已损坏
- 每条发现给 file:line + 证据 + 失败场景（什么输入/状态下出错）
- 分级：Blocking（安全/数据损坏/逻辑错误/竞态）→ Required（粗糙/懒惰/未处理边界）→ Suggestion → Note
- 输出 Verdict：Request Changes / Needs Discussion / Approve；Approve 标准是"无 Blocking"，不是"完美"
- 修复后必须复验循环，直到 Approve 或明确卡点
- 禁止为逃避 Approve 而人为制造问题

### 盲区扫描（每轮至少一次，六个视角各提 ≥1 个具体场景）

1. 最苛刻验收：哪个功能"界面上有、流程走不通"
2. 最倒霉接入方：按文档真实发一个请求会踩什么坑
3. 最辛苦运维：凌晨三点磁盘满/内存涨/连接泄漏会怎样
4. 极端输入：畸形 JSON、超大 body、并发突刺、存储文件被删、config 非法值
5. 时间/环境：时区、系统时间回拨、跨天边界、中文路径、Windows 文件锁
6. 并发与多 worker：状态分裂场景（S1 Redis 共享状态已有，找别的）

### Web 性能快查（前端改动时）

- 整包 import 大库（recharts/lodash 全量）→ 改具名导入
- img 缺 width/height → CLS 风险
- render-blocking 外链、字体无 display=swap
- 动画避开 width/height/top/left，只用 transform/opacity
- 有证据才报，不跑 Lighthouse 全量（静态导出内网工具，不制造无证据工作）

## 历史 bug 警示（不可再犯）

| bug | 文件 | 教训 |
|-----|------|------|
| metrics_middleware `dir()` 崩溃 | api/metrics_middleware.py | 永远不要用 `dir()` 判断局部变量，用默认值 + try/finally |
| 熔断器误标成功 | services/account_service.py | record_success 必须在可用性确认后调用 |
| SSE 协程泄漏 | api/dashboard.py | event_generator 必须有 CancelledError 处理 |
| bat 闪退 | 启动chatgpt2api.bat | bat 必须 GBK + CRLF + 无 BOM，不能 UTF-8 |
| Turbopack 中文路径崩 | web/package.json | 中文路径构建必须 `--webpack` |
| 熔断误判业务拒绝为上游抖动 | services/protocol/conversation.py | record_failure 用正向白名单 is_upstream_instability_error，禁止反向白名单——否则恶意用户熔断健康账号 |
| 环境污染击穿测试 | test/conftest.py | 禁止模块级 os.environ.setdefault 改 auth-key；用 autouse fixture 隔离 |
| usage 统计读错字段 | api/dashboard.py | 日志时间键 time/ts/created_at 兼容，status 在 detail 子对象 |
| chunked 绕过请求体限制 | api/request_size_limit.py | 仅查 Content-Length 不够，无 Length 的 chunked 写请求要 411 |
| Session 池化指纹串扰（已修） | services/session_pool.py | 池 key 必须含账号标识（token 末 8 位）——同代理多账号共享会覆盖 Authorization 串号 |
| 池化形同虚设（已修） | services/openai_backend_api.py | 池化 Session 的 close() 必须转 release()，否则 finally close 每次拆连接 |
| 前端断链假功能（已修） | web/src/lib/api.ts + settings 孤儿组件 | 前端调了后端从未注册的 /api/proxy——删组件必须连带删 api.ts 封装函数；契约守卫可自动抓此类断链 |
| 熔断默认阈值无人看守（已修） | test/test_circuit_breaker.py | 测试全用自定义阈值(3)，默认 5 变异曾逃逸——关键默认值必须有显式回归测试 |
| 假接口=后端有端点但前端零消费（已修） | 多文件 | 后端实现≠已闭环。每加一个端点要追前端是否调用/展示；契约守卫 DYNAMIC_KEY_ENDPOINTS 要覆盖新端点。抓出 usage-forecast/weighted_random/proactive 三个前端零接入假接口 |
| 限流中间件从未接线（已修） | api/app.py | 定义了 RateLimitMiddleware 却从不 add_middleware → rate_limit_rpm 配置形同虚设。加配置项必须同时接线 |
| resume_poll 双启动竞态（已修） | services/image_task_service.py | resume 成功改状态后锁释放，并发第二次 resume 双线程轮询同一 conversation 双扣配额。状态机变化需 in-flight 守卫（resume_inflight 置位/清除对称） |
| 任务字段落盘白名单丢关键字段（已修） | services/image_task_service.py | _load_locked 只恢复白名单字段会丢 conversation_id/account_email → 重启后 resume_poll 失效。持久化字段必须读写对称 |
| 落盘失败二次崩溃卡死任务（已修） | services/image_task_service.py | _update_task 内 _save_locked 抛异常会让 except 分支再崩→任务永久 RUNNING。落盘失败只记日志不抛出（内存态先更新） |
| 前端双重 toast（已修） | web/src/lib/request.ts | 拦截器 toast + 调用方 catch 再 toast = 每错弹两条。拦截器不 toast，改 error.userMessage 由调用方统一展示；401 返回 reject 而非 never-resolving（否则轮询挂起） |
| 乐观更新不回滚（已修） | web/src/app/proxy-pool/page.tsx | 策略切换先 setState 后请求，失败不回滚→UI 显示已切换实际未生效。乐观更新必须存 previous 失败回滚 |
| 刷新复活失败图片（已修） | web/src/app/image/page.tsx | 刷新恢复对 error+taskId 图片重新 fetch，后端已成功会把"失败"翻"成功"。恢复只轮询 loading，error 保留快照 |
| 破坏性操作无确认（已修） | 多组件 | 有损/不可逆操作（图片压缩/清理、备份删除、连接删除）必须二次确认，与既有删除确认模式一致 |
| 告警去重表每实例重建（已修） | services/alert_service.py | _build_from_config 每次重建实例→去重表清空→告警风暴。去重态提升到模块级共享 |
| 寿命预测降档勿误封 | services/account_lifetime.py + account_service._lifetime_downgrade | 预测只降不升（濒危→risky/高→warm），低/中不降；最小观测窗口守卫（success+fail<3 且无明确失效→low）防「瞬间封禁/复活抖动」；禁止把 high 直接封禁 |
| 原子写非统一（已修） | services/image_task_service.py + editable_file_task_service.py | 固定 .tmp 名并发覆盖、崩溃半写。统一复用 json_storage._atomic_write_text（唯一 tmp+重试） |
| 文档与真实不一致（已修） | README.md + docs/api/ | 限流"已移除"vs 实际接线、/metrics"无需鉴权"vs 实际 401——改代码必须同步改文档，否则反向误导调用方 |
| OTP 取件时间比较被静默吞掉（已修） | services/otp_login_service.py `_mail_time` | 邮件时间转本地 naive 与 UTC aware 基准比较抛 TypeError，被外层 `except` 静默吞掉 → **永远取不到验证码且无报错**。时间比较必须统一 aware(UTC)；凡是 `except: pass` 包住的核心步骤都要警惕"永远失败但无日志" |
| 启动脚本前端版本停滞（已修） | 启动chatgpt2api.bat + scripts/web_stamp.ps1 | 旧逻辑仅判 `web_dist\index.html` 存在就跳过构建 → 改了代码/VERSION 也不重建，UI 版本号停滞。改为指纹(web/src+配置+VERSION+CHANGELOG 哈希)不一致才重建。改 bat 必须 PowerShell GBK(936) 读写，禁用 UTF-8 Edit/Write |
| 事件总线初始化失败不阻断 | api/app.py lifespan | 初始化失败只打日志不阻断启动——核心模块初始化失败应明确记录，但不要阻止服务启动 |
| 任务队列消费者死循环 | services/task_queue.py | 消费者出队异常必须走 fail 状态，不无限重试。handler 抛异常标记 error 后继续消费下一任务——不阻塞队列 |
| 变异性探针 GBK flaky（已修） | scripts/mutation_probe.py | 子进程强制 UTF-8（PYTHONIOENCODING + errors=replace），消除 Windows GBK 中文日志偶发 UnicodeEncodeError |
| config 单文件挂载原子写失败（已修） | services/config.py `_save` | docker compose volume mount 单文件场景，原子写 tmp+rename 失败（跨文件系统不可 rename），回退直接写原文件 |
| 熔断判定双源不一致（已修 v2.10.0） | services/protocol/conversation.py + openai_search.py | 文本链路和搜索链路各有自己的熔断判定逻辑，导致同一异常分类不同结果。统一走 `image_failure.classify_image_exception` + `should_record_circuit_failure` |
| 图片透传 resume-poll 漏接（已修 v2.9.2） | services/image_task_service.py | 透传启用后，resume-poll 续轮询仍走老下载逻辑，透传分流没覆盖 resume 路径。评审补充后发现并修复 |
| config 环境变量覆盖不生效 | services/config.py | 环境变量 `CHATGPT2API_*` 必须在 `@property` 的 getter 中实时读取 `os.environ`，不能开局读一次缓存——配置热更新后环境变量覆盖失效（影响 docker compose 运行时改配置） |
| 回收站端点漏提交（已修 v2.32.0） | api/accounts.py | 新端点实现后 `git add` 漏文件 → 部署后 404。新端点入库立即 `git status` 核对已暂存 |
| 粘性 IP 配置与行为脱节（v2.32.0 警示） | services/proxy_service.py | `get_profile` 粘性 IP 仅 `kookeey.proxy_enabled=true` 生效，默认 false 行为不变——配置项必须接线验证，不能只看代码 |
| 事件流端点鉴权（v2.31.0 警示） | api/dashboard.py `/api/events/stream` | SSE 无法传 header，必须 `?token=` 查询参数鉴权（复用 dashboard/stream 模式） |
| R2 图片存储凭证缺失 | services/image_storage_service.py | R2 模式需 r2_account_id/access_key/secret/bucket 四配置齐全，缺配置应降级 local 而非 500 |
| diagnose/healing 前端 .json() 误用（已修 v2.33.0） | web/src/lib/api.ts | `httpRequest` 已返回 axios 解析后的 data，封装函数再 `resp.json()` 运行时必崩（TS 因 unknown 拦截）。封装函数直接返回 data + 显式泛型，禁止把 data 当 Response 二次 .json() |

## 关键文件速查

| 需求 | 文件 |
|------|------|
| 调度 | services/account_service.py（Provider 过滤见 _account_matches_provider） |
| 熔断 | services/circuit_breaker.py（判定见 image_failure.py） |
| 连接池 | services/session_pool.py（自适应扩容/缩容，key 含账号标识+指纹） |
| 指标 | services/metrics_service.py + services/prometheus_metrics.py（X-Request-ID 头在 api/app.py 中间件注入） |
| 代理池 | services/proxy_pool.py + api/proxy_pool.py |
| 限流 | api/rate_limit.py（已接线 api/app.py，默认 0 关闭，Redis 降级本地） |
| 用量预测 | services/usage_forecast.py + /api/dashboard/usage-forecast + dashboard 看板横幅 |
| 账号寿命预测 | services/account_lifetime.py（EWMA 失败率+连续失效窗口双信号，只降不升+最小观测窗口防抖动） |
| 容量规划 | /api/dashboard/capacity（基于 usage_agg 聚合缓存，禁止全量扫 logs） |
| 告警恢复事件 | services/alert_service.py + circuit_breaker.record_success 半开恢复 + account_service._record_refresh_success |
| 日志聚合缓存 | services/usage_agg.py（按小时桶增量聚合+90 天窗口+原子落盘，后台线程每 60s ingest） |
| 批量账号操作 | api/accounts.py `POST /api/accounts/batch`（evict_stale/label/export 表驱动分发） |
| 账号分组 | api/accounts.py `GET /api/accounts/groups`（group 字段 JSON 列自动持久化） |
| 图片 seed 透传 | services/protocol/openai_v1_image_generations.py → ConversationRequest.seed → 上游 payload tools[0].seed |
| 主动探活 | api/support.py start_proactive_probe（默认关，proactive_probe_enabled） |
| 配置 | services/config.py（1071行，含 schema 校验+环境变量覆盖+热更新） |
| 日志 | services/log_service.py（4.1 起按天轮转切分：写 logs-YYYY-MM-DD.jsonl、list(days=N) 分片读、过期天文件整删+当天文件裁剪） |
| 审计日志 | services/audit_service.py（独立 audit-YYYY-MM-DD.jsonl 按天轮转+原子写+过期整删+operator 末 8 位脱敏） |
| 看板 | api/dashboard.py + web/src/app/dashboard/page.tsx |
| IP 池 | web/src/app/proxy-pool/page.tsx |
| 事件总线 | services/event_bus.py + services/event_bus_init.py |
| 任务队列 | services/task_queue.py + services/task_queue_init.py |
| Provider 路由 | services/router_service.py + services/providers/registry.py |
| Provider 调度 | services/provider_scheduler.py |
| 共享状态 | services/shared_state.py（Local/Redis 双实现，多 worker 唯一状态层） |
| 重试预算 | services/retry_budget.py（幂等 GET 指数退避 + 流式首字节前换号） |
| 异步图片管道 | services/image_pipeline.py（asyncio 协程+并发限流+内存缓存） |
| 图片透传 | services/protocol/conversation.py（build_passthrough_items 等）+ config.image_passthrough_enabled |
| 健康端点 | api/system.py `GET /api/system/healthz` + `/api/system/health/ready` |
| API 文档 | docs/api/* |
| 六道防线 | scripts/run_all_guards.py（contract_guard/sql_audit/slow_query_report/mutation_probe/stress_test/docs_sync_check，带执行锁防双跑） |
| 号池救活 | services/otp_login_service.py（Graph 取件优先/98faka 兜底）+ services/account_service.py（watcher 重登+导入两处 OTP 降级）+ scripts/revive_abnormal.py |
| 每号住宅 IP | services/proxy_service.py `kookeey_proxy_for(email)`（md5[:8] 粘性 session→同号固定 IP） |
| 常规请求粘性 IP | services/proxy_service.py `get_profile`（对话/生图自动接入，需 kookeey proxy_enabled=true） |
| 雨露均沾调度 | services/account_service.py `_pick_least_used`（scheduler_mode=least_used） |
| 账号回收站 | services/trash_service.py + api/accounts.py（GET trash + POST clear/restore） |
| 请求级响应缓存 | api/response_cache.py（预注册 5 端点 TTL + ?refresh=1 + 写操作 invalidate） |
| 自适应调度器 | services/adaptive_scheduler.py + /api/dashboard/adaptive_scheduler |
| 配置热加载 | services/config_watcher.py（mtime 轮询 + CONFIG_CHANGED 事件） |
| 智能诊断/自动修复 | services/diagnostic_engine.py + auto_healer.py + /api/system/diagnose + /api/system/healing/* |
| 成本优化 | services/cost_service.py + /api/dashboard/cost（usage_agg+provider+kookeey 三源） |
| 三级会话缓存 | services/session_cache.py（L1 LRU + L2 Redis + L3 存储层） |
| 事件流 SSE | api/dashboard.py GET /api/events/stream + GET /api/dashboard/events（events.jsonl 持久化） |
| R2 图片存储 | services/image_storage_service.py R2Client（AWS SigV4 签名，纯 Python 无 boto3） |
| 异步存储层 | services/storage/async_database.py + async_bridge.py（STORAGE_ASYNC_ENABLED 启用） |
| 多提供商地基 | services/providers/（ProviderMeta+注册表，chatgpt 默认/grok 占位未启用） |
| 前端智能重建 | scripts/web_stamp.ps1（对 web/src+配置+VERSION+CHANGELOG 算指纹）+ 启动bat 按指纹决定重建 |
| 备份演练 | scripts/verify_backup_roundtrip.py（打包/解包 sha256 往返，不触网） |
| live 测试 | scripts/run_live_tests.py（dry-run 预检 + --go 执行，防误跑烧配额） |
| 规格保鲜 | scripts/refresh_spec.py（生成 docs/project-spec.md，会话启动判断过时） |
| 文档同步检查 | scripts/docs_sync_check.py（VERSION 与 4 文档内嵌版本号一致性，防 bump 漏同步） |
| 验证登记表 | docs/verification-registry.md（当前已验证基线+已知 flaky/边界+各区域最近改动） |
| 黄金范例 | docs/golden-examples.md |
| 产品策略 | docs/product-strategy.md |
| ADR | docs/adr/index.md |
| 新人文档 | docs/onboarding/（7 篇，高级工程师版 + 承包商版 + 初级开发者版） |

### AI 会话启动协议（CRITICAL）

任何 AI 会话在本项目动手前，按序：

1. **读本技能**（当前 SKILL.md）
2. **读 `workflow_status.md` 最新一轮**（知道哪些已闭环，别重复也别推翻）
3. **读 `docs/verification-registry.md`**（当前已验证基线 + 已知 flaky/边界 + 各区域最近改动）——**只在改动落到某区域时才重跑该区域验证，没碰的沿用登记表结论不重跑**；表里的"已知 flaky/边界"不要重复追查
4. **读 `CLAUDE.md` 项目约定**
5. **判断上述文档是否过时**（对照实际代码抽查 ≥3 处）：过时 → 先更新文档再编码；未过时 → 按文档编码
6. **编码前先写验收标准**（怎么算完成、用什么命令验证）
7. **编码前看 `graft/INDEX.md`** 浏览全部节点（graft 已索引）；结构性问题用 `codegraph_context`/`codegraph_callers`；字面量用 `graft grep`/`rg`
8. **改完跑 `graft build`** 刷新索引