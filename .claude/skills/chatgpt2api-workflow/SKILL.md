---
name: chatgpt2api-workflow
description: ChatGPT2API 项目的完整开发工作流。用于新功能开发、API 接入、配置修改、看板扩展、账号池/代理池/熔断器/可观测性相关改动时，确保架构一致性和生产级质量。
---

# ChatGPT2API 开发工作流

> 在本项目做任何改动前**必须先读本技能**，判断是否过时（对照实际代码），过时则更新本技能，未过时则按本技能编码。

## 何时使用

- 新增 API 接口/路由
- 新增配置项
- 新增前端页面/看板
- 修改账号调度/代理池/熔断器/限流/可观测性
- 修改启动脚本/部署配置

## 项目架构（当前真实状态）

```
chatgpt2api/
├── api/                      # FastAPI 路由层
│   ├── app.py                # 应用入口 + CORS 中间件 + 路由注册
│   ├── ai.py                 # OpenAI 兼容 AI 接口 (/v1/*)
│   ├── accounts.py           # 账号管理 CRUD + 刷新
│   ├── dashboard.py          # 看板 API (scheduler/ops/usage/latency/stream/metrics)
│   ├── image_tasks.py        # 图片任务提交/轮询
│   ├── proxy_pool.py         # 代理池管理 API (proxies/egress-ip/probe-ip)
│   ├── system.py             # 设置/日志/图片/备份
│   └── support.py            # 鉴权/工具函数
├── services/                 # 业务逻辑层
│   ├── account_service.py    # 账号池 + 智能调度(健康档位/调度分) + 熔断器接入
│   ├── circuit_breaker.py    # 上游熔断器状态机
│   ├── session_pool.py       # TLS 连接池复用
│   ├── metrics_service.py    # 指标收集 + Prometheus 导出
│   ├── proxy_pool.py         # 代理池管理(持久化到 data/proxies.json)
│   ├── proxy_service.py      # 代理配置/CF clearance
│   ├── config.py             # 配置加载 + schema 校验
│   ├── log_service.py        # 日志服务(惰性自动清理)
│   └── storage/              # 存储后端 (json/sqlite/postgres/git)
├── web/                      # Next.js 前端 (webpack 构建，中文路径必须 --webpack)
│   └── src/
│       ├── app/              # 页面路由
│       │   ├── dashboard/    # 运维看板 (调度/熔断/用量/延迟/SSE)
│       │   ├── proxy-pool/   # IP 池管理
│       │   ├── accounts/     # 号池管理 (含熔断状态列+驱逐失效token)
│       │   ├── image/        # 在线画图
│       │   ├── image-manager/ # 图片管理
│       │   ├── debug/        # 调试面板 (chat/ppt/psd/search/skill)
│       │   ├── login/        # 登录
│       │   ├── logs/         # 日志管理
│       │   └── settings/     # 系统设置 (含 CPA/Sub2API/备份/第三方应用)
│       └── lib/api.ts        # API 请求封装 + 类型定义 (经 lib/request.ts 统一拦截)
├── services/protocol/        # 协议层 (conversation/openai_v1_*/anthropic_v1_messages/web_search_tool)
├── config.json               # 运行时配置 (启动时 schema 校验)
├── main.py                   # 启动入口 (多 worker, JSON 存储自动回退 workers=1)
├── 启动chatgpt2api.bat        # Windows 一键启动 (GBK+CRLF 无 BOM)
└── 停止chatgpt2api.bat        # Windows 停止服务
```

## 核心模块关键逻辑

### 1. 智能调度（services/account_service.py）

- 健康档位：healthy / warm / risky（状态 + 错误率 + 配额 + 近期错误）
- 调度分：基础分 + 配额占比 + 成功加成 - 失败惩罚 - 冷却惩罚
- 选取顺序：优先级 > 档位 > 调度分
- **熔断器接入**：`get_available_access_token` 里，熔断账号跳过；`record_success` **必须在 `_is_image_account_available` 确认后调用**（历史 bug：在返回后立即调用导致误判）

### 2. 熔断器（services/circuit_breaker.py + services/protocol/conversation.py）

- 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED
- 连续失败 5 次熔断，30s 冷却，半开 3 次成功恢复
- 全局注册表 `circuit_breaker_registry` 按 token 管理
- **已接入上游调用链路**（第五轮）：`text_backend`/`stream_text_deltas`/图片路径检查熔断 open 换号、按成败 record
- **`record_failure` 判定必须用正向白名单 `is_upstream_instability_error`**（5xx/超时/TLS/连接），**禁止用 `not is_token_invalid_error` 反向白名单**——否则业务拒绝(moderation 400/prompt违规)会误记，恶意用户可熔断健康账号造成拒绝服务（红队审查 Blocking）
- 换号时取号调用必须包 try/except 转 `RuntimeError("no available text account")`（候选空抛 ModelUnavailableError，契约统一）

### 3. 可观测性（services/metrics_service.py + api/metrics_middleware.py）

- `/metrics` Prometheus 端点（**需鉴权**：Authorization header 或 `?token=`，防公网暴露账号规模）
- 中间件注入 `X-Request-ID` + `X-Response-Time-Ms`
- `/api/dashboard/latency` 延迟统计（总数/错误率/平均延迟/按路径/在途）
- `/api/dashboard/usage` 用量统计：日志时间键兼容 `time`(text)/`ts`(json)/`created_at`，成败状态读 `detail.status`（顶层无 status 键）。**3.5.1 起改读 `services/usage_agg.py` 聚合缓存**（按小时桶增量聚合，后台线程每 60s ingest），不再每次全量扫 logs.jsonl；`usage_forecast` 同源
- **注意**：中间件异常路径必须 `status = 500` 默认值，response 存在才注入头（历史 P0 bug）

### 4. SSE 实时推送（api/dashboard.py `/api/dashboard/stream`）

- EventSource 无法传 header，用 `?token=` 查询参数鉴权
- `event_generator` 必须外层 `try/except asyncio.CancelledError` 处理客户端断开（历史 P1 bug）

### 5. TLS 连接池（services/session_pool.py）

- 按 (代理配置, impersonate, verify, **token 末 8 位账号标识**) 缓存 Session，复用 TCP/TLS 连接
- 5 分钟 TTL，最多 200 个配置，惰性清理
- 池化 Session 带 `_chatgpt2api_pooled` 标记，`close()` 转 `release()` 不拆连接（第六轮 P0 修复：OAuth 刷新取池后 finally close 曾每次拆连接）

### 6. 代理池（services/proxy_pool.py）

- 持久化到 `data/proxies.json`，重启自动加载
- 三种调度：轮询 / 加权 / 最少连接
- 健康检查 + 自动隔离恢复

### 7. 安全策略（企业内网自用，性能优先）

- **中间件现状**（`api/app.py` 核实）：限流 `RateLimitMiddleware` **已接线**（默认 0 关闭，S-R15）；CORS 配置驱动；`inject_request_headers` 注入 X-Request-ID/X-Response-Time-Ms。已移除 SecurityHeadersMiddleware / RequestSizeLimitMiddleware / MetricsMiddleware——对应 config 的 `max_request_body_mb_*` 死配置已一并彻底移除（勿误以为有 413 行为）
- **SSRF 防护仍在**：图片 URL 抓取走 `services/ssrf_guard.py`（协议白名单 + 内网 IP 段校验，`api/image_inputs.py:261` 消费），`CHATGPT2API_SSRF_ALLOW_PRIVATE_IPS` 可回退（默认拒绝内网）
- **CORS 配置驱动**：`config.cors_origins`（默认 `*`），企业内网场景无需收紧
- **弱口令检测**：auth-key 常见弱口令或 <12 位，development 警告、production（`CHATGPT2API_ENV=production`）拒绝启动

### 8. CI/CD 质量门（第五轮新增）

- `.github/workflows/ci.yml`：backend(ruff/mypy/pytest/pip-audit) + frontend(tsc/build)
- **活测试标记**：需真实上游/活服务的测试打 `pytest.mark.live`（11 个文件），`pyproject.toml` 默认 `addopts = "-m 'not live and not redis'"` 排除
- **环境污染隔离**：`test/conftest.py` autouse fixture 固定 `CHATGPT2API_AUTH_KEY`，防模块级 setdefault 污染
- 本地跑活测试：`uv run pytest -m live`
- lint/mypy/pip-audit 存量大，`continue-on-error` 提示不阻断，逐步清零

## 开发规范

### 新增 API 路由

1. 在 `api/` 下新建文件，实现 `create_router()`
2. 在 `api/app.py` 导入并 `app.include_router()`
3. 鉴权用 `require_identity()` 或 `require_admin()`
4. 同步调用用 `run_in_threadpool` 包装

### 新增配置项（必须 6 步全做，缺一不可）

1. `config.json` 加默认值
2. `services/config.py` 加 `@property` 读取（含环境变量覆盖 `CHATGPT2API_*`）
3. `get()` 方法暴露该配置
4. `_validate_schema` 加类型校验
5. `web/src/lib/api.ts` 的 `SettingsConfig` 加字段
6. `web/src/app/settings/store.ts` 的 `normalizeConfig` 加默认值 + `config-card.tsx` 加 UI

### 新增前端页面

1. `web/src/app/` 创建目录 + `page.tsx`
2. `useAuthGuard()` 钩子鉴权
3. `web/src/components/top-nav.tsx` 加导航项
4. `web/src/lib/api.ts` 加类型和请求函数
5. **构建必须 webpack**：`cd web && npm run build`（package.json 已配 `--webpack`），中文路径 Turbopack 会崩

### 新增后端模块

1. 小文件职责单一（参考 metrics_service/circuit_breaker/session_pool 模式）
2. 线程安全（Lock/RLock）
3. 全局单例放文件末尾
4. 写单元测试到 `test/`

## 验收清单（每次改动后必做）

### 启动验证
- [ ] `uv run python -c "from api.app import create_app; app=create_app()"` 无报错
- [ ] 服务启动后关键 API 返回 200

### 构建验证
- [ ] `cd web && npm run build` 成功（webpack）
- [ ] `rm -rf web_dist && cp -r web/out web_dist`

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

### 五道防线（每次改动后跑 `scripts/run_all_guards.py` 一键全过）
1. **契约守卫** `scripts/contract_guard.py`：前端 /api 引用与后端路由差集（断链检测）+ 端点字段签名快照 diff。改 API 字段后必跑；新增端点加进 SNAPSHOT_ENDPOINTS
2. **SQL 安全审查** `scripts/sql_audit.py`：注入面/事务边界/多 worker 守卫静态扫描
3. **慢查询猎杀** `scripts/slow_query_report.py`：data/ 规模盘点 × 全量扫描热点交叉
4. **变异探针** `scripts/mutation_probe.py`：对关键阈值/判断做种子变异，验证测试真能抓住回归（抓不住的补测试，不许直接跳过）
5. **极限施压** `scripts/stress_test.py`：并发突刺 + 慢存储注入 + 存储并发写一致性（TestClient 进程内，不影响生产）

报告落盘 `reports/<防线>/`（已 gitignore）。任何防线 FAIL 不许交付。

### E2E 冒烟验收（前端改动后跑 `scripts/e2e_smoke.cjs`）

真实浏览器验证前端交互链（playwright-core + 系统 Edge channel，免下载浏览器）：
1. 起后端：`CHATGPT2API_AUTH_KEY=<临时key> uv run python main.py`（23456）
2. 起前端：`cd web && npm run dev`（3000）
3. 跑：`cd web && NODE_PATH=./node_modules E2E_AUTH_KEY=<临时key> node ../scripts/e2e_smoke.cjs`
4. 断言：登录跳转 / logs 账号筛选（account_email 网络请求）/ accounts 时间线抽屉 / dashboard 档位筛选激活态，5/5 PASS
5. 收尾：停两服务，删除 E2E 期间注入的测试数据（`data/usage_agg.json` 可删除让下次启动重建）

### 终局交付门禁（声称"完成"前必须逐项打勾）
- [ ] **需求追踪**：本轮需求在 workflow_status.md 有矩阵行，每行有证据（文件/命令/测试），无证据标"未闭环"
- [ ] **反向批判**：主动写出"我自己最可能错在哪"，至少攻击 3 个假设并逐一验证或修复
- [ ] **假功能扫描**：前端新增按钮/开关/菜单必须有点击后的真实后端调用证据（契约守卫断链=0）
- [ ] **五道防线全绿**：run_all_guards.py PASS
- [ ] **回归全绿**：pytest 全量（排除 live）passed/0 failed；前端 tsc 0 错误 + build 成功
- [ ] **文档同步**：README/CHANGELOG/onboarding/workflow_status 与新行为一致；新脚本进 docs
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
6. 并发与多 worker：状态分裂场景（S1 Redis 已登记，找别的）

### Web 性能快查（前端改动时，addyosmani/agent-skills 精神）
- 整包 import 大库（recharts/lodash 全量）→ 改具名导入
- img 缺 width/height → CLS 风险
- render-blocking 外链、字体无 display=swap
- 动画避开 width/height/top/left，只用 transform/opacity
- 有证据才报，不跑 Lighthouse 全量（静态导出内网工具，不制造无证据工作）

### AI 会话启动协议（CRITICAL）
任何 AI 会话在本项目动手前，按序：
1. 读本技能（.claude/skills/chatgpt2api-workflow/SKILL.md）
2. 读 workflow_status.md 最新一轮（知道哪些已闭环，别重复也别推翻）
3. 读 CLAUDE.md 项目约定
4. 判断上述文档是否过时（对照实际代码抽查 ≥3 处）：过时→先更新文档再编码；未过时→按文档编码
5. 编码前先写验收标准（怎么算完成、用什么命令验证）

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
| 假接口=后端有端点但前端零消费（已修） | 多文件 | 后端实现≠已闭环。每加一个端点要追前端是否调用/展示；契约守卫 DYNAMIC_KEY_ENDPOINTS 要覆盖新端点。本轮抓出 usage-forecast/weighted_random/proactive 三个前端零接入假接口 |
| 限流中间件从未接线（已修） | api/app.py | 定义了 RateLimitMiddleware 却从不 add_middleware → rate_limit_rpm 配置形同虚设。加配置项必须同时接线 |
| resume_poll 双启动竞态（已修） | services/image_task_service.py | resume 成功改状态后锁释放，并发第二次 resume 双线程轮询同一 conversation 双扣配额。状态机变化需 in-flight 守卫（resume_inflight 置位/清除对称） |
| 任务字段落盘白名单丢关键字段（已修） | services/image_task_service.py | _load_locked 只恢复白名单字段会丢 conversation_id/account_email → 重启后 resume_poll 失效。持久化字段必须读写对称 |
| 落盘失败二次崩溃卡死任务（已修） | services/image_task_service.py | _update_task 内 _save_locked 抛异常会让 except 分支再崩→任务永久 RUNNING。落盘失败只记日志不抛出（内存态先更新） |
| 前端双重 toast（已修） | web/src/lib/request.ts | 拦截器 toast + 调用方 catch 再 toast = 每错弹两条。拦截器不 toast，改 error.userMessage 由调用方统一展示；401 返回 reject 而非 never-resolving（否则轮询挂起） |
| 乐观更新不回滚（已修） | web/src/app/proxy-pool/page.tsx | 策略切换先 setState 后请求，失败不回滚→UI 显示已切换实际未生效。乐观更新必须存 previous 失败回滚 |
| 刷新复活失败图片（已修） | web/src/app/image/page.tsx | 刷新恢复对 error+taskId 图片重新 fetch，后端已成功会把"失败"翻"成功"。恢复只轮询 loading，error 保留快照 |
| 破坏性操作无确认（已修） | 多组件 | 有损/不可逆操作（图片压缩/清理、备份删除、连接删除）必须二次确认，与既有删除确认模式一致 |
| 告警去重表每实例重建（已修） | services/alert_service.py | _build_from_config 每次重建实例→去重表清空→告警风暴。去重态提升到模块级共享 |
| 原子写非统一（已修） | services/image_task_service.py + editable_file_task_service.py | 固定 .tmp 名并发覆盖、崩溃半写。统一复用 json_storage._atomic_write_text（唯一 tmp+重试） |
| 文档与真实不一致（已修） | README.md + docs/api/ | 限流"已移除"vs 实际接线、/metrics"无需鉴权"vs 实际 401——改代码必须同步改文档，否则反向误导调用方 |

## 关键文件速查

| 需求 | 文件 |
|------|------|
| 调度 | services/account_service.py |
| 熔断 | services/circuit_breaker.py |
| 连接池 | services/session_pool.py |
| 指标 | services/metrics_service.py（X-Request-ID 头在 api/app.py 中间件注入） |
| 代理池 | services/proxy_pool.py + api/proxy_pool.py |
| 限流 | api/rate_limit.py（已接线 api/app.py，默认 0 关闭） |
| 用量预测 | services/usage_forecast.py + /api/dashboard/usage-forecast + dashboard 看板横幅 |
| 日志聚合缓存 | services/usage_agg.py（usage/usage_forecast 数据源；按小时桶增量聚合+90 天窗口+原子落盘，后台线程每 60s ingest；full_scan_* 为旧口径参考） |
| 主动探活 | api/support.py start_proactive_probe（默认关，proactive_probe_enabled） |
| 配置 | services/config.py |
| 日志 | services/log_service.py |
| 看板 | api/dashboard.py + web/src/app/dashboard/page.tsx |
| IP 池 | web/src/app/proxy-pool/page.tsx |
| API 文档 | docs/api/* |
| 五道防线 | scripts/run_all_guards.py（contract_guard/sql_audit/slow_query_report/mutation_probe/stress_test，带执行锁防双跑） |
| 备份演练 | scripts/verify_backup_roundtrip.py（打包/解包 sha256 往返，不触网） |
| live 测试 | scripts/run_live_tests.py（dry-run 预检 + --go 执行，防误跑烧配额） |
| 规格保鲜 | scripts/refresh_spec.py（生成 docs/project-spec.md，会话启动判断过时） |
| 黄金范例 | docs/golden-examples.md |
| 产品策略 | docs/product-strategy.md |
| ADR | docs/adr/index.md |
| 新人文档 | docs/onboarding/（7 篇，高级工程师版 + 承包商版） |
