# 验证登记表（Verification Registry）

> **用途**：记录"当前已验证的真实基线"，让下次会话**先读本表**再决定要不要重跑——避免每次都盲目重复跑慢查询/防线/全量测试。
> **使用协议**（写进 SKILL.md 会话启动协议）：
> 1. 动手前先读本表 + `workflow_status.md` 最新一轮。
> 2. 只在**改动落到某区域**时才重跑该区域对应的验证；没碰的区域沿用本表结论，不重跑。
> 3. 每次改动后**更新本表**：标注改了哪个区域、对应验证的新结果与日期。
> 4. 「已知 flaky / 边界」列里的事项**不要重复追查**（已定性，非回归）。

---

## 一、当前验证基线（最新一轮：v2.37.0 告警接线+救号工作流+熔断多Worker一致化+覆盖率+安全纵深+前端体验）

| 项 | 结果 | 范围/说明 | 日期 | 证据 |
|----|------|-----------|------|------|
| 全量单测 | **1596 passed / 0 failed** | 全量 pytest（排除 live）；新增 G1~G6 相关测试 110+ 用例 | 2026-09-15 | `pytest test/ --ignore=test_fomimage_live.py`（295s） |
| 六道防线 | **全绿** | 契约断链=0 漂移=0；SQL P0=0 P1=0；慢查询 resolved=0；变异 caught=33 escaped=0；施压 8/8；文档同步 PASS | 2026-09-15 | reports/*（各防线） |
| 覆盖率 | **64%**（门禁 fail_under=55） | services+api 行覆盖 62%→64%；retry_budget/ssrf_guard/image_failure/providers 100%、rate_limit 96%、cost_service 89% | 2026-09-15 | `pytest --cov=services --cov=api` |
| 性能基准 | **PASS** | 126.6 rps / p99 462ms / 错误率 0 / 慢存储 p99 358ms（预算 30rps/1500ms/1%） | 2026-09-15 | `benchmark_check.py` |
| 前端 | tsc 0 错误 + build 成功 | 告警空态+测试按钮 / 救号工作台 / 熔断徽章 / 全局搜索聚合 / 通知中心事件流 / 待登录 statusMeta | 2026-09-15 | `tsc --noEmit` + `npm run build` |
| 契约守卫 | 断链=0 漂移=0 | 新增 alerts/test、revive/run、revive/status、revive/ledger 已注册 DYNAMIC | 2026-09-15 | `contract_guard.py` |
| E2E | **16 passed / 2 skipped / 0 failed** | Playwright 真实前后端（登录/看板/账号/设置）；清理残留服务后全绿 | 2026-09-15 | `npx playwright test` |
| 启动冒烟 | OK | `from api.app import create_app` 无报错 | 2026-09-15 | 实跑 |

## 二、本轮新增/改动区域 → 对应验证

| 区域 | 改动 | 验证 | 状态 |
|------|------|------|------|
| G1 告警接线闭环（v2.37.0） | `api/system.py`（alerts/test 端点）+ `services/alert_service.py`（test_alert）+ `services/disk_alert_guard.py`（磁盘守护）+ `api/app.py`（lifespan 接线）+ 前端 config-card（空态引导/测试按钮/状态点） | test_alert_test_endpoint 9 + test_disk_alert_guard 6 + 告警回归 42 + ruff 0 + 契约 0 | ✅（本轮闭环） |
| G2 救号工作流（v2.37.0） | `services/revive_workflow.py`（异步工作流+ReviveLedger）+ `api/accounts.py`（revive/run + status + ledger）+ `event_bus.py`（REVIVE_FINISHED）+ `task_queue_init.py` + 前端救号工作台 | test_revive_workflow 11 + 回归 62 + 契约 0 | ✅（本轮闭环） |
| G3 熔断多Worker一致化（v2.37.0） | `services/circuit_breaker.py`（SharedBreakerStateStore）+ `shared_state.py`（keys()）+ dashboard store 字段 + 前端徽章 | test_breaker_shared_state 6 + 熔断 33 回归 + 契约 0 | ✅（本轮闭环） |
| G4 前端体验（v2.37.0） | `global-search.tsx` 聚合 + `notification-center.tsx` 事件流 + accounts q 预填 | tsc 0 + build + E2E 16 passed | ✅（本轮闭环） |
| G5 覆盖率（v2.37.0） | `test/test_g5_coverage_core.py`（49 用例）+ test_kookeey_providers 修正 | 六大模块 89%~100%；全量覆盖率 64% | ✅（本轮闭环） |
| G6 安全纵深（v2.37.0） | S1 metrics_token / S2 内容类型白名单 / S3 SMTP 弱口令 / S4 CI security-audit / S5 配置保存审计 | test_metrics_token 4 + test_g6_security 13 + 回归 101 + ruff 0 | ✅（本轮闭环） |
| 回归修复（v2.37.0） | account_service 待登录白名单 + 前端 statusMeta + image_task 时间戳 + property hypothesis + openapi 重生成 | 全量 pytest 1596 passed（修复后） | ✅（本轮闭环） |

### v2.36.0 历史基线（沿用，未重跑）

| 项 | 结果 | 范围/说明 | 日期 | 证据 |
|----|------|-----------|------|------|
| 八道防线 | **8/8 PASS**（契约/SQL/慢查询/变异/施压/文档同步/性能基准/覆盖率门禁） | run_all_guards.py；变异 caught=33 escaped=0 drift=0；施压 8/8；覆盖率门禁 measured=62% ≥ fail_under=55% | 2026-08-12 | reports/* + `run_all_guards.py` |
| 全量单测 | **覆盖 62% 的全量 pytest 通过**（fail_under=55，真实 exit 0） | 覆盖率门禁内跑全量；此前基线 1179 passed（v2.33.0） | 2026-08-12 | `pytest --cov` |
| 覆盖率（增量门） | **services+api 行覆盖 60~62%**（门禁 fail_under=55） | VII-01 首次实测：两轮全量 60% / 62%；目标 90%+，每提升一档上调 5pt；`pyproject [tool.coverage.report] fail_under` + CI coverage gate + `scripts/coverage_guard.py` | 2026-08-12 | `pytest --cov=services --cov=api`；reports/coverage/ |
| 性能基准 | **PASS（8/8）**，实测吞吐 149.5 rps / p99 334.3ms / 慢存储 p99 262.7ms / 错误率 0 | V-04：`docs/benchmark-baseline.json` 阈值（≥30 rps / ≤1500ms / ≤1%）；`scripts/benchmark_check.py` 断言最近施压 JSON | 2026-08-12 | reports/stress/ + reports/benchmark/ |
| 六道防线·契约守卫 | PASS（断链=0 漂移=0） | 本轮涉 R2/回收站/least_used/粘性IP 区域 | 2026-08-12 | reports/contract/ |
| 六道防线·SQL 审查 | PASS（P0=0 P1=0） | 修 `text(` 启发式误报（write_text 撞 text(f），加负向后瞻 | 2026-08-12 | reports/sqlaudit/ |
| 六道防线·慢查询 | PASS | | 2026-08-12 | reports/slowquery/ |
| 六道防线·极限施压 | PASS（8/8） | | 2026-08-12 | reports/stress/ |
| 六道防线·变异探针 | PASS（caught=33 escaped=0） | mutation_probe.py 本轮增强后 | 2026-08-12 | reports/mutation/ |
| 六道防线·文档同步 | PASS | docs_sync_check.py 首跑（VERSION 与 4 文档一致） | 2026-08-12 | reports/docs_sync/ |
| 前端 | tsc 0 错误 + build 成功 | npm run build（含类型检查） | 2026-08-12 | `npm run build` |
| E2E | **16 passed / 0 failed**（2 skipped 容错） | e2e/ Playwright 真实前后端（登录/看板/账号/批量通知 4 spec）；v2.33.0 重跑确认（accounts/dashboard spec 默认 AUTH_KEY 对齐 config） | 2026-08-12 | `playwright test` |

## 二·B、历史轮次完成区（v2.34.0 及更早，对照 workflow_status）

| 区域 | 改动 | 验证 | 状态 |
| 工程效能 VII-01~04 + V-04（本轮） | `pyproject.toml`（pytest-cov + [tool.coverage] 门禁 + 补 hypothesis/aiosqlite 声明）、`.github/workflows/ci.yml`（coverage gate + OpenAPI/SDK --check + guards job）、`scripts/coverage_guard.py`、`scripts/benchmark_check.py` + `docs/benchmark-baseline.json`、`generate_openapi_spec.py --check`、`generate_sdks.py --check`（含 GBK 安全输出）、`run_all_guards.py` 扩至八道防线、`stress_test.py` 慢存储注入 marker 修复、`scripts/hooks/`（文档保鲜 git hook） | 各脚本本地实跑：openapi/sdk --check PASS、coverage_guard PASS（62%≥55%）、benchmark PASS、hook 放行/阻塞双路径验证；CI job 需 GitHub Actions 环境 | ✅（本轮） |
| R2 图片存储后端 | `services/image_storage_service.py` R2Client（AWS SigV4，纯 Python）+ config r2_* 四字段 | `test/test_image_storage_service.py`（覆盖签名/上传/读取/删除/列对象/降级） | ✅（第二十一轮闭环） |
| 变异探针增强 | `scripts/mutation_probe.py`（282 行增量，锚点覆盖 14 测试文件） | `pytest` 全量 + 防线变异（caught=33 escaped=0） | ✅（第二十一轮闭环） |
| R2 前端配置接线（v2.33.0） | `web/src/lib/api.ts`（ImageStorageMode 加 r2/r2_local + 五字段）+ `settings/store.ts`（normalize/save 补 r2）+ `config-card.tsx`（R2 表单 + 按模式测试按钮）+ `api/system.py`（image-storage/test 按 mode 分流） | `npx tsc --noEmit` 0 错误 + `npm run build` 成功 + `test_image_storage_service.py` 端点 3 项 | ✅（本轮闭环） |
| R2Client 层测试（v2.33.0） | `test/test_image_storage_service.py` 新增 16 项：validate 缺字段 / object_key / SigV4 参考重算 / put-get-delete / ListObjectsV2+continuation / 连接测试 | 存储单测 29 passed | ✅（本轮闭环） |
| e2e/ 纳入版本控制（v2.33.0） | `e2e/` 14 文件 + `.gitignore` 排除产物 + `docs/e2e.md` 使用说明 | `git ls-files e2e/`=14；E2E 基线 16 passed/0 failed（v2.32.0 记录） | ✅（本轮闭环） |
| diagnose/healing .json() 修复（v2.33.0） | `web/src/lib/api.ts` 4 个封装函数去掉 `resp.json()` 误用 + 补泛型 | `npx tsc --noEmit`（此前 5 错，现 0） | ✅（本轮闭环） |
| 回收站/least_used/粘性IP | `services/trash_service.py` + `account_service._pick_least_used` + `proxy_service.get_profile`（v2.32.0 已提交） | `test/test_trash_scheduler_sticky.py` 等 11 项 | ✅（v2.32.0 闭环） |
| 事件流 SSE | `/api/events/stream` + `/api/dashboard/events` + events.jsonl 持久化（v2.31.0 已提交） | `test/test_events_stream.py` 8 项 | ✅（v2.31.0 闭环） |
| 文档同步 | SKILL.md/workflow_status/verification-registry/CLAUDE.md/project-spec + docs_sync_check.py | 本表 + `run_all_guards.py` 第六道防线 | ⏳ 回填 |
| 源码树清理 | 87 ,cover + deploy.tar + web_dist_bak + tmp_pg5 + 根 final-report 移除，.gitignore 收紧 | `git ls-files` 残留=0；`find . -name "*,cover"`=0 | ✅ |
| 响应缓存 | `api/response_cache.py` 5 端点（v2.30.0 已提交） | `test/test_response_cache.py` 22 项 | ✅（v2.30.0 闭环） |
| 自适应调度/配置热加载 | `adaptive_scheduler.py` + `config_watcher.py`（v2.30.0 已提交） | `test/test_scheduler_modes.py` 28 项 + `test_config_watcher.py` 7 项 | ✅（v2.30.0 闭环） |
| 产品策略刷新（2026-08-12） | `docs/product-strategy.md` 第八轮刷新：告警状态更新为**已实现（多通道）/接线是缺口**（v2.34.0 III-07），并纠正账号日志过滤/排行榜风险可见性/寿命预测/容量规划四处"缺口"已闭环；`docs/onboarding/` 补「验证 E2E」章节（链接 docs/e2e.md） | docs_sync_check PASS（VERSION 未变，纯文档任务） | ✅ |

## 三、已知 flaky / 边界（**不要重复追查**）

- **~~变异探针「还原后全量」偶发 FAIL~~（已根治 v2.9.0）**：Windows GBK 中文日志偶发 `UnicodeEncodeError`。已强制子进程 UTF-8（PYTHONIOENCODING + errors=replace）。
- **`test_refresh_error_window_is_600` 偶发 flaky**（本轮记录）：全量顺序跑偶发红、单独跑/单文件跑恒绿、干净全量跑绿（1162 passed）。断言 800s 前刷新错误 → healthy（窗口 600），与防线/并发跑时的状态残留或时序相关。**不阻塞**，已在干净跑验证通过；若再遇，单独复跑该测试确认即可。
- **真实上游图片/OTP/Graph 联网**：live 测试默认排除，需真实凭证+烧配额，由用户手动 `-m live` 自测。
- **71 个遗留异常号**：mail_credential 入库功能之前导入，池内无取件凭证 → watcher 自动救活无效，只能 `revive_abnormal.py` + 外部 payload 一次性救。
- **代理出口（kookeey/v2ray TUN 分流）**：`gate.kookeey.info:1000` 本机 TUN 下不可达属用户网络/基础设施决策；代码层 `kookeey_proxy_for` 已就绪。
- **kookeey 凭据经 /api/settings 返回**：与既有全局 `proxy` 凭据处理一致（均返回供管理员编辑，仅 auth-key 被 pop）。内部管理员工具、需鉴权。
- **多提供商为「地基」阶段**：provider 字段+注册表已就位；调度分池/路由分发/前端切换器是后续阶段。
- **R2 图片存储无真实凭证**（本轮新增边界）：单测覆盖 SigV4 签名与逻辑降级；真实上传需用户配 r2_account_id/access_key/secret/bucket 后自测。
- **粘性 IP 依赖 kookeey.proxy_enabled**（本轮新增边界）：默认 false 行为不变，测试用 mock；服务器已开 true。
- **CHANGELOG 缺版本段**（v2.21/2.22/2.23/2.26–2.29）：git log 有提交但 CHANGELOG 未登记，已记入 workflow_status 矩阵，不重复追查。
- **e2e/ Playwright 运行前置**：需本机 Edge（msedge channel）+ 起真实前后端（23456/3000），worker=1。
- **本地系统 python 3.11 全量 6 failed（2026-08-12 记录，非回归）**：test_tracing 4 项（Windows 时钟粒度下 `duration_ms==0` 断言过严）+ test_property_account 1 项（hypothesis 6.165.3 FailedHealthCheck filter 比例）+ test_circuit_breaker 1 项（flaky）。`git stash` 验证无改动时同样失败，**非 GZip 修复引入**；服务器/CI（Python 3.13 + venv）不受影响。本地全量基线以 `1287 passed` 为准。

## 四、历史审计修复明细

v2.9.0（24 确认已修 / 8 驳回）与更早轮次的审计明细见 git history 与旧版 workflow_status；本表聚焦当前基线，历史明细不再全文保留。

## 五、各区域"最近改动"速记（下次只重测这些）

- 2026-08-12（GZip hotfix）：`api/app.py`（移除 GZipMiddleware——gzip+chunked 在代理链路下 Chrome ERR_INVALID_CHUNKED_ENCODING，改走 identity+Content-Length）、`test/test_contracts.py`（scheduler_mode 补 least_used）、web_dist 重新构建并上传服务器对齐 v2.34.0 → 重跑：contracts 10 passed + 三端点响应头验收（Content-Length 无 gzip，已做）；服务器容器 healthy。
- 2026-08-12（工程效能 VII 轮）：`pyproject.toml`（覆盖率门禁 + 依赖补齐）、`ci.yml`（coverage/guards/--check job）、`run_all_guards.py`（八道防线）、`coverage_guard.py`、`benchmark_check.py` + `docs/benchmark-baseline.json`、`generate_openapi_spec.py --check`、`generate_sdks.py --check`、`stress_test.py`（慢存储 marker）、`scripts/hooks/`（文档保鲜 hook）→ 重跑：coverage_guard + benchmark_check + 防线全量 + hook 冒烟。
- 2026-08-12（第二十二轮）：`api/system.py`（image-storage/test 按 mode 分流）、`web/src/lib/api.ts` + `settings/store.ts` + `config-card.tsx`（R2 接线 + diagnose/healing .json() 修复）、`test/test_image_storage_service.py`（R2Client 层 16+3）、`docs/e2e.md`、CHANGELOG/VERSION（v2.33.0）→ 重跑：image_storage/config 相关测试 + 前端 build/tsc + 防线全量 + E2E。
- 2026-08-12（第二十一轮）：`services/image_storage_service.py`（R2Client）、`scripts/mutation_probe.py`、`scripts/docs_sync_check.py`、`scripts/run_all_guards.py`、`.gitignore`、SKILL.md、workflow_status.md、verification-registry.md、CLAUDE.md、docs/project-spec.md → 已验证，重跑沿用。
- 2026-08-11（v2.32.0）：`services/trash_service.py`、`account_service.py`（least_used）、`proxy_service.py`（get_profile）、`config.py`（scheduler_mode）、`api/accounts.py`（trash 端点）→ 已验证，重跑沿用。

---

*本表随每轮改动更新；历史轮次的详细矩阵见 `workflow_status.md`。*
