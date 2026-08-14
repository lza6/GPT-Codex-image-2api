# ChatGPT2API 工作流状态 — 第二十四轮（v2.36.0 fomimage 提供商接入 + 规模化增强）

> 最后更新：2026-08-14
> 模式：fomimage 提供商接入全链路（模型前缀映射 + 自动注册号池 + 积分用完即弃 + 一号一指纹 + 批量并发 + 多邮箱源 + 统计接线 + 前端管理）
> 基线：v2.36.0

> 上一轮（第二十三轮，v2.34.0）已闭环：Provider Phase 4 + III-01~07 + V-01~04 + VII-01~04，详见历史。

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | fomimage 真实契约探测 | ✅ | 实测 temp-mail 建邮箱（POST /mailbox）、fromimage 注册/OTP/登录/余额 50 全通；HAR 还原 12 模型定价表 + 积分公式 |
| B | 模型前缀映射 | ✅ | registry fomimage 12 模型 + helper split_image_model + router 前缀路由 + /v1/models（owned_by=fomimage）；test_fomimage_pricing 13 用例 |
| C | fomimage 上游客户端 + 协议分派 | ✅ | fomimage_backend_api（上传 CurlMime multipart/建任务/轮询/下载）+ fomimage_image 协议适配 + conversation 按 account.provider 分派；test_fomimage_provider 9 用例 |
| D | 自动注册引擎 | ✅ | temp_mail + engine（密码不规则/每号独立代理/错峰）+ coordinator（批量+自动补号）；API 端点 2 个 |
| E | 积分成本映射 + 用完即弃 | ✅ | fomimage_pricing 完整定价表 + estimate_credits（对齐 HAR）+ mark_image_credits_result 按 costCredits 扣减 + quota 归零自动剔除 |
| F | 前端 | ✅ | 设置页 fomimage 注册管理卡片（批量数量/指纹/IP/邮箱源策略/号池规模）+ 图片工作台全模型展示；tsc 0 + build |
| G | 真实 E2E | ✅ | test_fomimage_live（-m live）注册→收码→上传→图生图→下载→余额 50→40；本地 E2E 注册 2 号不同指纹 + cookies/指纹 调用出图扣分 |
| H | 规模化增强 | ✅ | 一号一指纹（fomimage_fingerprint.py）+ 多邮箱源（mail_source.py temp→luckmail→gptmail）+ register_workers 并发 + API 上限 500 + fomimage 出图日志→usage_agg |
| I | 部署期修复 | ✅ | fetch_remote_info 对 fomimage 跳过 OpenAI 校验（防 watcher 误删）+ 会话 cookie 随账号入库（防生成期 Unauthorized）；服务器真实出图验证 |
| J | 验收 | ✅ | 全量 pytest exit 0 + 本轮改动 ruff 0 + tsc 0 + build 成功 + 契约断链 0 + 文档同步 |

## 本轮防线状态

| 批次 | 契约 | SQL | 慢查询 | 变异 | 施压 | 文档同步 |
|------|------|-----|--------|------|------|----------|
| 第二十四轮 | ✅（新增端点已加 DYNAMIC） | 未触新风险（无 SQL 改动） | 沿用登记表 | 沿用登记表 | 沿用登记表 | ✅（VERSION 2.36.0 与文档同步） |

> 本次改动区域：services/fomimage_* / services/registration/fomimage/ / providers registry / conversation 分派 / api/registration / settings 卡片 / README。
> 未触碰 SQL/存储/调度核心，慢查询/变异/施压沿用 verification-registry 基线；契约守卫已重跑确认无断链。

## 边界声明（诚实）

- **fomimage 出图烧真实积分**：live E2E 消耗一次性账号。生产启用需 `registration.fomimage.enabled=true`。
- **定价为静态快照**：`services/fomimage_pricing.py` 定价表来自 2026-08-13 SSR payload + HAR 实测；运行时上游 `/api/ai/image-models` 可能调整，`estimate_credits` 仅用于前端展示与预检，实际扣分以上游返回 `costCredits` 为准。
- **"几万账号"规模化受限（诚实）**：代码能力已全部就绪（一号一指纹/一号一IP/多邮箱源/并发/批量API），但规模受外部条件硬约束——① temp-mail 域名有限且服务器（数据中心 IP）被 CF 403 → 需 luckmail 付费 key（`registration.fomimage.luckmail.api_key`）；② 一号一IP 依赖 kookeey 住宅 IP（付费按量）或免费代理池（健康 IP 个位数）；③ 注册速率 ~1号/分钟/worker，`register_workers` 并发可提速。**缺 luckmail key + kookeey 启用即"已做到代码层，缺外部条件无法规模实测"**。
- **百万次不重复 IP 调用**：调用 IP = 账号绑定 IP；50分/号 ÷ 10分/张 = 5张/号 → 百万张需 20 万账号 + 20 万独立 IP → 必须 kookeey 按量付费，免费代理不可能。
- **部署期修复已合入**：fetch_remote_info 对 fomimage 跳过 OpenAI 校验 + fomimage 会话 cookie 随账号入库，均经服务器真实出图验证。

> 最后更新：2026-08-12
> 模式：v2.34.0 III-01~07（回收站根因/调度A/B/配额预警/慢查询/连接池/备份校验/告警多通道）+ V-01~04（bundle/缓存/虚拟列表/基准化）+ VII-01~04（覆盖率/防线CI/文档钩子/OpenAPI）+ Provider Phase 4（grok）
> 基线：v2.35.0

> 上一轮（第二十二轮，v2.33.0）已闭环：R2 接线 6 步 + e2e 体系。历史明细见 git history 与 docs/verification-registry.md。

## 补录 v2.18→v2.32 完成矩阵（此前未入档，对照 git log + CHANGELOG.md）

| 版本 | 主题 | 关键内容 | 验证证据 |
|------|------|----------|----------|
| v2.18.0 | 多模型路由 | `model_upstream_map` 映射表 + `_resolve_upstream_model` + `/v1/models` 可见映射模型 | 7 单测；705 全量（第二十轮） |
| v2.19.0 | 连接池四优化 | Session 池健康预检 / 动态冷却期 / 连接 TTL / 指数退避重连 | 7 新增；27 全绿 |
| v2.20.0 | 查询优化闭环 | `auth_key` cached_property + `metrics_sample_rate` 采样 + `_normalize_path` 路径归一化降 cardinality | 12 单测 |
| v2.21.0 | 性能优化（CHANGELOG 未登记段） | 增量刷新 + 倒排索引 + 分页 + 连接池（git log `f6b6b59`） | git log 证据 |
| v2.22.0 | 可观测性+调度增强+账号自愈（CHANGELOG 未登记段） | git log `79cfd78` | git log 证据 |
| v2.23.0 | 批处理闭环（CHANGELOG 未登记段） | log 升级 + prometheus + tracing + api/logs（`ea8a95e`，835 测试）；least_load/predictive/affinity 调度 + self-heal 自愈（`60c916b`） | git log 证据 |
| v2.24.0 | 事件总线 Pub/Sub 增强 + 三级缓存 | EventType 枚举(26) + 异步消费者 + 事件统计 + 4 指标；`session_cache.py` L1 LRU→L2 Redis→L3 存储 | 42+4 单测 |
| v2.25.0 | 智能诊断 + 自动修复 2.0 + 异步存储层 | 7 诊断检查器 + 6 修复器；AsyncStorageBackend + async_database + async_bridge | 24 + 14 单测 |
| v2.26–v2.29 | CHANGELOG 未登记（功能并入 v2.30.0 段） | ConfigWatcher 热加载 + 批量查询优化 + AdaptiveScheduler + 容量规划 + OpenAPI SDK | git log 证据（CHANGELOG 缺口，已记入本矩阵警示） |
| v2.30.0 | 请求级响应缓存 + 容量/成本 + 自适应调度 + 配置热加载 | ResponseCache 预注册 5 端点 + `/api/dashboard/cost` + AdaptiveScheduler + ConfigWatcher + async storage 开关 | 22+10+28+7 单测；913 全量 |
| v2.31.0 | 前端深度体验 + SSE 事件流 + 契约断链清零 | motion/use-interaction-feedback/响应式；`/api/events/stream` + events.jsonl 持久化；accounts tags/detail/export-csv；断链 3→0 | 9+8 单测；tsc+build |
| v2.32.0 | 账号回收站 + 雨露均沾 + 粘性 IP | trash_service + `_pick_least_used` + `proxy_service.get_profile` 常规请求接入 | 11 新增；1161 回归 |
| v2.33.0 | R2 配置接线闭环 + E2E 体系 | 前端 r2/r2_local 模式 + 五字段表单 + 按模式连接测试；R2Client 层测试 16+3；e2e/ 入 git + docs/e2e.md；diagnose .json() 修复 | 29 存储项；tsc+build；防线（本轮） |
| v2.34.0 | 里程碑3/5 + 工程效能 + Phase 4 | III-01~07 全闭环（回收站根因/调度A/B/配额预警/慢查询/连接池/备份校验/告警多通道）+ V-01~04（bundle/缓存/虚拟列表/基准化）+ VII-01~04（覆盖率62%/八道防线/文档钩子/OpenAPI）+ Provider Phase 4（grok 接入 + 三入口切换） | 八道防线 8/8 PASS；覆盖率门禁 62%；变异 caught=33；+38 新增测试文件相关回归全绿 |

> **CHANGELOG 缺口警示**：v2.21/v2.22/v2.23/v2.26–v2.29 在 CHANGELOG.md 无独立版本段（功能部分并入 v2.30.0 段），git log 有对应提交。已在本矩阵如实登记，未擅自补写 CHANGELOG。

## 八道防线状态

| 批次 | 契约 | SQL | 慢查询 | 变异 | 施压 | 文档同步 | 性能基准 | 覆盖率门禁 |
|------|------|-----|--------|------|------|----------|----------|------------|
| 第二十一轮 | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | - | - |
| 第二十二轮 | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | - | - |
| 第二十三轮 | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |
| 第二十四轮 | ✅（见下） | 沿用 | 沿用 | 沿用 | 沿用 | ✅ | 沿用 | 沿用 |

> 第二十四轮（v2.36.0）改动区域为 fomimage 提供商（无 SQL/存储/调度核心改动），契约守卫重跑断链=0，SQL/慢查询/变异/施压沿用 verification-registry 基线；文档同步 VERSION 2.36.0 与 CHANGELOG/workflow_status 对齐。

## 当前 git 状态

- 本轮（v2.36.0）改动：fomimage 提供商接入（services/fomimage_pricing.py、fomimage_backend_api.py、protocol/fomimage_image.py、registration/fomimage/、providers/registry.py、utils/helper.py、router_service.py、conversation.py 分派、account_service mark_image_credits_result、api/registration.py、config.example.json、web 前端 3 文件）
- 新增测试：test_fomimage_pricing / test_fomimage_registration / test_fomimage_provider / test_fomimage_live
- 版本：VERSION=2.36.0，CHANGELOG 已更新

## 边界声明（诚实）

- **fomimage 出图烧真实积分**：live E2E 消耗 1 个一次性账号；生产启用需 registration.fomimage.enabled=true + free_proxy.enabled=true
- **fomimage 定价为静态快照**：以运行时上游 /api/ai/image-models 为准，实际扣分按上游 costCredits
- **fomimage 注册风控**：temp-mail 域名可能被屏蔽，失败自动弃邮箱换新
- **服务器自动注册受限（2026-08-14 部署实测）**：服务器（腾讯云东京）访问 temp-mail 被 CF 403（数据中心 IP 信誉，本机家庭 IP 可注册）、gptmail 428、luckmail 未配 key → 服务器上自动补号需外部条件（配 luckmail key 或可访问 temp-mail 的出站代理）；当前用本地注册的 3 个带 cookie 账号导入服务器号池，出图/扣分/用完即弃全链路已验证
- **部署期修复已合入**：fetch_remote_info 对 fomimage 跳过 OpenAI 校验（防 watcher 误删号池）+ fomimage 会话 cookie 随账号入库（防生成期 Unauthorized），均经服务器真实出图验证
