# ChatGPT2API 领域语言（Ubiquitous Language）

> 状态：**current**（现行真相源之一）
> 版本：v1.0（2026-08-08，第十八轮对标上游 v3.0 CONTEXT.md 后适配主项目 v2.x 落地）
> 真相源优先级（与 `docs/README` 一致）：**当前代码 + 测试 + 公开契约 > 本文件（领域术语与所有权）> `docs/adr/index.md` > 其余 current 文档**。
> 规则：文档与实现不一致时以代码/契约为准并当场修订本文件；新增/下线概念须同步本文件。
> 目的：统一「业务语义」的单一事实来源，收敛主项目历史上反复出现的**假接口 / 文档漂移 / 术语歧义**（见 SKILL.md 历史 bug 警示）。
> 说明：主项目为「企业内部自用、画图为主」的自托管工具，性能优先、安全由调用方处理；本文件只描述主项目**当前真实**语义，不引入上游 v3.0 中主项目没有的概念（如 GenBox、Application Database、Vue 控制台）。

---

## 一、访问与账号（Access & Accounts）

**上游账号（Upstream Account）**
可被调度选中、用于执行一次上游请求的 ChatGPT 凭据实体。池内以 `access_token` 为主要标识，附 `email`/`refresh_token`/`account_id`（management_id）等。
_避免_: 用户、登录账号、User Key。

**上游凭据（Upstream Credentials）**
上游账号的 `access_token`（必需）+ 可选 `refresh_token` / `id_token`。后端把 access_token 状态投影为 `valid` / `expiring` / `invalid`；refresh_token 状态为 `valid` / `missing` / `invalid`——**只有明确的终态刷新失败（TerminalRefreshTokenError）才把现存 refresh_token 判为 invalid**。
_避免_: 前端自推的 token 状态、把"待登录"当"失效"。

**待登录账号（Pending Account）**
凭「邮箱+密码」导入但尚未成功抓到 token 的占位账号，token 以 `_PENDING_PREFIX`（`pending:{email}`）标记，status=待登录、quota=0、保留 email/password/login_error 供 re-login。`list_tokens` 须过滤 pending，不参与调度。
_来源_：第十六轮账号密码导入。

**账号池（Account Pool）**
当前模型/状态/配额/计划类型/来源类型/代理策略过滤下，可被选取的上游账号集合。
_避免_: 用户池。

**用户密钥（User Key）**
标识调用方并授予控制台能力的本地 bearer 凭据（auth-key / 多 key）。**与上游账号的 access_token 是两个不同概念**，严禁混用。
_避免_: 上游账号、access token。

**能力（Capability）**
控制台权限，当前由 `require_identity()` / `require_admin()` 两级体现（identity=登录调用方，admin=管理面）。dashboard 等管理端点须 `require_admin`。

**号池救活 / OTP 登录（主项目独有）**
对失效/passwordless 账号走 `services/otp_login_service.py`：微软 Graph 直连优先取件、98faka 兜底；`_mail_time` 统一 UTC aware（否则取件时间比较被静默吞→永远取不到码）。`mail_credential` 入库的账号才可被 watcher 自动救活；71 个遗留异常号无凭证，只能 `scripts/revive_abnormal.py` + 外部 payload 一次性救。

**每号住宅 IP（主项目独有）**
`services/proxy_service.py kookeey_proxy_for(email)`：md5[:8] 粘性 session → 同号固定住宅 IP，凭据 URL 编码；配置经 `config.get_kookeey_settings`。

---

## 二、图片执行（Image Execution）

**图片任务（Image Task）**
一次异步的文生图/图生图请求，归属某个 User Key，终态产出一个或多个图片资产。持久化字段**读写对称**（白名单恢复不得丢 `conversation_id`/`account_email`，否则重启后 resume_poll 失效）。
_避免_: 对话、调用日志。

**图片尝试（Image Attempt）**
一次图片调用内、用某个上游账号做的一次尝试，含其结果、诊断、是否又切换了账号。一次图片任务可含多次尝试。
_避免_: 图片任务、重试日志。

**账号切换（Account Switch）**
从一次失败的图片尝试切到另一账号的新尝试。它**不是终态结果**——任务成功才算成功。
_关键不变量_：熔断 `record_success` **必须在 `_is_image_account_available` 确认之后调用**（历史 bug：返回后立即调导致误判）；换号取号调用须 try/except 转 `RuntimeError("no available ... account")`。

**图片文本结果（Image Text Result）**
上游返回审核/解释性文本而非图片的终态结果（`text_review` 等结构化失败码）。**属业务拒绝，不是上游抖动**，严禁计入熔断 `record_failure`。
_避免_: 当作普通失败/普通对话。

**可编辑文件任务（Editable File Task）**
归属某 User Key 的异步 PPT/PSD 生成请求，终态产出主可编辑文件 + ZIP 包。按 API Key 隔离创建/查询/删除。

**图片资产（Image Asset）**
生成/编辑得到的图片，经 URL 或 base64 暴露，可被画廊索引。下载须带 web cookies（cf_clearance/_cfuvid/oai-sc）+ Bearer，否则被 CF 层 404（历史根因）。

---

## 三、可观测与路由（Observability & Routing）

**调用日志（Call Log）**
一次公开接口调用的持久化记录，含结果、耗时、诊断、图片尝试。写 `logs-YYYY-MM-DD.jsonl`（按天轮转），时间键兼容 `time`/`ts`/`created_at`，成败读 `detail.status`（顶层无 status 键）。用量/预测**只读 `services/usage_agg.py` 聚合缓存**（按小时桶增量），禁止全量扫日志。

**审计日志（Audit Event）**
管理面操作留痕（`require_admin` 统一埋点 + login），写 `audit-YYYY-MM-DD.jsonl`，operator 末 8 位脱敏。401/403 必记、写操作与非轮询 GET 成功记；dashboard/metrics/health 轮询 GET 成功**降噪不记**（防 SSE 每 3s 刷爆）。

**实时监控（Active Request）**
仅在请求存活窗口存在的内存态，经 dashboard SSE 推送。EventSource 无法传 header 用 `?token=` 鉴权；`event_generator` 必须 `try/except asyncio.CancelledError` 处理客户端断开。

**熔断器（Circuit Breaker）**
按 token 管理的上游熔断状态机 CLOSED→OPEN→HALF_OPEN→CLOSED（连续失败 5 次熔断、30s 冷却、半开 3 次成功恢复）。`record_failure` 判定**必须用正向白名单 `is_upstream_instability_error`**（5xx/超时/TLS/连接），**禁止 `not is_token_invalid_error` 反向白名单**——否则业务拒绝（moderation 400/prompt 违规）被误记，恶意用户可熔断健康账号造成拒绝服务。

**智能调度（Scheduler）**
`services/account_service.py`：健康档位（healthy/warm/risky）+ 调度分（基础分+配额占比+成功加成-失败惩罚-冷却惩罚），选取顺序 优先级>档位>调度分。接入寿命预测（`account_lifetime.py`）**只降不升**（濒危→risky、高→warm，低/中不降）+ 最小观测窗口防抖动。

**代理池（Proxy Pool）**
`services/proxy_pool.py`，持久化 `data/proxies.json`，轮询/加权/最少连接三调度 + 健康检查自动隔离恢复。与「每号住宅 IP」「代理运行时配置」分层。

**SSRF 防护**
图片 URL 抓取走 `services/ssrf_guard.py`（协议白名单 + 内网 IP 段校验），`CHATGPT2API_SSRF_ALLOW_PRIVATE_IPS` 可回退（默认拒绝内网）。

---

## 四、共享目录与持久化（Catalogues & Persistence）

**模型目录（Model Catalog）**
后端投影的受支持文本/图片模型、默认值与能力，供前端各页面共享（非页面私有模型清单）。

**存储后端（Storage Backend）**
`config.storage_backend_type`（默认 `json`）可切 json/sqlite/postgres/git，经 `services/storage/factory.create_storage_backend` 单例。**主项目坚持四后端可切换**——Git 后端是本地发版/备份载体（ADR-009），JSON 是极简部署入口。

**多 Worker 约束**
JSON 后端 `workers>1` 自动回退 1 并警告（多进程各持独立账号副本=数据损坏）；SQLite/Postgres 才允许多 Worker。多进程共享状态**只走存储层**，禁止模块级可变全局变量跨请求持有；多 worker 精确限流需 Redis（`shared_state`，断连降级本地滑窗不 500）。

**多提供商（Provider，主项目地基）**
`services/providers/`（ProviderMeta+注册表，chatgpt 默认 / grok 占位未启用）；account normalize 加 `provider` 字段默认 chatgpt，**当前不改调度行为**（调度分池/路由/前端切换器为后续阶段）。

**配置（Config）**
`config.json` + `services/config.py`：启动 schema 校验 + 环境变量 `CHATGPT2API_*` 覆盖。新增配置项走 6 步（config.json 默认值 + property + get + schema 校验 + api.ts + store/config-card）。

---

## 五、易混点澄清（Flagged Ambiguities）

- **"account"** 既曾被当作上游账号也当作本地调用方凭据 → 本地调用方用 **用户密钥（User Key）**，上游用 **上游账号（Upstream Account）**。
- **"access token"** 可指上游 ChatGPT token 或登录态 bearer → 前者归上游账号凭据，后者归 User Key。
- **"text"** UI 上可指普通对话或 `text_review` → 后者用 **图片文本结果（Image Text Result）**，且绝不计入熔断失败。
- **"失败"** 分两类：业务拒绝（moderation/审核/prompt 违规/文本结果）与上游抖动（5xx/超时/TLS/连接）——只有后者进熔断 `record_failure`，这是多条历史 bug 的根因边界。
- **"多后端"** 指**可切换的四种存储后端**，不是"同时写多份"；运行时单例生效其一。
- **"文档"** 分 current / plan / historical 三态；current 只描述已验证行为与真实路由。

---

## 六、术语速查（中英文对照）

| 中文 | 英文/代码锚点 |
|------|--------------|
| 上游账号 | Upstream Account（`services/account_service.py`） |
| 用户密钥 | User Key（`api/support.py require_identity/require_admin`） |
| 待登录账号 | Pending Account（`_PENDING_PREFIX`） |
| 图片任务 | Image Task（`services/image_task_service.py`） |
| 图片尝试 | Image Attempt |
| 账号切换 | Account Switch |
| 图片文本结果 | Image Text Result（`text_review`） |
| 可编辑文件任务 | Editable File Task（`services/editable_file_task_service.py`） |
| 调用日志 | Call Log（`services/log_service.py`，logs-*.jsonl） |
| 审计日志 | Audit Event（`services/audit_service.py`，audit-*.jsonl） |
| 熔断器 | Circuit Breaker（`services/circuit_breaker.py`） |
| 智能调度 | Scheduler（`account_service._account_health_tier` 等） |
| 代理池 | Proxy Pool（`services/proxy_pool.py`） |
| 每号住宅 IP | kookeey sticky residential IP（`proxy_service.kookeey_proxy_for`） |
| 号池救活 | OTP 救活（`services/otp_login_service.py`） |
| 存储后端 | Storage Backend（`services/storage/factory.py`） |
| 用量聚合 | Usage Agg（`services/usage_agg.py`） |
| 寿命预测 | Account Lifetime（`services/account_lifetime.py`） |

---

*维护：新增/下线领域概念时同步本文件；与代码冲突时以代码为准并当场修订。*
