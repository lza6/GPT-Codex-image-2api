## 2.3.0 审计补丁 - 2026-08-04 (终局总审计：假接口接入 + 越权 + 限流接线 + 稳定性)

**修复（发版后审计发现，未发新版本号）：**
+ [假接口] usage-forecast 前端接入看板（告警横幅 + 近7天趋势折线）；scheduler_mode=weighted_random / proactive_probe 补齐设置页 UI + env/config 模板样例；「导出全部 Token」改走后端三件套导出
+ [越权] dashboard 后端全端点 require_identity→require_admin；前端 useAuthGuard(["admin"])
+ [限流] RateLimitMiddleware 接线生效（此前定义了但从未注册，配置形同虚设）
+ [稳定性] resume_poll resume_inflight 竞态守卫 / image_tasks.json 加载保留 conversation_id / 落盘失败降级不卡死 / 原子写统一 / X-Request-ID 注入 / SSE 指数退避重连
+ [安全] 图片压缩/清理、R2 备份删除、CPA/Sub2API 连接删除补二次确认
+ [文档] README 限流描述、docs/api /metrics 鉴权、onboarding 引用、SKILL.md 13 条新 bug 警示

## 2.3.0 - 2026-08-04 (排期矩阵闭环：P0 运行时修复 + 调度/告警/看板功能 + 工程效能)

**新增配置项：**
- `scheduler_mode` 新增 `weighted_random`：档位内按调度分加权随机选号，摊平单账号磨损
- `proactive_probe_enabled`（默认关）/ `proactive_probe_interval_minute`（默认 30）：低频主动探活，提前剔除哑死账号
- 告警事件新增 `quota_forecast_depletion`：配额耗尽预测临近时推 webhook

本轮（v2.3.0 排期 A/B/C/E + F 调研转化）：
+ [修复] account_service 补 logging.getLogger，防配额告警路径 NameError 崩溃
+ [修复] 限流关键词词边界收紧，"rate limiting" 不再误中 "rate limit" 白换号浪费配额
+ [修复] resume_poll 原账号优先：任务记录 account_email，恢复按 email 找回 token 重连（匿名 token 无权读已登录会话，超时续等此前必失败）；账号已删明确报错
+ [修复] 熔断器 OPEN 态迟到 record_success 不再直接闭合，防抖动上游过早放行
+ [修复] Session 池 remove 偷出时摘池化标记，防死连接回流复用（连接泄漏）
+ [修复] 图片任务幂等强化：TERMINAL 同 key 幂等返回 + 120s prompt 短窗口去重，防重复扣配额
+ [修复] 下载 fallback 双失败日志带 primary_error + fallback_attempted 关联字段
+ [修复] 启动 bat 连续 5 次崩溃熔断 + 指数退避（3s→60s）+ crash.log 记录，防刷盘死循环
+ [修复] 停止 bat 杀进程前校验 python 映像名，防误杀同端口其他程序
+ [功能] 用量预测 `/api/dashboard/usage-forecast`：近 7 天线性外推号池配额耗尽时间 + 提前告警
+ [功能] 加权随机调度（F3）+ 低频主动探活（F4）+ 配额耗尽预测告警（F1/F2）
+ [工程] CI pip-audit 高危阻断 / 五道防线执行锁 / conftest 环境隔离面扩大 / 配置校验表驱动化 / live 测试安全入口 / Docker 非 root+HEALTHCHECK+SIGTERM / 项目规格保鲜脚本
+ [脚本] `verify_backup_roundtrip.py`（备份恢复演练）、`run_live_tests.py`（live 安全入口）、`refresh_spec.py`（规格保鲜）

## 2.1.0 - 2026-08-03 (安全收口 + 韧性收口 + 可观测性 + 主动告警)

**Breaking changes（升级必读）：**
- **SSRF 防护**：`image_inputs` 图片 URL 默认拒绝内网/回环/链路本地地址（原行为允许）。内网图床场景需在设置页开启「允许抓取内网图片」或配置 `ssrf_allow_private_ips=true` 回退
- **文件下载鉴权**：`/files/{path}` 需携带 auth-key（原为公开端点）。调用方需在请求头带 `Authorization: Bearer <auth-key>`
- **XFF 伪造防护**：`X-Forwarded-For` 头默认仅信任回环来源（原行为可能全信）。反向代理部署需配置 `trusted_proxies` 白名单（设置页「可信反向代理 IP」）
- **账号导出时区**：导出文件 `expired`/`last_refresh` 字段从 UTC+8 改为 UTC ISO8601（跨时区部署一致性）

本轮新增（D1-D19 全量收口）：
+ [安全] SSRF 防护：协议白名单 + 内网 IP 段校验 + 重定向逐步校验（services/ssrf_guard.py）
+ [安全] XFF trusted_proxy：resolve_client_ip 按白名单解析真实 IP，防伪造绕过按 IP 限流
+ [安全] 文件下载鉴权：/files/{path} 挂 require_identity，前端经 axios blob 鉴权下载
+ [安全] 备份 key 白名单：download/detail/delete 接 _is_backup_object 校验
+ [安全] config.json 密钥治理：git rm --cached + config.example.json 脱敏入库
+ [韧性] SQLite WAL：journal_mode=WAL + busy_timeout=5000 + synchronous=NORMAL（每连接重放），配置 sqlite_wal_mode/sqlite_busy_timeout_ms
+ [韧性] 进度字典 TTL：refresh/relogin 进度记录 monotonic 惰性淘汰（默认 3600s），配置 progress_ttl_seconds
+ [韧性] 熔断器生命周期：账号删除/轮换/自动移除接 registry.remove + 孤儿 TTL 24h 惰性淘汰
+ [韧性] codex 池化：裸 urllib 改池化 curl_cffi Session
+ [韧性] 搜索路径熔断：openai_search 接熔断；web_search_tool 补 close 泄漏
+ [可观测性] 备份失败可见：完整堆栈日志 + chatgpt2api_backup_failures_total 计数器 + dashboard 备份卡片
+ [可观测性] 优雅停机：lifespan shutdown 接 session_pool.close_all() + 守护线程 join 5s
+ [告警] webhook 主动告警：4 类事件 POST 到 alert_webhook_url，重试 1 次 + 5 分钟去重，配置 alert_webhook_url/timeout/events
+ [架构] 多 worker 共享状态：services/shared_state.py Local/Redis 双实现 + 限流走共享层 + docker-compose 可选 redis profile
+ [测试] 关键路径补强 + 变异探针扩至 6 点 6/6 caught；circuit_breaker 95% / session_pool 86% / retry_budget 100%
+ [治理] docs 归档：workflow_status-v6/final-report-v4/code-review-report 归档 docs/archive/

独立审查：六维审查 2 轮（Request Changes → 修复 → Approve）；295 passed / 0 failed；五道防线 5/5 PASS

## 2.0.0 - 2026-08-02 (生产级增强 + 韧性闭环)

**Breaking changes（升级必读，见 README「升级到 2.0」章节）：**
- CORS 默认收紧：`config.cors_origins` 原默认 `["*"]`，生产环境需显式配置域名白名单
- `/metrics` Prometheus 端点需鉴权（Authorization header 或 `?token=`），防公网暴露账号规模
- 活测试标记：需真实上游/活服务的测试打 `pytest.mark.live`，本地跑全量需 `pytest -m live`（默认排除）

本轮新增：
+ [新增] 生产级可观测性：/metrics Prometheus 指标端点、X-Request-ID 请求追踪、X-Response-Time-Ms 延迟头、/api/dashboard/latency 延迟统计
+ [新增] 上游熔断器：连续失败 5 次自动熔断，30s 冷却半开恢复，防止上游抖动雪崩（接入账号调度 + 上游调用链路）
+ [新增] TLS 连接池复用接入主流量：OpenAIBackendAPI 与账号 OAuth 刷新走池化 Session（按账号+代理+impersonate 缓存，key 含 token 末8位防同代理串号），close() 转 release 不拆底层连接
+ [新增] 统一重试预算（services/retry_budget.py）：幂等 GET 指数退避≤2 次、流式首字节前换账号≤1 次、流式开始后绝不重试（防重复扣费/出图）
+ [新增] 上游指标埋点：chatgpt2api_upstream_requests_total{model,result} 在文本/图片路径接入，/metrics 真实导出
+ [新增] 熔断状态 API + 账号页熔断列：GET /api/dashboard/circuit_breakers（token末8位上报），前端 15s 轮询标注熔断中/半开账号
+ [新增] 驱逐失效 token：POST /api/accounts/evict_stale 批量处理异常账号，账号页「驱逐失效token」按钮（loading+toast）
+ [新增] SSE 实时推送：/api/dashboard/stream 看板数据 3s 推送，前端 EventSource 实时更新；页面隐藏时暂停连接与轮询（visibilitychange），可见时立即拉取重建
+ [新增] 统一错误反馈拦截器：401 跳登录、429 提示限流、5xx 错误 toast 带 request-id 后 8 位（web/src/lib/request.ts）
+ [新增] IP 池管理 UI：代理增删改查、权重调度（轮询/加权/最少连接）、健康状态、出口 IP 探测
+ [新增] 连接池并发看板：实时显示使用中账号（在途）、配额用完账号、延迟按路径分布
+ [新增] 日志自动清理：日志超 5000 条自动裁剪到 3000 条，惰性触发防高频 I/O
+ [新增] config.json schema 校验：启动时校验配置类型，错误给出清晰行号报错
+ [新增] API 契约文档：OpenAPI 3.0 规范、多语言 SDK 示例（Python/Node/Go/curl）、图片任务轮询代码、错误码表
+ [新增] 请求体大小限制中间件（/v1/images/* 50MB、其余 10MB，413/411）+ 安全响应头中间件（nosniff/DENY/Referrer-Policy）
+ [新增] CI 质量门：GitHub Actions（backend ruff/mypy/pytest/pip-audit + frontend tsc/build）
+ [修复] 去除 GitHub 链接，品牌内部定制化
+ [变更] 端口从 8000 改为冷门端口 23456

## 1.9.0 - 2026-08-01

+ [新增] 智能调度系统：健康档位（healthy/warm/risky）+ 调度分 + 优先级 + 双模式调度（round_robin / remaining_quota），移植自 codex2api fast_scheduler
+ [新增] 运维看板：调度健康度、资源占用、用量统计、账号排行榜（3 个 API + 前端页面）
+ [新增] 多级限流：全局 RPM + 单 IP RPM 滑动窗口限流中间件
+ [新增] 代理池：多代理管理、健康检查、自动隔离恢复（移植自 codex2api proxy_pool）
+ [新增] 代理池管理 API（/api/proxies 增删改查、权重调整、策略切换、健康检查触发）
+ [新增] 多 Worker 并发：支持多进程利用多核 CPU（需 SQLite/Postgres）
+ [新增] Windows 一键启动/停止 bat 脚本，支持 UTF-8 编码、自动依赖安装、崩溃自动重启
+ [新增] 前后端契约测试、安全审查测试、极限压测
+ [修复] 中文路径下 Turbopack 构建失败，改用 webpack
+ [修复] 多 Worker + JSON 存储数据安全问题，自动回退 workers=1 并警告
+ [修复] SQLAlchemy 2.0 告警
+ [修复] 环境变量覆盖 4 个新配置项（CHATGPT2API_SCHEDULER_MODE/RATE_LIMIT_RPM/RATE_LIMIT_PER_IP_RPM/WORKERS）
+ [变更] 端口从 8000 改为冷门端口 23456，避免冲突

## 1.8.0 - 2026-07-28

+ [新增] 新增默认请求上游模型名称和默认思考强度配置，支持在设置页面修改，并可通过模型名的 `-standard`、`-extended`、`-max` 后缀覆盖思考强度。
+ [修复] 新增没出图也移除本地对话的配置，支持在图片生成失败、超时或仅返回文本时异步隐藏对应对话记录。
+ [修复] `/v1/models` 汇总各账号类型的官方模型列表，文本请求按模型权限选择账号。
+ [修复] 过滤隐藏、非最终频道及发往内部工具的助手消息，避免搜索指令和推理内容泄漏到 API 输出。
+ [修复] 修复输出清洗误删代码和命令中标点前空格的问题。
+ [修复] 为图片生成 SSE 流增加可配置的硬超时上限，避免上游长连接长时间挂起。
+ [优化] 数据库存储改为增量同步，仅新增、更新或删除发生变化的记录，保留未变记录的 ID。

## 1.7.0 - 2026-07-05

+ [移除] 移除注册功能、防滥用机制导致封禁GitHub账号。

## 1.6.0 - 2026-07-04

+ [修复] 修复sub2api导入问题。
+ [修复] 修复前端404、405问题。
+ [新增] 新增出图后删除对话记录功能。
+ [调整] Pro号不再按无限额度处理、约每天1000张。

## 1.5.0 - 2026-06-13

+ [新增] 新增 WARP / Privoxy / FlareSolverr 清障方案，注册遇到 Cloudflare 拦截后可刷新 clearance 并重试。
+ [新增] 新增 `outlook_token` 邮箱池，支持 Outlook/Hotmail 注册验证码读取。
+ [新增] 新增网页搜索兼容接口、图片编辑 mask 和图片任务相关能力。
+ [优化] 更新 sentinel/PoW 获取方式，提高上游请求兼容性。
+ [优化] 调整代理优先级和注册请求重试逻辑。

## 1.4.1 - 2026-06-03

+ [新增] 账号刷新改为异步模式，支持前端轮询刷新/重新登录进度。
+ [新增] 号池管理页面新增重新登录功能，支持密码登录恢复异常账号。
+ [新增] 刷新后自动重新登录异常账号（可在设置页开启）。
+ [新增] 图片生成支持并行模式，多张图片使用独立线程和账号同时生成。
+ [新增] 图片轮询超时自动换账号重试（最多4次），连接超时同账号递增等待重试。
+ [新增] 图片二次确认机制与先check再hit可配置化，关闭后可跳过等待直接返回结果。
+ [新增] 图片任务进度追踪，显示当前生成步骤（上传/预热/获取token/生成中等）。
+ [新增] 图片超时后续轮询功能，前端显示"继续等待"按钮。
+ [新增] 设置页新增图片二次确认、超时等待时间、自动重新登录等配置项。
+ [优化] 优化生图页面滚动加载性能，图片懒加载、会话切换滚动位置保存与恢复。

## 1.4.0 - 2026-05-31

+ [新增] 新增AI生成可编辑PSD文件逆向。
+ [新增] 新增AI生成可编辑PPT文件逆向。

## 1.3.1 - 2026-05-30

+ [新增] 新增ChatGPT搜索调试、Skills。

## 1.3.0 - 2026-05-30

+ [新增] 新增ChatGPT搜索接口逆向。

## 1.2.4 - 2026-05-30

+ [新增] 添加聊天补全缓存与重复请求合并。
+ [新增] 新增无限画布一键跳转功能

## 1.2.3 - 2026-05-29

+ [新增] 新增账号级代理。
+ [修复] 修复503异常信息、前端邮箱换行问题。

## 1.2.2 - 2026-05-29

+ [新增] 新增Codex链路生图、支持2k,4k。
+ [新增] 支持RT刷新账号信息。

## 1.2.0 - 2026-05-28

+ [新增] 当前版本基线，包含 Web 面板、画图、号池管理、注册机、图片管理、日志管理和设置能力。
+ [新增] 前端版本号支持点击查看版本更新弹窗，展示当前版本、最新版本和更新日志。
+ [优化] 优化注册机效率，成功率大幅提高。
+ [优化] 优化生图页面配置选项。
