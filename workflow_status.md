# ChatGPT2API 工作流状态 — 第二十三轮（v2.34.0 里程碑3/5 + 工程效能 + Phase 4）

> 最后更新：2026-08-12
> 模式：v2.34.0 III-01~07（回收站根因/调度A/B/配额预警/慢查询/连接池/备份校验/告警多通道）+ V-01~04（bundle/缓存/虚拟列表/基准化）+ VII-01~04（覆盖率/防线CI/文档钩子/OpenAPI）+ Provider Phase 4（grok）
> 基线：v2.35.0

> 上一轮（第二十二轮，v2.33.0）已闭环：R2 接线 6 步 + e2e 体系。历史明细见 git history 与 docs/verification-registry.md。

## 补记（2026-08-12，GZip hotfix，commit 321c1d8）

**背景**：用户浏览器报大量 `ERR_INVALID_CHUNKED_ENCODING` + 页面显示 v2.32.0（后端 v2.34.0）。
**根因**：`api/app.py` GZipMiddleware（minimum_size=500）→ 所有 >500B 响应 `gzip + chunked + Connection: close`，用户代理路径（v2ray/Clash）下 Chrome 严格解析 chunk 失败（curl 宽容成功）。且 v2.34.0 发版只重建后端镜像，web_dist（volume 挂载）未上传 → 前端停在 v2.32.0。
**处理**：① 移除 GZipMiddleware（响应走 identity+Content-Length+keep-alive，根治）；② `test/test_contracts.py` scheduler_mode 补 least_used（v2.32.0 引入但契约断言漏更新，本地/服务器 least_used 配置下契约测试失败）；③ 重新构建 web_dist 并 tar 上传服务器；④ push 321c1d8 + 服务器 git pull + compose build/up -d。
**验收**：容器 healthy；`/version`→v2.34.0；三端点 Content-Length 无 gzip、keep-alive；SSE 纯 chunked 无 gzip。
**测试**：本地全量 1287 passed / 6 failed（5 预先存在 tracing/property 环境差异 + 1 circuit flaky，`git stash` 验证非本次引入，见 verification-registry 已知 flaky）。

> **硬教训**：GZipMiddleware 在代理链路（v2ray/Clash/TUN）下与 Chrome 不兼容，自托管多走代理时**不要启用 gzip**；后端发版 ≠ 前端发版，web_dist 有前端改动须单独重建上传。

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | Provider Phase 4 + grok（§2.6） | ✅ | 账号/设置/图片三入口切换器 + grok enabled + 生图 provider 透传链路（前端→image-tasks→task service→protocol→按 provider 取号）；router/provider_scheduler/registry 113 + 365 测试；grok 出图需外部上游凭据（已标注降级） |
| B | III-01 回收站根因面板 | ✅ | trash stats 加 by_reason_top/trend + top_reasons query + trash-dialog recharts 分布图；17 测试 |
| C | III-02 调度A/B + III-03 配额预警 | ✅ | scheduler_pick_total 加 mode 标签 + per-mode 统计 + 配额剩余天数第三信号（只降不升）；dashboard 模式对比卡 + 配额 badge；78 测试 |
| D | III-04 慢查询清零 + 基准化 | ✅ | json/db 存储优化 + c2api_storage_operation_duration_seconds 指标（10 埋点）+ slow_query JSON 门禁（--max-hotspots）；2 热点 accepted_degradation 如实标注；90 测试 |
| E | III-05 连接池泄漏 | ✅ | 借用追踪 + stats()（idle/in_use/hit_rate）+ leak_report + cleanup_stale 健康接管 + session_pool.leak 告警；18 测试 + 118 回归 |
| F | III-06 备份完整性 | ✅ | 上传后读回 sha256 比对三态（verified/mismatch/unavailable）+ backup.checksum_mismatch 告警 + 状态字段；8 测试 + verify_backup_roundtrip PASS |
| G | III-07 告警多通道 | ✅ | Telegram/SMTP/企微/钉钉通道抽象 + config alert_channels（env 覆盖）+ 前端配置 UI；18 测试 |
| H | V-01 bundle + V-03 虚拟列表 | ✅ | recharts 懒加载摘除（dashboard -119KB / accounts -116KB）+ 日志/图片/账号三列表虚拟化 + 滚动记忆；bundle 预算如实说明未达 150/300KB（框架下限）；tsc + build |
| I | V-02 响应缓存扩展 | ✅ | /api/logs、trash、usage、events 4 端点接入（TTL 5~15s + 写侧 invalidate + ?refresh=1）+ contract_guard 同步；21 测试 + 111 回归 |
| J | VII-01~04 + V-04 | ✅ | 覆盖率门禁（实测 62% ≥55% + 增量门）+ 防线扩八道 + CI guards/coverage/OpenAPI --check + 文档保鲜 githooks + 压测基准（149.5 rps / p99 334ms + 阈值断言） |
| K | 验收：八道防线 + 回归 | ✅ | 八道防线 8/8 PASS（变异 caught=33 escaped=0 drift=0；施压 8/8；覆盖率门禁 62%）；契约快照同步预期字段新增 |

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

> 首次跑时 SQL 审查 FAIL（P0=2）：`docs_sync_check.py` 的 `write_text(f"..")` 撞 `sql_audit` 的 `text(f"` 启发式误报（与历史 `_extract_otp_code` 同类）。已修 `scripts/sql_audit.py` 给 `text(` 模式加 `(?<![A-Za-z_])` 负向后瞻，重跑 P0=0。变异探针 caught=33 escaped=0（本轮 mutation_probe 增强后）；施压 8/8。

## 当前 git 状态

- 源码树清理：216 个 `D`（87 ,cover + web_dist_bak 123 + deploy.tar + tmp_pg5×2 + 根 final-report×3）待提交
- 文档同步：SKILL.md / workflow_status.md / verification-registry.md / CLAUDE.md / project-spec.md / .gitignore / CHANGELOG(未改) 待提交
- 未提交代码改动：config.json R2 配置 + `services/image_storage_service.py` R2Client + `scripts/mutation_probe.py` 增强 + 12 个测试文件（pytest 基线全绿，随本轮一并提交）
- 未跟踪：`e2e/`（playwright E2E 项目，含 node_modules 已 ignore）、`t2i.json`（测试产物，删）、`test/test_property_session.py`（新测试，入库）

## 边界声明（诚实）

- **CHANGELOG 未补写缺版本段**：v2.21/2.22/2.23/2.26–2.29 无独立段，仅在 workflow_status 矩阵登记——补写需按 git log 核对归并，超出本次范围，已记入矩阵警示
- **E2E 真实跑**：本轮用 `e2e/` Playwright 项目（登录/看板/账号/批量通知 4 spec）起真实前后端跑；上游联网类断言沿用既有边界（live 测试默认排除）
- **R2 图片存储未做真实上传**：无 R2 凭证，仅单测覆盖 SigV4 签名与逻辑，真实上传由用户配 r2_* 后自测
- **docs/ 下历史 final-report html（v4/v5/v10/v2.9.0）保留**：属历史审计归档，未动；仅清理根目录散落 3 份
