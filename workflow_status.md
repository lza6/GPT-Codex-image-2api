# ChatGPT2API 工作流状态 — 第十四轮（v3.1 账号寿命预测/容量报表/告警恢复 + v3.2 前端体验）

> 最后更新：2026-08-05
> 模式：v3.1 产品功能增强 + v3.2 前端体验升级 —— 计划书 5.1/5.2/5.3 + 6.1/6.2/6.3
> 基线：f2edc2a（v2.6.0 收尾）

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 5.1 账号寿命预测（EWMA+连续失效窗口双信号） | ✅ | services/account_lifetime.py（compute_lifetime_risk 纯函数 + now 可注入）；_account_health_tier 降档接入（濒危→risky、高→warm，只降不升）；test_account_lifetime.py 17 用例 |
| B | 5.1 看板/账号页展示 | ✅ | /api/dashboard/scheduler 排名加 lifetime_risk/eta_days、/api/accounts 附加 lifetime 字段；dashboard 濒危卡片 + 排行榜寿命列 + accounts 寿命徽章；契约断链=0 |
| C | 5.2 容量规划报表 | ✅ | /api/dashboard/capacity（usage_agg 聚合缓存；mock 断言不调 log_service.list）；test_capacity_report.py 5 用例（空数据/单账号/零增长不除零） |
| D | 5.3 告警降级与恢复 | ✅ | circuit_breaker_closed（半开恢复触发）+ account_recovered（失效清零触发）；alert_events 默认含新事件；设置页多选补 4 项；test_recovery_alerts.py 3 用例（含去重） |
| E | 6.1 全局交互反馈 | ✅ | ui/async-button.tsx（AsyncButton：isLoading 禁用+spinner+成功清态）；dashboard 刷新接入；e2e_smoke.cjs 新增 2 项断言（loading 态+禁用），7/7 PASS |
| F | 6.2 骨架屏 | ✅ | ui/skeleton.tsx（Skeleton/SkeletonTable/SkeletonCards）；dashboard + image-manager 加载态改统一骨架（消 CLS） |
| G | 6.3 账号列表分页 | ✅ | /api/accounts?page=&page_size= 服务端分页（可选向后兼容）+ total；test_accounts_pagination.py 5 用例 |
| H | 验证全绿 | ✅ | pytest 377 passed / 0 failed；五道防线全 PASS；tsc 0 错误 + build 成功；E2E 7/7 |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十四轮 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 契约守卫 /api/accounts 快照字段含 total/lifetime（新增字段不漂移，断链=0）。变异探针 caught=6 escaped=0。

## 当前 git 状态

- 测试：**377 passed / 0 failed**（31 live/redis 排除）
- 前端：tsc 0 错误 + build 成功（dashboard/accounts/image-manager/async-button/skeleton）
- 契约：断链=0 漂移=0
- 版本：**v2.7.0（已发版）**

## 边界声明（诚实）

- 账号寿命预测是**趋势信号**（非精确到期）：EWMA 失败率 + 连续失效窗口，数据量小时不引入统计回归；无限配额账号 eta_days 按风险档位给保守上限（1/7/30 天）
- 6.3 虚拟滚动未引入：账号 <1k 时既有前端分页已满足，引入虚拟滚动是过度工程（YAGNI）；服务端分页参数已就位，账号量级突破 1k 后可切
- 5.4 Redis 精确限流部署实测未在本轮做（需真实多 worker + redis 环境），README 边界声明保留

---

## 第十三轮历史（4.1 日志按天轮转切分：慢查询根治落地）

> 最后更新：2026-08-05
> 模式：v3.0 路线第 2 批 —— 计划书 4.1 性能根治（日志按天切分 + usage_agg 多文件适配）
> 基线：9174a7b（v2.5.0 收尾）

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 4.1 日志按天轮转切分 | ✅ | services/log_service.py 写 `logs-YYYY-MM-DD.jsonl`、`list(days=N)` 分片读、`delete()` 跨天、`_auto_cleanup()` 两级（过期整删+当天裁剪）；test_log_rotation.py 11 用例 |
| B | 旧 logs.jsonl 惰性迁移 | ✅ | `_ensure_migrated()` 首次访问迁移 + rename 备份；app lifespan 启动即迁移；迁移无丢失无重复测试 |
| C | usage_agg 多文件增量适配 | ✅ | services/usage_agg.py 单例传 DATA_DIR 目录扫 `logs-*.jsonl`、每文件独立 offset、新天文件增量/裁剪才重建、升级检测清空防 double count |
| D | /api/logs days 参数 | ✅ | api/system.py 透传 + 前端 fetchSystemLogs 支持 + logs 页默认 days=7（选日期用 start_date/end_date）；契约守卫断链=0 漂移=0 |
| E | 慢查询报告热点移除 | ✅ | scripts/slow_query_report.py 移除 3 处日志全量读热点（已根治），优化建议标注 4.1 落地 |
| F | 验证全绿 | ✅ | pytest 347 passed / 0 failed；五道防线全 PASS；tsc 0 错误 + build 成功；契约探测 200 |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十三轮 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 慢查询热点从 6 处 → 2 处（日志 3 个热点已根治，剩账号/DB 2 个 P3 量级项）。
> 变异探针 caught=6 escaped=0，还原后全量=OK。

## 当前 git 状态

- 测试：**347 passed / 0 failed**（31 live/redis 排除）
- 前端：tsc 0 错误 + build 成功（logs 页 days=7）
- 契约：断链=0 漂移=0（/api/logs 新增可选 query 参数，响应结构不变）
- 版本：**v2.6.0（已发版）**

## 边界声明（诚实）

- 反向分块读取（4.2）未做：按天切分后单文件量级受 5000 条上限约束，风险已可控，登记远期
- 本机 data/logs.jsonl 已被迁移为 logs-2026-08-05.jsonl（lifespan 启动迁移副作用，data/ 不入库）
- 多 worker 下 usage_agg 各进程各自维护缓存，原子写互不损坏（同 3.5.1 口径）

---

## 第十二轮历史（下一步改进指南首批落地：慢查询根治/账号洞察/编码容错/看板可见性/Redis 一键）

> 最后更新：2026-08-05
> 模式：v3.0 路线第 1 批 —— 计划书 1.2 表 7 项中 5 项实现项全落地 + 2 项规模项登记远期
> 基线：27f2ac1（第十一轮收尾）

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 3.5.1 日志聚合缓存替代全量扫描（慢查询热点根治） | ✅ | services/usage_agg.py（UsageAgg 按小时桶增量聚合+90 天窗口+原子落盘+后台线程）；api/dashboard.py + usage_forecast.py 改读缓存；test_usage_agg.py 7 用例含"mock 断言 usage 端点不调 log_service.list"；慢查询报告热点已移除 |
| B | 3.1.1 `/api/logs` 按 account_email 过滤 | ✅ | services/log_service.py `_matches_filters`/`list` 加参数 + api/system.py `/api/logs?account_email=` + 前端 logs 页筛选输入框；test_logs_account_filter.py 5 用例；契约快照 --update 刷新（断链=0 漂移=0） |
| C | 3.2.1 单账号洞察时间线 | ✅ | accounts/page.tsx 行操作 History 按钮 + 时间线抽屉（拉 `/api/logs?account_email=`）；tsc 0 错误 |
| D | 3.3.4 Windows 中文日志编码容错 | ✅ | utils/log.py `_SafeStreamHandler`（errors='replace' 兜底重写）；test_log_encoding.py 3 用例；变异探针「还原后全量测试」偶发失败根因修复 |
| E | 3.7.2 调度排行榜风险账号可见性 | ✅ | dashboard/page.tsx 档位筛选（全部/风险+温存/仅风险）+ 筛选显示该档位全部（风险档不被 slice(0,10) 截断） |
| F | 3.3.2 Redis 共享限流一键化 | ✅ | scripts/init_redis_state.py（幂等写 redis_url+连通性校验）+ docker-compose.local.yml redis 服务 + README/onboarding 文档段；复用 test_shared_state.py |
| G | 规模项登记远期（不拆分） | ✅ | 计划书 1.2 已登记（openai_backend_api 2974/account_service 1993/conversation 1884；image/accounts/settings 前端页）；本轮不拆防回归 |
| H | 3.1.2 账号批量操作（批量驱逐失效 / 批量打标签 / 批量导出） | ✅ | api/accounts.py `POST /api/accounts/batch`（表驱动 evict_stale/label/export，复用既有逻辑）+ 账号加 label 字段（JSON/SQLite JSON 列自动持久化）+ accounts 页工具栏 3 按钮 + 标签输入 Dialog + 列表 label badge；test_accounts_batch.py 8 用例；契约快照 --update |
| I | 3.1.3 图片工作台增强（seed / 负向提示 / 宽高比预设） | ✅ | seed 后端透传（generations/edits 请求 → image_task_service → protocol → 上游 payload tools[0].seed）；前端 ImageComposer 加固定种子输入（-1 随机）+ 负向提示输入（best-effort 拼入 prompt）+ 宽高比预设（已有 SIZE_PRESETS）；test_generations_seed.py 5 用例（live 标记 1 条）；tsc 0 错误 |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十二轮 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 十二轮补 2 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 慢查询热点从 7 处 → 6 处（「用量统计全量读」已由聚合缓存根治）；变异探针 caught=6 escaped=0，还原后全量=OK（3.3.4 后稳定）。

## 当前 git 状态

- 测试：**337 passed / 0 failed**（31 live/redis 排除）
- 前端：tsc 0 错误 + build 成功（logs/accounts/dashboard/image 页改动）
- 契约：断链=0 漂移=0（/api/accounts/batch 新端点 + image-tasks seed 参数，快照已 --update）
- 版本：**v2.5.0（已发版）**

## 边界声明（诚实）

- 单账号时间线前端为手动走查（未写 UI 单测，避免 brittle 断言）；后端过滤逻辑由 test_logs_account_filter.py 覆盖
- Redis 一键化仅本地验证幂等写入与连通性（本机 Redis 可达）；真实多 worker 精确限流需部署环境实测
- 近 24h 用量为整小时窗口近似（缓存口径），与旧精确 86400 秒窗口误差 ≤1 小时数据量，业务可忽略（test_usage_agg 双算对比文档注明）
- 规模项（3/4）本轮不拆，仅远期记录，见计划书 1.2

---

## 第十一轮历史（onboarding 初级版落地 + 文档漂移全量修复）

> 最后更新：2026-08-05
> 模式：文档闭环轮 —— 新增初级开发者 onboarding + 对照真实代码核查并修复全部文档漂移（含 SKILL.md 自相矛盾）
> 基线：06a61c7（第十轮收尾）

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | onboarding 初级开发者版（零基础） | ✅ | docs/onboarding/07-junior-developer.md（术语表/端到端走查/3 任务演练/测试入门/调试速查/学习路径） |
| B | onboarding README 三版索引 + 版本号/测试数修正 | ✅ | docs/onboarding/README.md（受众分三版；2.0.0→2.3.0；182→338 用例） |
| C | 文档漂移全量核查与修复（对照真实代码） | ✅ | 见下方明细表，8 处不一致全部修正 |
| D | SKILL.md 安全策略段自相矛盾修复 | ✅ | .claude/skills/chatgpt2api-workflow/SKILL.md（RateLimit 已接线/SSRF 仍在，原文档相反） |
| E | config.py 误导 docstring 修正（"超限返回 413"声称→标注） | ✅ | services/config.py:571,582（docstring 已随 H 一并移除） |
| F | project-spec 经 refresh_spec.py 重新保鲜 | ✅ | docs/project-spec.md（413 描述已去除，与 config.py 同步） |
| G | 验证全绿 | ✅ | pytest **308 passed / 0 failed / 30 deselected**（16s）；create_app OK v2.3.0；五道防线全绿 PASS |
| H | 死配置 `max_request_body_mb_*` 彻底移除 | ✅ | services/config.py + config.json(本机) + config.example.json；前端/测试/部署零引用（清理前全量 grep 验证） |
| I | contract_guard 动态键豁免补 scheduler | ✅ | scripts/contract_guard.py DYNAMIC_KEY_ENDPOINTS（health.statuses.* 按账号池实时状态动态生成，第七轮同款教训） |

## 文档漂移修复明细（文档与真实代码不一致，本轮逐一核实修正）

| 文档 | 原过时内容 | 核实后的真实状态 |
|------|-----------|-----------------|
| 01-architecture.md | mermaid 中间件"Metrics → CORS → 请求大小 → 限流 → 安全头" | 仅 X-Request-ID 注入 / CORS / 限流(默认关)（api/app.py） |
| 01-architecture.md | 安全表"请求大小 → api/request_size_limit.py" | 文件已删；`max_request_body_mb_*` 死配置已彻底移除 |
| 01-architecture.md | 安全表"安全头 → api/security_headers.py" | 文件已删（内网自用，安全由调用方处理） |
| 01-architecture.md | 安全表无 SSRF 行 | 补：SSRF 校验保留在图片抓取路径（ssrf_guard.py ← image_inputs.py:261） |
| 03-setup.md | max_request_body_mb_* 环境变量"请求体上限（MB）" | 环境变量已删除（死配置彻底移除） |
| README.md | "移除 RateLimitMiddleware/.../SSRF 防护" | 限流已在 v2.3.0 重新接线（S-R15）；SSRF 校验保留 |
| README.md | "限流在 v2.3.1 已重新接线" | 版本号实为 **v2.3.0**（无 v2.3.1） |
| golden-examples.md | 引用已删文件 `api/security_headers.py` | 加"文件已删，模式仍可参考 + 当前中间件清单"注记 |
| SKILL.md | "已移除 RateLimitMiddleware/.../SSRF 防护" | 限流已接线、SSRF 仍在；已移除的仅 SecurityHeaders/RequestSizeLimit/MetricsMiddleware |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十一轮 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 本轮改动含死配置移除（`/api/settings` 字段减少，经 `contract_guard --update` 更新基线）+ 契约守卫 scheduler 豁免补丁。防线输出：`reports/`

## 边界声明（诚实）

- **Windows 中文日志编码偶发**：并发场景下 `utils/log.py` 输出含中文日志经管道（GBK 编码）偶发 UnicodeEncodeError，导致变异探针"还原后全量测试"偶发失败（对照实验：stash 后 308 passed、恢复后亦 308 passed，失败点随机在 fetch_remote_info / test_resume_poll_token——非业务回归）。探针核心结论"6 变异全被抓住 / 逃逸 0"不受影响。
- 真实上游图片生成/编辑（live）需用户自测烧配额
- 多 worker 进程内限流不共享（需 Redis）

## 当前 git 状态

- 测试：**308 passed / 0 failed**（30 live/redis 排除）
- 前端：tsc 0 错误 + build 成功（本轮未改前端）
- 契约：断链=0（未改 API 字段）
- 版本：v2.3.0（已发版，本轮不发新版号）

---

## 第十轮历史（终局总审计 + 六维独立复验 + v2.3.0 全量闭环）

> 最后更新：2026-08-04
> 模式：终局闭环第十轮 —— 以"即将被真实用户/调用方/部署者使用"标准做最严格审计，多 agent 审查 → 主线程修复 → 复验循环
> 基线：918371e（v2.3.0 发版）+ 三批排期修复 + 终局审计三批

### 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 终局审计六维审查（6 个只读 agent：契约/UI/后端/数据/静默失败/部署） | ✅ | reports/final-audit-findings.md（58 项已修/确认） |
| B | 三大假接口前端接入（usage-forecast 看板 / weighted_random 设置 / proactive 开关） | ✅ | dashboard/page.tsx + settings/store + config-card |
| C | 越权修复（dashboard 后端 require_admin + 前端 admin 守卫） | ✅ | 无鉴权 401，普通 user-key 403 |
| D | 限流中间件接线（此前定义未注册=配置无效） | ✅ | api/app.py add_middleware |
| E | resume_poll resume_inflight 竞态守卫 | ✅ | 双扣配额风险消除 |
| F | 原子写统一 / X-Request-ID 注入 / SSE 重连 / 破坏性确认全覆盖 | ✅ | 三批提交 |
| G | SKILL.md 固化 13 条新 bug 警示（可复用） | ✅ | .claude/skills/chatgpt2api-workflow |
| H | HTML 终审报告 + 测验 | ✅ | docs/final-report-v10.html |
| I | 六维独立复验线程 | ✅ | 结论 WARNING → 修复 10 项（1 HIGH + 4 P2 + 5 P3）→ 复验 308 passed 转 Approve；顺带抓到 logging 未 import 真 bug |
| J | 记忆文件更新 | ✅ | chatgpt2api-v2.3.0-closed-loop.md |

### 终局审计提交链

- 918371e v2.3.0 发版收尾
- 454b309 终局审计 P0/P1 首批（假功能+越权+限流接线+破坏性操作确认）
- d764e32 终局审计 P0/P1 第二批（Docker 构建/权限/原子写/请求头/文档对齐）
- 2b55426 终局审计 P0/P1 第三批（SSE重连/越权补全/破坏性确认全覆盖/用量预测边界）
- bfdbd0f SKILL.md 固化 13 条新 bug 警示

### 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 终局批一 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 终局批二 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 终局批三 | ✅ | ✅ | ✅ | ✅ | ✅ |

### 边界声明（诚实）

- 真实上游图片生成/编辑（live）需用户自测烧配额
- 多 worker 进程内限流不共享（需 Redis）
- Docker 容器实跑 / WebDAV / R2 需真实环境
