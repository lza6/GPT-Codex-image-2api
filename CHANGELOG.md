# Changelog

## 2.9.2 - 2026-08-08 (图片透传上游直链 + UI 实时开关)

**图片透传（省上下行流量）：**
+ [开关] `config.json` 新增 `image_passthrough_enabled`（默认 True）/ `image_passthrough_ttl_secs`（默认 3600），设置页新增「图片透传上游直链」开关实时生效
+ [后端] `services/protocol/conversation.py` 新增 `build_passthrough_items`/`_image_items_from_urls`/`_passthrough_items_to_data`；三处生图下载点（生图主链路、resume-poll 续轮询、模型文本回复兜底）按开关分流
+ [后端] `services/image_task_service.py` resume-poll 续轮询同步接入透传（评审发现遗漏）
+ [容错] `config.py._save` 单文件挂载场景原子写失败时回退直接写（解决 docker compose `- ./config.json:/app/config.json` 目录不可写导致 500）
+ [测试] `test_image_passthrough.py`（6 条：开/关两分支、空 URL、expires_at）+ `test_resume_poll_token.py` 透传分支 + `test_v1_images_edits_live.py` 兼容透传断言
+ [前端] settings store + config-card 新增透传开关，实时生效

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
