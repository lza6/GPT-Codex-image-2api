# Changelog

## 2.36.0 - 2026-08-14 (fomimage 提供商接入：模型前缀映射 + 自动注册号池 + 积分用完即弃)

> 新增 fomimage（FromImage AI）图片生成/编辑提供商。模型按提供商前缀 `fomimage-` 区分，自动注册引擎用 temp-mail 一次性邮箱 + 每号独立代理 + 不规则密码，注册送 50 积分、按上游 costCredits 扣减、quota 归零自动剔除（用完即弃）。

**模型映射（按提供商前缀区分）：**
+ [新增] `services/providers/registry.py` 注册 fomimage ProviderMeta（12 模型，含 6 个文生图 `-text` 变体）
+ [新增] `services/fomimage_pricing.py`：12 模型完整定价表（`quality|resolution` 组合键、参考图加价、includedInputImages），`estimate_credits()` 复刻上游积分公式（对齐 HAR 实测 gpt-image-2 medium|2K+2图=50）
+ [新增] `utils/helper.py` `split_image_model`/`is_supported_image_model` 识别 `fomimage-` 前缀；`router_service.py` 前缀路由；`/v1/models` 暴露 fomimage 模型（owned_by=fomimage）

**fomimage 上游客户端：**
+ [新增] `services/fomimage_backend_api.py`：参考图上传（CurlMime multipart）→ 建任务 → 轮询（2.5/5/10s 档）→ 下载结果图；每账号独立代理
+ [新增] `services/protocol/fomimage_image.py`：OpenAI size/quality → fomimage options（aspectRatio/resolution/quality）映射 + 生成协议适配
+ [改造] `conversation.py` `_generate_single_image` 按 `account.provider=="fomimage"` 分派到 fomimage 路径；`account_service.get_available_access_token` 对 fomimage 账号跳过 OpenAI 远程校验

**自动注册引擎（temp-mail + 每号独立 IP）：**
+ [新增] `services/registration/fomimage/`：`temp_mail.py`（POST /mailbox 建一次性邮箱 + 轮询收 6 位验证码）、`engine.py`（建邮箱→signup→收码→verify→signin→查余额→入池，密码随机不规则 14-18 位，注册错峰 1-3s）、`coordinator.py`（批量注册 + 自动补号 watcher）
+ [新增] 每号独立出口 IP：`resolve_account_proxy(email)` 走免费代理池粘性绑定（proxy_pool.select_sticky）
+ [新增] API：`POST /api/registration/fomimage/register` + `GET /api/registration/fomimage/status`（require_admin）
+ [改造] `registration/config.py` 新增 `FomimageRegistrationConfig`（registration.fomimage 段）；`api/app.py` lifespan 启动 fomimage 补号 watcher

**号池用完即弃 + 积分扣减：**
+ [新增] `account_service.mark_image_credits_result()`：按上游 costCredits 扣本地 quota，quota 归零 → 限流 → `auto_remove_rate_limited_accounts` 自动剔除
+ [新增] `config.example.json`/`config.json` `registration.fomimage` 配置段（enabled/proxy_mode/min_accounts/register_batch/pool_quota）

**规模化增强（一号一指纹 + 批量并发 + 多邮箱源）：**
+ [新增] `services/fomimage_fingerprint.py`：一号一指纹 —— 随机 curl_cffi impersonate（chrome110/116/120/124/131/edge101）+ 匹配 UA + 平台特征；注册与调用同账号固定（`fomimage_fingerprint` 字段随账号入库）
+ [新增] `services/registration/fomimage/mail_source.py`：邮箱源统一抽象 + 优先级（temp-mail 免费 → luckmail 付费购买 → gptmail 备用），`create_mailbox_source` 自动 fallback
+ [增强] `email_sources` 配置（兼容字符串/数组）、`register_workers` 并发注册（各号独立 IP/指纹）、`luckmail` 购买参数（复用 grok LuckMailClient 契约）
+ [增强] `POST /api/registration/fomimage/register` 批量上限 10 → 500；前端卡片批量数量输入 + 指纹/IP/邮箱源/并发策略展示 + 号池规模
+ [增强] fomimage 出图写日志（summary 含 文生图/图生图 → usage_agg 聚合 image_calls），黑匣子可见

**前端：**
+ [新增] 设置页「fomimage 自动注册」卡片：号池健康（可用数/补号阈值/状态）+ 手动触发注册 + 刷新（`web/src/app/settings/components/fomimage-registration-card.tsx`）
+ [增强] 图片工作台 provider 切到 fomimage 时展示全部 12 模型（nano-banana/seedream 命名不含 image 也展示）
+ [增强] 设置页 providers-card 更新 fomimage 已接入说明

**测试与验收：**
+ [测试] `test/test_fomimage_pricing.py`（12 模型映射 + 积分公式 13 用例）、`test/test_fomimage_registration.py`（temp-mail/密码/引擎/coordinator/API 鉴权 14 用例）、`test/test_fomimage_provider.py`（options 映射/生成流/分派/扣费 9 用例）
+ [测试] `test/test_fomimage_live.py`（`-m live`，真实上游 E2E：注册→收码→上传→图生图→下载→余额 50→40 全通过）
+ [验收] 全量 pytest 通过 + ruff 0 错误 + 前端 tsc 0 错误 + build 成功

**部署期修复（服务器实测暴露，随 v2.36.0 一并合入）：**
+ [修复] `fetch_remote_info` 对 provider=fomimage 账号跳过 OpenAI get_user_info：fomimage 账号入库后不再被 account-watcher/refresh 误删（此前被 InvalidAccessTokenError 移除导致号池静默清空）
+ [修复] fomimage 会话 cookie 随账号入库（`fomimage_cookies` 字段）：fromimage 业务接口凭 cookie 认证，此前入池只存 access_token 导致生成期 Unauthorized；engine 注册后提取 `__Secure-better-auth.session_token`，FomimageBackendAPI 构造恢复认证态
+ [部署] 服务器（腾讯云东京 23456）已部署 v2.36.0：容器 healthy、`/version` 2.36.0、`/v1/models` 12 个 fomimage 模型、fomimage 号池 3 账号带 cookies、真实出图验证通过（wan-2.7-text 扣 10 积分 50→40）
+ [边界] 服务器自动注册受限于邮箱源：temp-mail 对数据中心 IP 返回 CF 403（本机家庭 IP 可注册）、gptmail 428、luckmail 未配 key——需配 luckmail key 或可访问 temp-mail 的出站代理后自动补号生效

## 2.35.0 - 2026-08-12 (GZip 修复 + 救号流程化 + 日志/审计过滤 + 可观测指标 + 多 worker 评估 + 文档保鲜)

> 6 并行 agent 交付 + GZip hotfix。修复服务器访问 `ERR_INVALID_CHUNKED_ENCODING` 与图片 URL 回环地址。

**访问稳定性修复：**
+ [修复] 移除 GZipMiddleware：gzip+Transfer-Encoding: chunked 组合在代理链路（v2ray/Clash）下触发 Chrome `ERR_INVALID_CHUNKED_ENCODING`（curl 宽容、Chrome 严格），改走 identity+Content-Length 根治
+ [修复] 服务器 `base_url` 配置空导致图片 URL 写死 `127.0.0.1`：设 `config.base_url` 为公网地址，图片/日志详情可正常渲染

**4.2 救号流程化：**
+ [新增] `POST /api/accounts/revive`：批量救号端点（require_admin + 审计 + 事件 `account.recovered` + 并发限流复用 `image_account_concurrency`）
+ [增强] `revive_abnormal.py --dry-run`：可救/不可救分类清单；不可救账号落 `revive_skipped` 标记防 watcher 空转
+ [新增] 前端账号页「批量救活」按钮（确认弹窗，明示烧配额/风控风险）
+ [测试] `test/test_account_revive.py` 20 用例（分类/限流/事件/skipped/鉴权/审计）

**4.3 日志/审计链路：**
+ [新增] `/api/audit?actor` 过滤（actor 兼容匹配 actor/operator 字段）
+ [增强] `/api/logs?account_email` 端到端测试补全（过滤实现在 v3.1.1 已落地）+ 账号详情抽屉「近 10 条行为」时间线

**5.2 可观测性：**
+ [新增] `c2api_dashboard_request_duration_seconds` histogram（dashboard 13 端点装饰器 + `metrics_sample_rate` 采样开关，零开销关闭）

**5.3 多 worker 评估：**
+ [评估] 本机无 Docker 记边界，产出 `docs/assessment-multiworker-scale.md`；关键发现：熔断器未走 shared_state（多 worker 状态分裂风险）、stress_test 为单进程模型无法验证 workers>1

**5.4 文档保鲜：**
+ [文档] product-strategy 重写（告警已实现/接线是缺口 + 纠正 4 处过时缺口）+ onboarding 补「验证 E2E」章节

**验收：** 契约守卫断链=0 漂移=0；新功能 59 测试全绿；tsc 0 错误 + build 成功；E2E 16 passed / 0 failed。

## 2.34.0 - 2026-08-12 (里程碑3 稳定性与可观测性 + 里程碑5 性能与容量 + 工程效能 + Provider Phase 4)

> 对应任务文档「4.3 里程碑3（原计划 v3.2.0）」「4.5 里程碑5（原计划 v3.4.0）」「VII 工程效能」「2.6 Provider Phase 4」。本批 11 个并行 agent 交付，八道防线 8/8 PASS。

**Provider Phase 4 + grok（多 Provider 可用化）：**
+ [新增] `services/providers/base.py` — ProviderMeta 加 `capabilities`；`registry.py` grok `enabled=True` + 11 个 models（grok-4/-3/-2 系列 + grok-3-image/grok-2-image）
+ [新增] 生图 provider 透传链路：`api/ai.py` ImageGenerationRequest + `image_tasks`/`image_inputs` 读 provider → `image_task_service` 透传 → `protocol/conversation.py` ConversationRequest + `get_available_access_token(provider=)` 按 provider 过滤账号
+ [新增] 前端三入口切换器：账号列表 provider 筛选（切换即重拉）+ 设置页 ProvidersCard（默认 Provider localStorage）+ 图片工作台提供商下拉 + 模型联动
+ [边界] grok 真实出图需外部上游凭据（xAI API/账号），已标注降级行为

**里程碑3 稳定性与可观测性：**
+ III-01 回收站根因面板：`trash_service.stats()` 加 `by_reason_top`/`trend` + `api/accounts.py` top_reasons query + `trash-dialog.tsx` recharts 分布图
+ III-02 调度 A/B 可观测：`scheduler_pick_total` 加 `mode` 标签 + 补 `record_scheduler_mode_switch`（此前被静默吞掉）+ per-mode 命中/失败率/延迟 + dashboard 模式对比卡
+ III-03 配额预警联动：`account_lifetime` 配额剩余天数第三信号（最小观测窗口防误判）+ 档位降级「≤1 天 risky / ≤3 天 warm，只降不升」
+ III-04 慢查询清零：json/db 存储优化（内容比对跳过覆写 + 键列扫描/定向更新/批量删除）+ `c2api_storage_operation_duration_seconds` 指标 + slow_query JSON 门禁；2 热点 accepted_degradation
+ III-05 连接池泄漏：`session_pool` 借用追踪 + stats + leak_report + cleanup_stale 健康接管 + `session_pool.leak` 告警
+ III-06 备份完整性：上传后读回 sha256 比对三态 + `backup.checksum_mismatch` 告警（不叠加 failure）+ 状态字段
+ III-07 告警多通道：Telegram/SMTP/企微/钉钉通道抽象 + `config.alert_channels`（env 覆盖）+ 前端配置 UI

**里程碑5 性能与容量：**
+ V-01 bundle 优化：recharts 懒加载摘除（dashboard -119KB / accounts -116KB）+ bundle-analyzer + 测量脚本；150/300KB 预算如实说明未达（框架下限）
+ V-02 响应缓存扩展：`/api/logs`、trash、usage、events 4 端点接入（TTL + 写侧 invalidate + ?refresh=1）
+ V-03 虚拟列表：日志/图片/账号三列表 `useVirtualizer` + 滚动位置记忆
+ V-04 性能基准化：`stress_test` JSON 基准 + `benchmark_check` 阈值断言（实测 149.5 rps / p99 334ms）

**工程效能：**
+ VII-01 覆盖率门禁：pytest-cov + `[tool.coverage]` fail_under=55 + `coverage_guard.py`（实测 62%，增量门每档 +5pt）
+ VII-02 防线进 CI：guards job（契约/SQL/变异/文档同步）+ coverage gate + OpenAPI/SDK --check
+ VII-03 文档保鲜：`scripts/hooks/` githooks pre-commit（Node，core.hooksPath）
+ VII-04 OpenAPI/SDK 自动化：`generate_openapi_spec.py --check` + `generate_sdks.py --check`（GBK 安全）
+ 防线扩至**八道**（+性能基准 +覆盖率门禁）；修复 stress_test 慢存储注入空跑 + 补 hypothesis/aiosqlite 预存依赖缺口

## 2.33.0 - 2026-08-12 (R2 图片存储配置接线闭环 + E2E 体系 + 变异探针增强)

**R2 图片存储前端配置接线（6 步闭环）：**
+ [新增] `web/src/lib/api.ts` — `ImageStorageMode` 新增 `r2`/`r2_local`；`ImageStorageSettings` 补 `r2_account_id`/`r2_access_key_id`/`r2_secret_access_key`/`r2_bucket`/`r2_prefix` 五字段
+ [新增] `web/src/app/settings/store.ts` — normalizeConfig/saveConfig 补 r2 字段与默认值；模式白名单放开 `r2`/`r2_local`；测试按钮 toast 按模式显示「R2 / WebDAV」
+ [新增] `web/src/app/settings/components/config-card.tsx` — 保存模式新增「仅 R2」「本机 + R2」；R2 五字段表单（Account ID / Access Key / Secret / Bucket / 对象前缀）；连接测试按钮按模式显示「测试 R2 / 测试 WebDAV」；当前模式文案覆盖 5 种模式
+ [变更] `api/system.py` — `/api/image-storage/test` 按保存模式分流：r2/r2_local 调 `image_storage_service.test_r2`，否则 `test_webdav`
+ [修复] `web/src/lib/api.ts` — diagnose/healing 4 个封装函数 `resp.json()` 误用（`httpRequest` 已返回 axios 解析后的 data，运行时必崩）→ 直接返回 + 显式泛型
+ [测试] `test/test_image_storage_service.py` — 新增 R2Client 层 16 项 + API 端点 3 项：validate 缺字段 / object_key 前缀与路径穿越拒绝 / SigV4 签名结构 + 独立参考实现重算对比 / put/get/delete HTTP 语义 / ListObjectsV2 解析 + continuation 分页 / 连接测试 / sync 错误映射 400 / 测试端点按模式分流

**E2E 体系纳入版本控制：**
+ [新增] `e2e/` — Playwright 全链路（login/dashboard/accounts/batch-notify 4 spec + Page Object + global-setup 自动起真实前后端 + 系统 Edge）
+ [新增] `docs/e2e.md` — 前置/运行/结构/覆盖范围/产物清理/CI 决策说明
+ [变更] `.gitignore` — 排除 `e2e/test-results/`、`e2e/playwright-report/`、`e2e/node_modules/`

**变异探针增强：**
+ [增强] `scripts/mutation_probe.py` — 锚点覆盖扩展至 14 个测试文件（282 行增量）
+ [测试] 锚点断言入 test_circuit_breaker/test_account_scheduler 等（熔断阈值/半开恢复/超时、重试预算、限流窗口、调度分、淘汰方向）

**测试：** R2 存储 29 项；全量回归见 `workflow_status.md` 第二十二轮。

## 2.32.0 - 2026-08-11 (账号回收站 + 雨露均沾调度 + 粘性 IP)

**账号回收站（可视化剔除记录）：**
+ [新增] `services/trash_service.py` — TrashService 回收站（记录被自动剔除/手动删除账号：email/token/剔除时间/状态/上游返回原因/来源，线程安全 + 原子落盘 + 上限裁剪）
+ [新增] `api/accounts.py` — `GET /api/accounts/trash`（列表+统计）、`POST /api/accounts/trash/clear`（清空）、`POST /api/accounts/trash/restore`（恢复）
+ [新增] `web/src/components/trash-dialog.tsx` — 回收站弹窗（统计卡片 + 原因分布 + 记录列表，含剔除时间/上游原因）
+ [新增] `web/src/app/accounts/page.tsx` — 账户列表工具栏"回收站"按钮
+ [新增] `services/account_service.py` — `delete_accounts`、`account_deactivated` 停用路径自动记入回收站
+ [新增] `web/src/lib/api.ts` — `fetchTrash`/`clearTrash`/`restoreTrash` 类型与函数
+ [测试] `test/test_trash_scheduler_sticky.py` — 回收站增删查/统计/恢复/上限裁剪 + least_used 调度 + 粘性 IP 测试

**雨露均沾调度（least_used）：**
+ [新增] `services/account_service.py` — `_pick_least_used` 调度模式：选最近最少使用的账号（last_used_at 最久远者优先），避免集中突刺单号，让免费号更像真人分布
+ [新增] `services/config.py` — `scheduler_mode` 枚举新增 `least_used`
+ [新增] `web/src/lib/api.ts` + settings UI — 调度模式下拉新增"雨露均沾（least_used）"

**粘性 IP（常规请求路径接入）：**
+ [新增] `services/proxy_service.py` — `get_profile` 账号级 kookeey 粘性代理：同号固定住宅 IP、异号异 IP，常规对话/生图请求自动接入（仅 kookeey proxy_enabled 开启时生效，按量计费）
+ [变更] `config.json` — `kookeey.proxy_enabled: true`（需开启才启用粘性 IP）

**测试：** 回收站 7 + least_used 3 + 粘性 IP 1 + 回归 1161 passed（仅 openapi spec 需重新生成后 15 passed）

## 2.31.0 - 2026-08-11 (前端深度体验 + SSE 事件流 + 契约断链清零)

**4.3.1 组件交互反馈系统：**
+ [新增] `web/src/utils/motion.ts` — 统一动效预设（fadeIn/slideUp/scaleIn/stagger/expandCollapse/ripple），所有组件共享 framer-motion 动画配置
+ [新增] `web/src/hooks/use-interaction-feedback.ts` — 统一交互反馈 Hook：点击涟漪坐标 + 加载/成功/错误三态 + 震动反馈
+ [新增] `web/src/components/ui/ripple.tsx` — 波纹点击组件（点击位置扩散涟漪）
+ [新增] `web/src/components/ui/progress-bar.tsx` — 进度条组件（确定/不确定模式，sm/md/lg 尺寸，四色主题）
+ [改进] `web/src/components/ui/button.tsx` — 集成 action 异步操作，自动 loading/success/error 三态动画 + 涟漪
+ [改进] `web/src/components/ui/input.tsx` — 实时校验 + 字符计数 + 清空按钮 + 左侧图标 + 焦点动画 + 校验错误提示
+ [改进] `web/src/components/ui/select.tsx` — 新增 `SearchableSelect` 搜索过滤下拉框（搜索 + 分组 + 选中高亮）
+ [改进] `web/src/components/ui/table.tsx` — 新增 `ExpandableRowContent` 可展开行动画（AnimatePresence 高度过渡）
+ [改进] `web/src/components/ui/dialog.tsx` — 新增拖拽移动 + 堆叠管理（z-index 提升 + stackId 唯一标识）
+ [改进] `web/src/lib/toast-helper.ts` — Toast 进度条复用 ProgressBar 组件 + `toastPositioned` 位置定制

**4.3.2 响应式 + 移动端优化：**
+ [新增] `web/src/hooks/use-breakpoint.ts` — 响应式断点 Hook（mobile/tablet/desktop，matchMedia 监听）
+ [改进] `web/src/app/dashboard/page.tsx` — 接入实时事件流卡片（EventStream 组件，此前为死代码未被任何页面使用）

**4.3.3 SSE 实时数据管道（升级增强）：**
+ [新增] `api/dashboard.py` — `GET /api/events/stream` SSE 事件流端点（1s 推送事件，含自动去重）
+ [新增] `api/dashboard.py` — `GET /api/dashboard/events` 端点（读 events.jsonl 最近事件，SSE 事件流同源）
+ [新增] `api/dashboard.py` — `_fetch_recent_events()` 从 events.jsonl 读取最近事件（限量 + JSON 容错）
+ [新增] `api/app.py` — 事件总线持久化订阅：账号/熔断/备份/Provider 事件写入 events.jsonl + `_trim_events_file` 行数裁剪
+ [改进] `web/src/hooks/use-realtime.ts` — 支持多行 JSON 解析 + 多字段通道提取（data/channel 字段兼容）

**契约断链清零（3 → 0）：**
+ [修复] `api/accounts.py` — 新增 `GET /api/accounts/tags`（去重 label 标签列表 + count）
+ [修复] `api/accounts.py` — 新增 `POST /api/accounts/export-csv`（CSV 导出，仅非敏感字段）
+ [修复] `api/accounts.py` — 新增 `POST /api/accounts/detail`（按 token 返回账号详情 + 熔断状态）
+ [测试] `test/test_accounts_detail_tags_export.py` — 9 个测试覆盖 tags 去重/详情 404/CSV 导出
+ [测试] `test/test_events_stream.py` — 8 个测试覆盖事件流鉴权/events.jsonl 持久化/行数裁剪
+ [契约] `scripts/contract_guard.py` — SNAPSHOT/DYNAMIC_KEY_ENDPOINTS 新增 `/api/dashboard/events`

**Bug 修复：**
+ [修复] `web/src/components/top-nav.tsx` — 移除桌面端冗余垂直侧边栏及折叠按钮（PanelLeft），顶部导航已完整展示所有导航项，避免 UI 严重重复
+ [修复] `services/account_service.py` — `list_abnormal_tokens_for_recover` 排除已达重试上限且无下次重试时间的账号。此前已放弃恢复的异常账号被无限重试，invalid_count 累加到 800+ 仍反复尝试
+ [测试] `test/test_account_self_heal.py` — 新增 4 个恢复候选筛选测试（排除已放弃/额度耗尽、保留可恢复账号）
+ [文档] `docs/openapi.json` — 重新生成（新增 4 端点，路径数 116→120）

## 2.30.0 - 2026-08-11 (3.1.3 请求级响应缓存)

**3.1.3 请求级响应缓存：**
+ [新增] `api/response_cache.py` — `ResponseCache` 类（`cachetools.TTLCache` 封装），支持 get/set/register/invalidate/get_cache_stats/get_ttl，线程安全
+ [新增] `api/response_cache.py` — 全局单例 `response_cache`，预注册 5 个端点 TTL：`/v1/models` 60s、`/api/providers` 30s、`/api/dashboard/scheduler` 10s、`/api/accounts` 5s、`/api/dashboard/ops` 15s
+ [新增] `api/response_cache.py` — `apply_cache_headers()` 函数，为响应添加 `Cache-Control: max-age=N` 头
+ [新增] `api/ai.py` — `/v1/models` 端点接入缓存，支持 `?refresh=1` 强制刷新
+ [新增] `api/providers.py` — `/api/providers` 端点接入缓存，支持 `?refresh=1` 强制刷新
+ [新增] `api/dashboard.py` — `/api/dashboard/scheduler`、`/api/dashboard/ops` 端点接入缓存，支持 `?refresh=1` 强制刷新
+ [新增] `api/accounts.py` — `/api/accounts` 端点接入缓存，支持 `?refresh=1` 强制刷新；写操作（POST/DELETE/refresh/update/batch）自动 invalidate 缓存
+ [新增] `test/test_response_cache.py` — 22 个测试覆盖：基础 get/set、TTL 过期、失效策略（单/全量）、统计查询、并发安全、Cache-Control 头、边界（0 TTL/大值/自定义 maxsize/链式注册）
+ [依赖] pyproject.toml — 新增 `cachetools>=5.3.0`
+ [测试] 22 passed / 0 failed 在 test_response_cache.py；全量回归 1087+ 通过，无回归

**5.1.1 容量预测仪表盘（前端补齐）：**
+ [前端] `web/src/lib/api.ts` — 新增 `fetchCapacity()` / `CapacityStats` 类型
+ [前端] `web/src/app/dashboard/page.tsx` — 新增容量规划卡片区域（日均请求/活跃账号/单号日均/扩缩容建议+趋势图）
+ [契约] `scripts/contract_guard.py` — SNAPSHOT_ENDPOINTS 新增 `/api/dashboard/cost`

**5.1.2 成本优化（全新模块）：**
+ [新增] `services/cost_service.py` — CostService 类：三源合并（usage_agg 用量+provider 分布+ kookeey 流量），无 kookeey 配置降级
+ [新增] `api/dashboard.py` — `GET /api/dashboard/cost` 端点，require_admin 鉴权，同线程池
+ [新增] `test/test_cost_service.py` — 4 个测试覆盖正常返回/未配置降级/异常降级/字段契约
+ [前端] `web/src/lib/api.ts` — 新增 `fetchCostOverview()` / `CostOverview` 类型
+ [前端] `web/src/app/dashboard/page.tsx` — 新增成本优化卡片区域（总调用量/Provider 分布/kookeey 流量/调用类型）

**测试：** 9 passed（cost 4 + capacity 5）

**4.1.2 自适应调度器：**
+ [新增] `services/adaptive_scheduler.py` — AdaptiveScheduler 类：基于运行指标（并发>100→least_load、成功率<0.8→predictive、模型多样性>0.7→affinity、默认→weighted_random）自动切换调度模式，含最短驻留时间守卫（120s）防抖动
+ [新增] `services/prometheus_metrics.py` — `chatgpt2api_scheduler_mode_switches_total{from_mode,to_mode}` 模式切换计数指标，`record_scheduler_mode_switch()` 函数
+ [新增] `services/config.py` — `scheduler_adaptive_enabled`（bool，默认 false）、`scheduler_adaptive_interval_seconds`（float，默认 30）配置项，含环境变量覆盖
+ [新增] `api/dashboard.py` — `GET /api/dashboard/adaptive_scheduler` 端点（自适应调度器状态+运行指标+切换历史），看板 SSE 含 `scheduler_adaptive_enabled` 字段
+ [新增] `services/account_service.py` — `_acquire_next_candidate_token` 接入自适应调度器，`effective_mode` 由 `AdaptiveScheduler.tick()` 驱动
+ [新增] `config.json` — 新增 `scheduler_adaptive_enabled: false`、`scheduler_adaptive_interval_seconds: 30`
+ [前端] `web/src/lib/api.ts` — SettingsConfig 和 OpsOverview 新增 `scheduler_adaptive_enabled`、`scheduler_adaptive_interval_seconds` 字段
+ [前端] `web/src/app/settings/store.ts` — normalizeConfig 新增归一化，`setSchedulerAdaptiveEnabled`、`setSchedulerAdaptiveIntervalSeconds` action
+ [前端] `web/src/app/settings/components/config-card.tsx` — 自适应调度器开关 UI（checkbox + 条件显示的检查间隔输入）
+ [测试] `test/test_scheduler_modes.py` — TestAdaptiveScheduler 10 个测试（模式选择/切换守卫/指标收集/历史记录/状态查询/模块导入/高负载/低成功率/高多样性/默认模式）
+ [测试] 28 passed / 0 failed in test_scheduler_modes.py

**3.2.3 配置热加载：**
+ [新增] `services/config_watcher.py` — ConfigWatcher 类：轮询检测 config.json 的 mtime 变化，触发 ConfigStore 热加载并发布 CONFIG_CHANGED 事件
+ [新增] `services/config_watcher.py` — 支持 reload_callback 注入，默认回调 ConfigStore._try_reload
+ [新增] `services/config.py` — `config_watch_enabled` 配置项（bool，默认 true），`_BOOL_FIELDS` 校验，`get()` 序列化，环境变量 `CHATGPT2API_CONFIG_WATCH_ENABLED` 覆盖
+ [新增] `api/app.py` — lifespan 启动 ConfigWatcher（config_watch_enabled 控制），stop_event 优雅停止
+ [新增] `services/event_bus_init.py` — 订阅 CONFIG_CHANGED 事件，记录日志
+ [变更] `config.json` — 新增 `config_watch_enabled: true`
+ [变更] `services/config.py` — 移除模块级 `from services.storage.base import StorageBackend`，改为惰性导入，消除循环依赖
+ [前端] `web/src/lib/api.ts` — SettingsConfig 新增 `config_watch_enabled` 字段
+ [前端] `web/src/app/settings/store.ts` — normalizeConfig 新增 `config_watch_enabled` 归一化
+ [测试] `test/test_config_watcher.py` — 7 个测试覆盖文件变更检测/事件通知/轮询间隔/停止/幂等start/坏路径/连续变更
+ [测试] 913 passed / 0 failed, 33 deselected

## 2.25.0 - 2026-08-11 (智能诊断引擎 + 自动修复 2.0)

**4.2.2 智能诊断引擎：**
+ [新增] `services/diagnostic_engine.py` — DiagnosticCheck ABC + 7 诊断检查器（熔断器/账号健康/代理连通/存储空间/限流/连接池/配置一致性）+ DiagnosticEngine
+ [新增] `api/system.py` — `POST /api/system/diagnose` 运行诊断、`GET /api/system/diagnose` 获取上次诊断
+ [新增] `test/test_diagnostic_engine.py` — 13 个测试覆盖数据模型 + 引擎 + 7 检查器
+ [新增] `web/src/app/system/diagnose/page.tsx` — 诊断报告页面（摘要卡片 + 逐项详情 + 严重级别图标）
+ [新增] `web/src/app/system/page.tsx` — 系统主页面（重定向到诊断）

**4.2.3 自动修复 2.0：**
+ [新增] `services/auto_healer.py` — HealingHandler ABC + 6 修复器（会话重建/磁盘清理/内存缓解/配置恢复/代理切换/熔断探测）+ AutoHealer + 成功率统计
+ [新增] `api/system.py` — `GET /api/system/healing/history` 修复历史、`POST /api/system/healing/run` 一键修复、`POST /api/system/healing/clear-history` 清除历史
+ [新增] `test/test_auto_healer.py` — 11 个测试覆盖数据模型 + 6 修复器 + 统计
+ [新增] `web/src/app/system/healing/page.tsx` — 修复历史页面（统计卡片 + 逐条记录）
+ [新增] `web/src/lib/api.ts` — 诊断/修复类型定义 + 5 个请求函数
+ [新增] `web/src/components/top-nav.tsx` — 导航栏加"系统诊断"项
+ [新增] `services/config.py` — `auto_heal_enabled`（默认 true）、`auto_diagnose_interval_minutes`（默认 60）配置项
+ [新增] `config.json` — 默认配置值
+ [测试] 24 测试全绿 + 前端构建成功

**存储层异步化：**
+ [新增] `services/storage/base.py` — `AsyncStorageBackend` 异步存储后端基类（所有方法 async）
+ [新增] `services/storage/async_database.py` — `AsyncDatabaseStorageBackend` 异步数据库后端（sqlalchemy.ext.asyncio + aiosqlite/asyncpg）
+ [新增] `services/storage/async_bridge.py` — `AsyncToSyncStorageBackend` 同步→异步桥接适配器（线程池 asyncio.run 桥接）
+ [新增] `services/storage/factory.py` — 支持 `STORAGE_ASYNC_ENABLED` 环境变量，自动创建异步后端
+ [新增] `services/config.py` — `storage_async_enabled` 配置项（默认 false，布尔类型校验）
+ [新增] `config.json` — `storage_async_enabled: false` 默认值
+ [新增] `web/src/lib/api.ts` — `SettingsConfig.storage_async_enabled` 字段
+ [新增] `web/src/app/settings/store.ts` — `storage_async_enabled` 状态 + setter
+ [新增] `web/src/app/settings/components/config-card.tsx` — 异步存储后端开关 UI
+ [新增] `test/test_async_storage.py` — 14 个测试覆盖异步后端全路径 + 桥接适配器
+ [变更] `services/storage/base.py` — 新增 `AsyncStorageBackend` ABC，与原有 `StorageBackend` 共存
+ [依赖] 新增 `aiosqlite`、`asyncpg` 异步驱动（已安装）

## 2.24.0 - 2026-08-11 (事件总线 Pub/Sub 增强)

**EventBusV2 增强：**
+ [新增] `services/event_bus.py` — EventType 枚举（26 个事件类型，含账号/调度/熔断/系统/代理/备份/配置）
+ [新增] `services/event_bus.py` — Event.source/severity 增强字段，subscribe_all 通配符订阅
+ [新增] `services/event_bus.py` — 异步消费者（asyncio.Queue + 后台协程），publish_async 入队/publish_sync 同步入队
+ [新增] `services/event_bus.py` — 事件统计（发布计数/severity 分布/handler 耗时/死信计数/消费者深度）
+ [新增] `services/prometheus_metrics.py` — 4 个事件指标：c2api_events_published_total / c2api_events_consumer_processed_total / c2api_events_dead_letter_total / c2api_events_handler_duration_seconds
+ [新增] `services/event_bus_init.py` — 注册新事件类型 ACCOUNT_BLOCKED/SCHEDULER_*/PROXY_*/SYSTEM_* 的订阅者
+ [新增] `api/app.py` — lifespan 启动/停止事件总线消费者后台任务
+ [测试] `test/test_event_bus.py` — 42 个测试覆盖 EventType 枚举/Event 增强/subscribe_all/消费者模式/事件统计/边界情况
+ [测试] `test/test_event_bus_events.py` — 4 个测试覆盖业务事件发布

## 2.17.0 - 2026-08-10 (看板 v3 深度升级)

**看板升级：**
+ [新增] `web/src/components/dashboard/kpi-bar.tsx` — 顶部 KPI 自动滚动条（motion 数字滚动动画）
+ [新增] `web/src/components/dashboard/provider-radar.tsx` — Provider 多维雷达对比图（recharts RadarChart + 趋势折线图）
+ [新增] `web/src/components/dashboard/health-heatmap.tsx` — 账号健康热力图（CSS Grid 颜色编码）
+ [新增] `web/src/components/dashboard/event-stream.tsx` — 实时事件流（类型过滤 + 点击详情 + motion 动画）
+ [新增] `web/src/app/dashboard/page.tsx` — 集成 KpiBar/ProviderRadarChart/HealthHeatmap/EventStream 四个新组件
+ [新增] `api/dashboard.py` `GET /api/dashboard/events` — 看板事件端点
+ [新增] `services/event_bus.py` — 环形缓冲区记录最近 100 条事件 + `get_recent_events()` 查询方法
+ [新增] `web/src/lib/api.ts` — `DashboardEvent` / `DashboardEventsResponse` 类型 + `fetchDashboardEvents()` 函数
+ [新增] `web/src/app/globals.css` — CSS 变量体系补充（间距/阴影/动画时长/ease）
+ [变更] `api/dashboard.py` SSE `_build_stream_payload` 新增 events 字段实时推送
+ [变更] `web/src/app/dashboard/page.tsx` SSE 事件处理新增 `payload.events` 实时更新

## 2.20.0 - 2026-08-10 (查询优化闭环)

**2.3 查询优化：**
+ [新增] `services/config.py` — `auth_key` 改用 `@functools.cached_property` 缓存（每个请求鉴权高频读取），`app_version` 改用 `cached_property` 缓存
+ [新增] `services/config.py` — `metrics_sample_rate` 配置项（float 0.0~1.0，默认 1.0），`_FLOAT_FIELDS` 校验，`get()` 序列化，环境变量 `CHATGPT2API_METRICS_SAMPLE_RATE` 覆盖
+ [新增] `services/prometheus_metrics.py` — `_normalize_path()` 路径归一化函数，将含数字/UUID/长随机串的动态路径收敛为 `{id}`，防高 cardinality label 膨胀
+ [新增] `services/prometheus_metrics.py` — `record_http_request()` 自动调用 `_normalize_path()` 归一化 path 标签
+ [新增] `api/app.py` — `access_log_middleware` 接线 `record_http_request`，支持采样率配置（`_should_sample` 基于 request_id 哈希的确定性采样）
+ [新增] `config.json` — `metrics_sample_rate` 默认值 1.0
+ [前端] `web/src/lib/api.ts` — `SettingsConfig` 新增 `metrics_sample_rate` 字段
+ [前端] `web/src/app/settings/store.ts` — `normalizeConfig` 新增 `metrics_sample_rate` 归一化
+ [测试] `test/test_query_optimization.py` — 12 个测试覆盖 metrics_sample_rate 默认值、环境变量覆盖、clamp、schema 校验；路径归一化数字/hex/UUID/短路径/静态路径；record_http_request 归一化验证

## 2.19.0 - 2026-08-10 (连接池四优化)

**Session Pool 性能增强（v2.17.0 四优化）：**
+ [新增] `services/session_pool.py` — 连接健康预检：从池中取出时发送轻量 HEAD 请求验证，断连自动重建，减少断连请求失败 50%+
+ [新增] `services/session_pool.py` — 动态冷却期：根据错误率线性映射缩容冷却期（1min~5min），错误率越高冷却期越长，更精准的缩容决策
+ [新增] `services/session_pool.py` — 连接 TTL：连接最大存活时间（默认 300s），到期自动重建，避免上游 TIME_WAIT 堆积
+ [新增] `services/session_pool.py` — 指数退避重连：连接失败后重试间隔 1s→2s→4s→8s→16s→cap，减轻上游风暴压力
+ [新增] `services/config.py` — `session_pool_health_check_enabled` 配置项（布尔，默认 true），`_BOOL_FIELDS` 校验表 + `get()` 序列化
+ [新增] `config.json` — `session_pool_health_check_enabled: true` 默认值
+ [新增] `web/src/lib/api.ts` — `SettingsConfig` 新增 `session_pool_health_check_enabled` 字段
+ [测试] 7 新增用例（健康预检/错误率/动态冷却/连接TTL/指数退避/stats新字段/关闭健康检查），27 全绿

## 2.18.0 - 2026-08-10 (多模型路由)

**8.3 多模型路由：**
+ [新增] `services/config.py` — `model_upstream_map` 配置项（dict[str,str] 用户面向模型名→上游模型名映射表），`_DICT_FIELDS` 校验，`get()` 序列化
+ [新增] `services/openai_backend_api.py` — `_resolve_upstream_model` 静态方法将用户请求模型名映射为上游模型名（映射表命中→返回映射值，空/auto→返回默认值，未命中→透传原值），`_conversation_payload` 和 `_image_model_settings` 已接入映射
+ [新增] `services/protocol/openai_v1_models.py` — `list_models()` 返回映射表中的模型，使用户能在 `/v1/models` 中看到映射后的模型名
+ [新增] `config.json` — `model_upstream_map`（`{}`）默认值
+ [前端] `web/src/lib/api.ts` — `SettingsConfig` 新增 `model_upstream_map` 字段
+ [前端] `web/src/app/settings/store.ts` — `normalizeConfig` 新增 `model_upstream_map` 归一化
+ [测试] 7 新增用例（映射命中/透传/auto/空映射表/空模型名/conversation payload/list_models），全绿；705 全量全绿

## 2.17.0 - 2026-08-10 (账号管理增强 + 全局交互升级)

**3.4 账号管理增强：**
+ [新增] 虚拟滚动 — @tanstack/react-virtual 实现账号列表虚拟滚动，1000+ 账号流畅渲染
+ [新增] 列显隐定制 — 用户可自行选择显示/隐藏表格列
+ [新增] 账号详情侧面板 — 点击账号行展开右侧 Sheet 详情面板
+ [新增] 批量选择增强 — Shift 范围选择、Ctrl 多选、全选/反选
+ [新增] 账号标签系统 — 按标签过滤账号
+ [新增] 导出选中账号 — CSV/JSON 格式导出

**3.5 全局交互升级：**
+ [新增] 全局搜索 — Cmd+K 搜索框，搜索账号/设置/日志
+ [新增] 可折叠侧边栏 — 左侧可折叠侧边栏 + 面包屑导航
+ [新增] 键盘快捷键体系 — ? 键查看快捷键列表
+ [新增] 错误边界 — 全局 ErrorBoundary 组件 + 重试按钮
+ [新增] 页面过渡 — motion 页面切换动画
+ [新增] 响应式适配 — 移动端表格卡片化
+ [新增] 离线增强 — 缓存数据 + 重连自动刷新
+ [新增] 空状态引导 — 列表/表格空状态插图 + 引导文案
+ [新增] 渐进式加载 — Skeleton + 内容渐进式渲染
+ [新增] Toast 增强 — 操作撤销、进度条、分组展示

## 2.16.0 - 2026-08-10 (多 Provider 精细调度)

**8.2 多 Provider 精细调度：**
+ [新增] `services/config.py` — `provider_weights` / `provider_rate_limit_rpm` 配置项 + `_DICT_FIELDS` 校验表 + `get()` 序列化
+ [新增] `services/provider_scheduler.py` — Provider 级 rate limiter（滑动窗口，独立计数互不阻塞）、权重选取（`_pick_provider_by_weight` 配置化比率）、Provider 熔断器（阈值 3 次/60s 冷却/成功清零，独立于账号级熔断器），`get_provider_stats` 扩展 quota_remaining/weight/breaker_state/breaker_recover_in_seconds
+ [新增] `services/account_service.py` — `get_text_access_token` 接入权重调度+配额检查+熔断检查+provider fallback（配额耗尽/熔断自动转向其他 provider）；`get_available_access_token` 接入权重选取+配额/熔断检查
+ [新增] `web/src/lib/api.ts` — `ProviderStats` 类型新增 `quota_remaining`/`weight`/`breaker_state`/`breaker_recover_in_seconds`
+ [新增] `web/src/app/dashboard/page.tsx` — provider 卡片展示调度权重/配额剩余/熔断状态
+ [新增] `config.json` — `provider_weights`（`{"chatgpt": 3}`）和 `provider_rate_limit_rpm`（`{}`）默认值
+ [测试] 18 新增用例（配额隔离 6 + 权重调度 6 + 熔断隔离 6 + 新字段 1），29 全绿；692 全量全绿；五道防线全 PASS

## 2.15.0 - 2026-08-10 (轻量请求追踪 + 性能看板)

**轻量请求追踪（6.1）：**
+ [新增] `services/tracing.py` — `TracedMiddleware` 轻量请求追踪中间件（不依赖 OpenTelemetry SDK），每个请求创建 trace_id，记录 method/path/status_code/duration
+ [新增] 慢查询日志：请求耗时超过 `slow_threshold_ms`（默认 5s）自动记录慢请求告警日志
+ [新增] `contextvars` 传递 trace_id，被 metrics_service 和 log_service 消费，实现全链路追踪
+ [测试] 3 单测全绿（含 trace_id 隔离、重置、线程安全）

**性能看板验证（6.4）：**
+ [验证] `GET /api/dashboard/latency` 端点正常返回（4 单测，含总请求数/平均延迟/错误率/按路径分布）
+ [验证] `GET /api/dashboard/metrics_summary` 端点正常返回

## 2.14.0 - 2026-08-10 (告警多通道 + 日志聚合/导出/归档)

**告警多通道增强（6.2）：**
+ [增强] `services/alert_service.py` — `AlertService` 新增多通道支持：`channels` 参数可同时配置企业微信(WeCom)、钉钉(DingTalk)、通用 webhook 多通道并发发送，任一通道失败不阻塞其他通道
+ [新增] `_send_wecom` / `_send_dingtalk` / `_format_markdown` — 企业微信/钉钉机器人 Markdown 格式消息体，发送失败重试 1 次
+ [新增] `config.json` 配置项 `alert_channels` — 多通道配置（`{"channel_name": {"webhook_url": "…", "type": "wecom|dingtalk|webhook"}}`）
+ [测试] 13 单测全绿（含多通道并发、通道失败隔离、去重协同、config 加载）

**日志系统增强（6.3）：**
+ [新增] `services/log_service.py` — `LogService` 新增 `aggregate` 方法（按 type/status/hour 维度聚合统计，支持 day/hour 时间粒度）
+ [新增] `LogService.export_csv` — 导出 CSV 格式字符串（id,time,type,summary,status,error），逗号/引号转义，limit 50000
+ [新增] `LogService.archive` — 归档过期日志到 `logs-archive-YYYYMMDD.zip` 压缩文件，归档后删除原文件
+ [测试] 17 单测全绿（含聚合、CSV 导出、归档、空数据、跨天边界）

## 2.13.0 - 2026-08-10 (Provider 调度分池 + 路由分发 + 批量操作 + 自适应连接池)

**多 Provider 调度分池（Phase 2/4）：**
+ [新增] `services/provider_scheduler.py` — `ProviderScheduler` 各 provider 独立调度池（healthy/warm/risky 档位分布统计 + 可用账号统计），供前端看板展示
+ [集成] `api/dashboard.py` — `/api/dashboard/scheduler` 返回 `provider_stats` 字段，前端看板显示各 provider 账号分布卡片

**路由分发（Phase 3/4）：**
+ [新增] `services/router_service.py` — `RouterService` 按模型名前缀自动路由到对应 provider（gpt-→chatgpt, grok-→grok, claude-→chatgpt），支持 config.json 自定义路由规则
+ [集成] `services/account_service.py` — `get_text_access_token` 在 provider 为空时自动调用 RouterService 路由

**批量操作增强（5.4）：**
+ [新增] `api/accounts.py` — `POST /api/accounts/batch` 新增 `update` action，支持批量编辑账号属性（proxy/priority/status 等）
+ [测试] batch_update 单测 6 个全绿（含空 updates 拒绝、部分失败、异常处理、多字段、去重）

**自适应连接池（7.1）：**
+ [增强] `services/session_pool.py` — `SessionPool` 新增自适应扩容（`_adaptive_grow`，空闲连接不足时渐进扩容 10 或 50%）和缩容（`_adaptive_shrink`，连续错误 3 次清理最旧 20% 连接，1 分钟冷却）
+ [增强] `SessionPool.__init__` 新增 `min_size` 参数（最小保留连接数，默认 5）

**前端 Provider 切换器（Phase 4/4）：**
+ [增强] `web/src/app/accounts/page.tsx` — 账号列表新增 Provider 下拉筛选器（从 /api/providers 获取列表，grok 灰显"即将支持"）
+ [增强] `web/src/app/dashboard/page.tsx` — 看板新增 Provider 统计卡片（各 provider 账号总数/可用数/档位分布）
+ [增强] `web/src/lib/api.ts` — `SchedulerDashboard` 类型新增 `provider_stats` 字段

## 2.12.0 - 2026-08-10 (任务队列系统 + 异步图片管道 + 统一 ORM 层 + SQLite 连接池优化)

**任务队列系统（P1）：**
+ [新增] `services/task_queue.py` — 基于优先级的轻量任务队列（CRITICAL/HIGH/NORMAL/LOW），支持处理器注册 + 后台消费者线程 + 优先级 FIFO 调度 + 状态查询/取消/统计/清理
+ [新增] `services/task_queue_init.py` — 处理器注册（图片生成/编辑/续轮询/备份/日志清理），启动时由 `api/app.py` lifespan 调用
+ [迁移] 图片任务 `_submit` 和 `resume_poll` 走任务队列 CRITICAL 优先级提交（消费者未启动时回退直接起线程，保证测试兼容）
+ [测试] 24 单测全绿（含消费者线程生命周期测试）

**异步图片管道（P0）：**
+ [新增] `services/image_pipeline.py` — `ImagePipeline` 异步图片处理管道：`asyncio.Semaphore(5)` 并发限流 + 内存缓存(TTL) + `asyncio.to_thread` 转线程池处理
+ [测试] 6 单测全绿（含并发限幅验证）

**统一 ORM 层（P0）：**
+ [增强] `services/storage/base.py` — 新增 `Repository[T]` Protocol 泛型接口（find/find_one/create/update/delete/count/paginate）、`Filter` 过滤条件、`Page[T]` 分页封装、`MockRepository[T]` 内存测试实现
+ [保留] 原有 `StorageBackend` ABC 保持不动，向后兼容

**SQLite 连接池优化（P0）：**
+ [增强] `services/storage/database_storage.py` — 显式配置 `pool_size=10`、`max_overflow=5`、`pool_timeout=30`、`pool_recycle=3600`、`echo_pool=False`；SQLite 专有 `connect_args`（timeout=15, check_same_thread=False）

## 2.11.0 - 2026-08-09 (事件总线系统)

**多提供商地基状态标注（Phase 1/4）：**
+ [状态标注] `services/providers/` 三文件 docstring 全部标注 Phase 1/4 进度（__init__/base/registry），明确已完成项与后续 3 个阶段计划；CHANGELOG 本段做全局可见性标注
+ [已完成 Phase 1] ProviderMeta 元信息模型 + 注册表（chatgpt 默认/grok 占位）；账号入库自动附加 provider 字段；调度层 provider 过滤参数透传；GET /api/providers 端点；单元测试 35 全绿
+ [待实现 Phase 2-4] 调度分池（各 provider 独立调度池）、路由分发（按模型/请求类型自动路由到对应 provider）、前端切换器（账号列表/设置页/图片工作台支持切换）——上述三项均未实现，项目处于地基阶段，不改变现有调度行为

**失败分类中枢收尾（双源熔断合一）：**
+ [文本链路收敛] `image_failure.classify_image_exception` 兼容 str 入参，`conversation.stream_text_deltas` 与 `openai_search` 的熔断判定统一走 `classify_image_exception` + `should_record_circuit_failure`，消除 `is_upstream_instability_error` 双源维护
+ [is_upstream_instability_error 保留] 仅存定义（供 image_failure._classify_message_text 复用关键词），全仓无调用点残留

**结构日志字段过滤：**
+ [/api/logs] 新增 `event=`/`request_id=`/`result=` 可选过滤参数，匹配 `detail.event`/`request_id`/`detail.result`；`log_service.list` 加对应过滤谓词；向后兼容

**Prometheus 指标扩展：**
+ [熔断状态机] `chatgpt2api_circuit_breaker_transitions{from,to}` 在 _trip/state/record_success 三处埋点
+ [调度选取] `chatgpt2api_scheduler_pick_total{tier}` 在 _acquire_next_candidate_token 埋点
+ [寿命预测] `chatgpt2api_lifetime_risk{risk}` 在 dashboard 看板端点埋点

**健康端点：**
+ [存活探针] `GET /api/system/healthz`（无鉴权，200 空 JSON，供 docker healthcheck）
+ [就绪探针] `GET /api/system/health/ready`（存储可写自检，不可用 503 + 原因）

## 2.9.2 - 2026-08-08 (图片透传上游直链 + 累计用量统计 + verify_account 核验挂钩 + 前端沉淀)

**图片透传上游直链（省上下行流量）：**
+ [开关] `config.json` 新增 `image_passthrough_enabled`（默认 True）/ `image_passthrough_ttl_secs`（默认 3600），设置页新增「图片透传上游直链」开关实时生效
+ [后端] `services/protocol/conversation.py` 新增 `build_passthrough_items`/`_image_items_from_urls`/`_passthrough_items_to_data`；三处生图下载点按开关分流
+ [后端] `services/image_task_service.py` resume-poll 续轮询同步接入透传（评审发现遗漏）
+ [容错] `config.py._save` 单文件挂载场景原子写失败时回退直接写（解决 docker compose 500）

**累计用量统计：**
+ [端点] `GET /api/dashboard/usage-totals`：累计请求数/成功/失败/图片生成数，基于 usage_agg 缓存（不触发全量日志扫描）
+ [修复] 端点 500：`usage_agg` 在 `api/dashboard.py` 中改为局部 import 避免循环引用 NameError

**异常链路核验挂钩：**
+ [verify_account] `account_service.verify_account` 在文本链路（`conversation.stream_text_deltas`）、搜索（`openai_search`）、图片链路异常时触发账号核验，主动剔除失效账号，避免死账号反复被调度

**存储可写检查修复：**
+ [health/ready] `GET /api/system/health/ready` 改用 `DATA_DIR` 做存储可写检查，兼容 `config.path` 不可写场景（如只读挂载）

**前端沉淀：**
+ [kookeey IP画像] 设置页 kookeey 标签页 IP 使用排行表已实现
+ [暗色主题] 修正暗色主题下的配色一致性

## 2.9.1 - 2026-08-08 (kookeey 流量看板 + 单IP画像 + 出口IP探测 + 失败分类接入)

**kookeey 集成（流量/账号可视）：**
+ [官方开发者 API] `kookeey_service` 实现 HMAC-SHA1+base64 签名调用（与文档示例逐字对齐，单测锁定）；实测修正 API 主机为 `www.kkoip.com`（文档写的 `kookeey.com` 是营销站前端，返回 HTML 404）；海外服务器直连被墙 → 走 kookeey 住宅代理出口访问 API
+ [流量总览] `GET /api/kookeey/traffic`：剩余/今日/近30天流量（/tinfo）+ 动态住宅包余额（/package）
+ [账户/明细] `GET /api/kookeey/balance`（/info）+ `GET /api/kookeey/traffic-detail`（/tdetail 按天/小时）
+ [单IP画像] 按账号粘性 session 记录请求数/失败/最近出口 IP，`GET /api/kookeey/ip-usage` 返回排行榜 + 已使用/已取出 IP 数
+ [出口IP探测] `POST /api/kookeey/probe-ips` 手动批量探测 + 定时 watcher（默认 2h 一轮，`KOOKEEY_IP_PROBE_INTERVAL_SEC` 可调）自动回填各号出口 IP；账号编辑弹窗加「出口 IP」按钮单号即查
+ [前端] 设置页新增「kookeey」标签：开发者 token/access_id 设置 + 4 张流量卡片 + 每账号/IP 使用排行表

**额度明细：**
+ [逐账号额度] `GET /api/dashboard/quota`：号池总额度 + 每号 quota/restore_at + 临近刷新（24h内）列表（`usage_forecast.per_account_quota`）

**生图失败分类（N6b）：**
+ [统一分类] `services/image_failure.py` 新增 `classify_image_exception`：自定义异常/HTTP错误/字符串 → 失败码；conversation 单张生图重试耗尽点接入，熔断判定从散写字符串匹配切换到 `should_record_circuit_failure` 单一事实来源（业务拒绝/账号态不记抖动熔断，上游抖动才记），`ImageGenerationError` 携带分类后 status_code/error_type/code
+ [文本识别] 关键词精确对齐 conversation 白名单（curl 28/35、TLS、5xx、连接重置），避免宽松匹配致熔断漂移

## 2.9.0 - 2026-08-07 (号池救活 + 生图稳定性 + 功能裁剪 + 版本对齐与前端智能重建)

**说明：** `VERSION` 此前停留在 2.8.0（落后于已发版的 2.8.1/2.8.2/2.8.3），本版本将其对齐到 2.9.0，并修复前端"版本号停滞"的根因——启动脚本不再只看 `web_dist` 是否存在，而是按内容指纹决定是否重建。

**号池救活（生产 71+ 异常账号，均为 passwordless 注册无 OpenAI 密码，须走邮箱 OTP）：**
+ [OTP 降级] `account_service` watcher 重登 + 导入两处加 OTP 降级：`_login_with_password` 返回 `need_verification_code`/`password_verify_failed_401`/`password_verify_failed_400` 且有 `mail_credential` 时改走邮箱验证码登录；`mail_credential`（client_id+refresh_token）成功/待登录均入库，供重登用
+ [passwordless 发码] `otp_login_service._trigger_passwordless_otp`：authorize 后停在密码页的 passwordless 账号，显式 POST `passwordless/send-otp` 触发 OpenAI 发码（此前不触发就干等取不到码）
+ [取件时间修复] `_mail_time` 统一 UTC aware：此前 naive/aware 比较抛 TypeError 被静默吞掉 → 永远取不到验证码（关键 bug）
+ [微软 Graph 取件] `_fetch_otp_code` 改**自建微软 Graph 直连优先**（`login.microsoftonline.com` 用 refresh_token 换 token → `graph.microsoft.com/v1.0/me/messages` 读收件箱，国内可直连、凭证不出本机、免第三方限流），token 换不出才回退 98faka；抽出共享 `_extract_otp_code` 文本提码核心；Graph 读到箱但无码不双轮询
+ [每号住宅 IP] `proxy_service.kookeey_proxy_for(email)`：kookeey 动态住宅代理，md5(email)[:8] 粘性 session → 同号固定 IP、不同号不同 IP，降低同 IP 批量登录被风控概率；`config.get_kookeey_settings` 读取配置
+ [批量救号脚本] `scripts/revive_abnormal.py`：一次性对异常账号跑 OTP 登录换新 token + 回写凭证（`--limit`/`--email`/`--offset`/`--proxy` 可选），数据来自 `data/_recover_payload.json`（74 条）
+ [多提供商地基] `services/providers/`（ProviderMeta + 注册表，chatgpt 默认/grok 占位未启用）：账号 normalize 加 `provider` 字段默认 chatgpt，不改变现有行为，为后续接 grok 等预留

**生图链路（P2）：**
+ [文生图] `_classify_failure_phase` 从错误信息识别 9 类失败阶段（无可用账号/熔断器 OPEN/CF 拦截/token 失效/上游限流等）拼进日志简述，失败可定位到阶段
+ [图生图] 新增 `test/test_v1_images_edits_live.py` 真实 E2E（multipart + URL 两种方式，断言 b64_json 可解码为合法 PNG）；用现有号池真实跑通图生图（约 1分52秒，验证 download_image_bytes headers 修复有效）
+ [缩略图] `ensure_thumbnail` 源图不存在/损坏时返回 404 而非 422（语义准确）；前端 img onerror 原图也失败时显示占位框，不再反复请求

**功能裁剪（P3）：**
+ [后端] `/v1/search` `/v1/ppt/generations` `/v1/psd/generations` 返回 404（保留 service 文件只删路由，不破坏生图链路）
+ [前端] debug 页裁掉 搜索Skills/搜索/PPT生成/PSD生成 4 个 tab，只留对话面板（chat completions/responses 是生图底层依赖）

**号池（用户三项要求）：**
+ [自动恢复] 账号自动恢复间隔从 30 分钟改为 5 分钟
+ [额度守卫] `list_abnormal_tokens_for_recover` 排除 last_refresh_error 含 quota_exhausted/rate_limit_exhausted/usage_limit_reached/plan_limit_reached 的账号（上游明确告知额度用完不可恢复）；watcher 主循环跳过 quota=0 且 restore_at 未到期的限流账号（避免反复刷上游浪费额度）

**部署：**
+ [启动脚本] `启动chatgpt2api.bat` 前端构建改为**按指纹智能重建**：新增 `scripts/web_stamp.ps1` 对 `web/src`、`web/public`、web 根配置、`VERSION`、`CHANGELOG.md` 计算哈希，与 `web_dist/.build-stamp` 不一致才重新 build，无变化则跳过——保证 UI 始终是新版本，又不在无变化时拖慢启动。此前仅靠 `web_dist\index.html` 是否存在判断，改代码后不重建导致 UI 版本号停滞在旧版。

## 2.8.1 - 2026-08-05 (账号密码导入：自动登录抓 Token + 失败保留待登录凭据)

**用户场景：** 后续导入以"邮箱----密码"凭据为主，不一定能拿到 Token。

+ [后端] `services/account_service.py` 新增 `add_password_accounts(credentials)`：逐条调既有 `_login_with_password` 自动登录抓 Token；成功 → 正常入库（token 作 key，保留 email/password/source_type=password）；失败（OTP/风控/网络/密码错）→ 以 `pending:{email}` 占位入库（status=待登录，quota=0，保留 email/password 与 login_error），可用 `re_login_accounts` 重试。新增 `_PENDING_PREFIX` 常量；`list_tokens` 过滤 pending 前缀避免误刷/误调度；`_find_account_by_email` 按 email 去重（含 pending）
+ [后端] `api/accounts.py` `create_accounts` 分流：`accounts` payload 中无 access_token 的纯 email+password 项走 `add_password_accounts`，有 access_token 的仍走原 `add_account_items`；混合输入分别处理；纯凭据导入不再因 `tokens` 为空而 400。返回新增 `pending`/`failed` 统计与 errors（每条含 email/error/detail）
+ [前端] `web/src/app/accounts/components/account-import-dialog.tsx` 导入对话框新增「账号密码导入（自动登录抓 Token）」方式：每行 `邮箱----密码` 解析（`splitCredentials`），支持粘贴与 TXT 文件读取；菜单首位 MethodCard；标题/描述/提交按钮齐全
+ [前端] `web/src/lib/api.ts` `AccountImportPayload.access_token` 放宽为可选（纯凭据导入无 token）
+ [测试] 新增 `test/test_account_password_import.py` **12 用例**：分流（纯凭据/带 token/混合/纯凭据不强制 token）、add_password_accounts 成功路径、失败路径（pending 占位+login_error+保留凭据）、登录异常路径、缺字段跳过、重复 email 跳过、既有 email 跳过、list_tokens 过滤 pending、pending 账号可被 re_login_accounts 锁定重试
+ [E2E] `scripts/e2e_smoke.cjs` 新增「账号密码导入」断言链：打开导入对话框 → 选账号密码方式 → 粘贴 `邮箱----密码` → 提交 → 断言 POST /api/accounts body 含 email+password+source_type=password；**10/10 PASS**
+ [真实验收] 用用户真实 `账号密码.txt` 验证：池中已有 email 命中 skipped（去重正确）；池中无的账号 `cjbwfowtfoojv@outlook.com` 真实触发 `_login_with_password` → 密码验证失败返回 `password_verify_failed_401` → pending 占位入库（凭据保留，可 re-login 重试）

**质量：** 全量 **410 passed**（+12 新用例）；ruff 0 错误；tsc 0 错误 + build 成功；五道防线全 PASS；E2E 10/10 PASS

**E2E 实测报告：** `reports/v2.8.1-password-import-e2e-report.md`（真实 txt 100 条导入 + 文生图/图生图/文本 API + 负载均衡 + 延迟，完整数据可复现）

**复用既有能力：** `_login_with_password`（OpenAI OAuth 密码登录，含 sentinel）、`re_login_accounts`（密码重登流程）、`_add_account_payloads`（入库）——无新增上游调用路径

## 2.8.0 - 2026-08-05 (3.2 审计日志：管理操作留痕闭环)

**安全纵深（计划书 3.2）：**
+ [审计服务] 新增 `services/audit_service.py`：管理操作统一留痕，独立文件 `audit-YYYY-MM-DD.jsonl`（不复用业务日志文件，防 /api/logs 删除/裁剪误伤审计）；按天轮转 + 原子写（RLock 防并发丢行）+ 过期天文件整删；operator 末 8 位脱敏；字段含 ts/action/result/operator/ip/request_id/method
+ [统一埋点] `api/support.py require_admin` 统一拦截：失败（401/403）总是记录，成功记录写操作与非轮询 GET；**降噪**——`/api/dashboard/*`、`/metrics`、`/health` 的轮询 GET 成功跳过（防 SSE 每 3s 推送刷爆审计）；中间件（api/app.py）注入 path/method/ip 到 `services/request_context.py` contextvar，require_admin 无需改 90 处端点签名即可读取；**login 端点补审计**（成功 success / 失败 unauthorized 均留痕，越权/错误密钥尝试可追溯）
+ [读取端点] 新增 `GET /api/audit`（require_admin，支持 days/limit/result/operator 过滤），前端 logs 页新增「审计日志」tab（AuditSection 组件：时间/方法/操作/结果/操作者/IP/请求ID）
+ [指标] `chatgpt2api_audit_actions_total{action,result}` 每次 record 递增
+ [契约] SNAPSHOT_ENDPOINTS 加 `/api/audit?limit=1` + DYNAMIC_KEY 豁免；契约守卫断链=0 漂移=0
+ [部署] `web_dist` 同步最新构建（bat 仅在 web_dist 缺失时构建，改前端后必须 `rm -rf web_dist && cp -r web/out web_dist`，否则生产用旧前端）

**质量：**
- 新增 `test/test_audit_service.py` 20 用例（字段完整/operator 脱敏边界/跨天倒序/days 只读最近 N 天 mock 文件系统/result+operator 过滤/limit 跨天/过期整删/当天超限裁剪/并发 8 线程×50 不丢行/真实 TestClient 成功+401+403 埋点/login 成功+失败留痕/dashboard 轮询降噪/审计失败不阻断请求/metrics +1/API 契约字段）
- E2E 冒烟新增审计 tab 断言（点击「审计日志」→ /api/audit 请求 + 表格渲染），9/9 PASS
- 全量 **399 passed / 0 failed**（396 基线 + 登录审计与裁剪 2 用例 + method 断言）；五道防线全 PASS；前端 tsc 0 错误 + build 成功

**独立六维审查修复（Request Changes → 复验 Approve）：**
+ [R1] 指标 label 基数膨胀：`record_audit_action` 归一化动态路径段（UUID/长数字 → {id}），防 /api/accounts/refresh/progress/{id} 等无限 label 组合
+ [R2] method 字段恒空：`record_admin_access` 从 request_context 提取 method，前端「方法」列真实展示
+ [R3] 多 worker append+replace 竞态丢数据：append 热路径永不覆写，清理改由读取端 `maybe_cleanup()`（60s 节流）+ 启动时触发
+ [R4] 测试污染 data/：metrics 用例重定向 audit_service.path 到 tmp
+ [R5] 成功埋点语义：workflow_status 边界声明「成功=鉴权通过，非操作成功」
+ [S3] 移除 /health 降噪死代码；[S5] 前端审计视图加结果筛选；[S6] lifespan 启动补审计清理

## 2.7.1 - 2026-08-05 (5.4 Redis 限流实测 + 6.5 移动端适配)

**5.4 Redis 精确限流部署实测：**
+ [实测] 2 worker + Redis + `rate_limit_rpm=5`：前 5 请求放行、第 6 起 429（跨进程精确限流生效，此前仅单元验证未部署实测）
+ [修复] **Redis 运行中断连 → 限流不 500 不崩**：`api/rate_limit.py` `_check_shared` 捕获 redis 异常回退本进程本地滑窗（`_check_local`）+ 打日志；此前 `get_shared_state` 单例缓存 RedisBackend 后断连 `incr` 抛异常致 500
+ [依赖] pyproject.toml 加 `redis>=5.0.0` + uv.lock；README「多 Worker 精确限流一键化」补实测结论与断连降级取舍

**6.5 移动端适配：**
+ dashboard 排行榜表格外包 `overflow-x-auto`（窄屏横向滚动）；top-nav 已有汉堡菜单，logs/accounts 已有横向滚动
+ 6.4 图片画廊懒加载确认既有（image-results.tsx IntersectionObserver + 骨架占位），游标分页不必要

**质量：**
- test_shared_state.py 新增 2 降级用例（redis 首次失败降级 / 运行中断连降级）；全量 **379 passed / 0 failed**
- 五道防线全 PASS；tsc 0 + build 成功；ruff 干净

## 2.7.0 - 2026-08-05 (v3.1 账号寿命预测/容量报表/告警恢复 + v3.2 前端体验)

**产品功能增强（5.1/5.2/5.3）：**
+ [5.1 账号寿命预测] `services/account_lifetime.py`：EWMA 失败率 + 连续失效窗口双信号，输出 risk（low/medium/high/critical）+ 预估剩余天数（有限配额按消耗速率外推）；`_account_health_tier` 降档接入（濒危→risky、高→warm，只降不升 + 最小观测窗口防抖动）；调度排名/账号列表附加 `lifetime_risk`/`lifetime_eta_days`；dashboard 濒危账号预警卡片 + 排行榜「寿命」列 + accounts 页寿命徽章
+ [5.2 容量规划] `GET /api/dashboard/capacity?days=`：基于 usage_agg 聚合缓存的日均请求/活跃账号/单账号日均消耗/增长率/外推需新号数；mock 断言不触发 log_service.list（慢查询守卫）；空数据/单账号/零增长不除零
+ [5.3 告警恢复] 新增 `circuit_breaker_closed`（熔断半开成功恢复触发）+ `account_recovered`（账号从失效态刷新成功清零触发）事件，复用告警通道 + 去重窗口；`alert_events` 默认含新事件；设置页告警事件多选补 4 项

**前端体验升级（6.1/6.2/6.3）：**
+ [6.1 异步按钮] `web/src/components/ui/async-button.tsx`：`isLoading` 禁用 + spinner + 成功后清态；dashboard 刷新按钮接入；e2e 新增 2 项交互反馈断言（点击后 loading 态 + 禁用）
+ [6.2 骨架屏] `web/src/components/ui/skeleton.tsx`（Skeleton/SkeletonTable/SkeletonCards）；dashboard 与 image-manager 加载态改统一骨架（消 CLS）
+ [6.3 账号列表分页] `/api/accounts?page=&page_size=` 服务端分页（可选，默认全量向后兼容），响应含 `total`；前端 `AccountListResponse` 加 total 字段

**质量：**
- 新增 test_account_lifetime.py（17 例）/test_capacity_report.py（5 例）/test_recovery_alerts.py（3 例）/test_accounts_pagination.py（5 例）；全量 **377 passed / 0 failed**
- 五道防线全 PASS（契约断链=0 漂移=0 / SQL 0 / 慢查询 2 处 / 变异 caught=6 escaped=0 / 施压 8/8）
- 前端 tsc 0 错误 + build 成功；E2E 冒烟 **7/7 PASS**（含新增交互反馈断言）
- 边界声明：账号寿命预测为趋势信号（非精确到期），无限配额账号 eta_days 按风险档位给保守上限；6.3 虚拟滚动未引入（账号 <1k 时前端分页已满足，YAGNI）

## 2.6.0 - 2026-08-05 (4.1 日志按天轮转切分：慢查询根治落地)

**性能根治（计划书 4.1）：**
+ [日志切分] `services/log_service.py` 改为按天轮转切分：写入 `logs-YYYY-MM-DD.jsonl`（不再写单一日志文件），`list()` 支持 `days=N` 只读最近 N 天天文件（limit 凑够 early-exit，不触碰更早文件），`start_date` 更早时自动扩展文件范围（不丢历史）；`delete()` 跨天文件删除；`_auto_cleanup()` 两级——过期天文件整删（文件级）+ 当天文件超限裁剪（条目级）
+ [旧数据迁移] 旧 `logs.jsonl` 首次访问时惰性迁移到天文件并 rename 为 `logs.jsonl.legacy`（幂等、线程安全、失败不崩）；app lifespan 启动即触发迁移，确保 usage_agg watcher 读切分后日志
+ [用量聚合适配] `services/usage_agg.py` 改为多文件增量：日志路径传 `DATA_DIR` 目录扫描 `logs-*.jsonl`，每文件独立 offset 增量读，新天文件出现只增量、某文件被裁剪才全量重建；升级检测（旧缓存无 `file_offsets` 且按天模式）自动清空重建防重复计数
+ [API] `/api/logs` 新增可选 `days` 参数透传；前端 `fetchSystemLogs` 支持 `days`，日志页默认近 7 天（days=7），用户选日期范围时用 start_date/end_date 精确过滤
+ [慢查询报告] `scripts/slow_query_report.py` 移除「日志列表全量读/日志删除整文件重写/日志惰性清理整文件重写」三个热点（已根治）；优化建议标注 4.1 已落地
+ [测试] 新增 `test/test_log_rotation.py` 11 用例（按天写入/list 跨天倒序/days 只读最近 N 天 mock 文件系统/start_date 扩展/过期天文件整删/当天超限裁剪/跨天删除/旧文件迁移无丢失无重复/limit 跨文件全局）；全量 347 passed / 0 failed

## 2.5.0 - 2026-08-05 (3.1.2 账号批量操作 + 3.1.3 图片工作台增强)

**新功能（计划书 3.1.2/3.1.3）：**
+ [批量操作] `POST /api/accounts/batch`：表驱动分发 `evict_stale`（按选中 ids 驱逐失效 token）/ `label`（批量打标签，账号新增 `label` 字段，JSON/SQLite JSON 列自动持久化，无 schema 迁移）/ `export`（复用 build_export_items）；accounts 页工具栏 3 按钮（批量驱逐失效/批量打标签/导出选中）+ 标签输入 Dialog + 列表标签徽章
+ [图片工作台] 固定种子（`-1` 随机 / 非负固定，seed 全链路透传至上游 payload `tools[0].seed`，实验性 best-effort）+ 负向提示（上游无原生字段，best-effort 拼入 prompt 语义降级）+ 宽高比预设（既有 SIZE_PRESETS 保留）
+ [契约] `/api/accounts/batch` 新端点 + image-tasks `seed` 参数；快照 --update（断链=0 漂移=0）
+ [测试] `test_accounts_batch.py` 8 用例 + `test_generations_seed.py` 5 用例（live 1 条默认跳过）；全量 337 passed / 0 failed

## 2.4.1 - 2026-08-05 (E2E 冒烟验收工具固化)

**工程效能（无功能变更）：**
+ [E2E] 新增 `scripts/e2e_smoke.cjs` 浏览器冒烟验收（playwright-core + 系统 Edge，免下载浏览器）：登录 → /logs 账号筛选 → /accounts 单账号时间线 → /dashboard 档位筛选，5 项断言；`web` 引入 playwright-core devDep + SKILL.md 记录用法
+ [验收] 真实服务 E2E 已跑通并留证据：后端 TestClient 全 ASGI 栈 7/7（缺参/精确过滤/模糊匹配/聚合 usage/forecast/落盘/401）、浏览器 E2E 6/6、冒烟脚本 5/5；E2E 测试数据已清理，production data/ 无残留

## 2.4.0 - 2026-08-05 (下一步改进指南首批落地：慢查询根治 / 账号洞察 / 编码容错 / 看板可见性 / Redis 一键)

**v3.0 路线第 1 批（P1/P2 落地，向后兼容）：**
+ [慢查询根治] `services/usage_agg.py` 日志聚合缓存（按小时桶增量聚合 + 90 天窗口 + 原子落盘）：`/api/dashboard/usage` 与 `usage_forecast` 改读缓存，不再每次全量扫 logs.jsonl（慢查询报告热点已移除）；启动后台聚合线程每 60s 增量 ingest；mock 断言 usage 端点不再调 log_service.list
+ [账号洞察] `/api/logs` 新增 `account_email` 查询参数（模糊匹配，含过滤+分页+缺参兼容）；日志页加账号筛选输入框；账号页行操作加「单账号时间线」抽屉（拉该账号调用日志）
+ [编码容错] `utils/log.py` 新增 `_SafeStreamHandler`：Windows 中文日志经 GBK 管道偶发 UnicodeEncodeError 时 errors='replace' 兜底重写，不再崩溃（变异探针「还原后全量测试」偶发失败根因修复）
+ [看板可见性] 调度排行榜加档位筛选（全部/风险+温存/仅风险），筛选时显示该档位全部账号，风险档不被 slice(0,10) 截断在榜单外
+ [Redis 一键] `scripts/init_redis_state.py` 幂等接线多 worker 精确限流（校验连通性→写入 config.json）；`docker-compose.local.yml` 补 redis 服务样例；README/onboarding 补「多 Worker 精确限流一键化」段；顺带修复 README 限流版本号漂移（v2.3.1→v2.3.0）
+ [慢查询报告] `scripts/slow_query_report.py` 热点清单移除「用量统计全量读」（已由聚合缓存根治），docstring 注明
+ [测试] 新增 `test_usage_agg.py`（7 用例：增量不丢不重/磁盘恢复/窗口裁剪/与全量扫描口径等价/mock 断言不触发全量扫描）、`test_logs_account_filter.py`（5 用例）、`test_log_encoding.py`（3 用例）；全量 323 passed / 0 failed

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
