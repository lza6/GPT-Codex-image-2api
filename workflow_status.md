# ChatGPT2API 工作流状态 — 第二十一轮（v2.32.0 文档同步 + 源码树清理）

> 最后更新：2026-08-12
> 模式：v2.32.0 账号回收站 + 雨露均沾调度 + 粘性 IP → 文档/版本全面对齐
> 基线：v2.32.0

## 本轮完成清单

| 编号 | 事项 | 状态 | 证据 |
|------|------|------|------|
| A | 文档/版本脱节根治（P0） | ✅ | 见下方「文档同步明细」——SKILL.md/workflow_status/verification-registry/project-spec/CLAUDE.md 五份全部对齐 v2.32.0 |
| B | 源码树污染清理（P0） | ✅ | 87 个 `,cover`（coverage annotate 产物）git rm + 磁盘删；deploy.tar/web_dist_bak/tmp_pg5×2/根目录 final-report×3 git rm + 归档；c2api_restart.log 删；`git ls-files` 残留=0 |
| C | .gitignore 收紧防复发 | ✅ | 补 `**/*,cover`、`*.tar`、`web_dist_bak/`、`*.png`+assets 白名单、`e2e/test-results|playwright-report|node_modules` |
| D | docs_sync_check.py 防复发 | ✅ | `scripts/docs_sync_check.py` 比对 VERSION 与 SKILL/CLAUDE/workflow_status/verification-registry 内嵌版本号；接入 run_all_guards.py 成第六道防线 |
| E | refresh_spec.py 保鲜触发 | ✅ | `python scripts/refresh_spec.py` → `[REFRESHED]`，project-spec.md 应用版本 v2.32.0（294 行/89 配置/53 服务模块） |
| F | 未提交改动验证 | ✅ | config.json R2 配置 + `image_storage_service.py` R2Client + mutation_probe 增强 + 一批测试，pytest 基线全绿 |
| G | 六道防线 + 回归 + E2E | ⏳ | 验收后回填（本轮涉及 R2/存储/文档/清理，防线全量重跑） |

## 文档同步明细（P0）

| 文档 | 原声称 | 现 | 改动 |
|------|--------|----|------|
| `.claude/skills/chatgpt2api-workflow/SKILL.md` | v2.13.0 | v2.32.0 | 架构树入档 12 个新模块（trash/adaptive_scheduler/config_watcher/diagnostic_engine/auto_healer/cost_service/session_cache/response_cache/tracing/quota_service/log_index/account_warmup）+ 事件总线 v2.24 Pub/Sub 段 + 六道防线 + 验收清单 v2.18+ 专项 + 关键文件速查 13 行 + 历史 bug 表 4 条 |
| `workflow_status.md` | 第二十轮 v2.18.0 | 第二十一轮 v2.32.0 | 本文件：补 v2.18→v2.32 完成矩阵 |
| `docs/verification-registry.md` | v2.9.0 | v2.32.0 | 基线表/区域表/最近改动速记全部刷新 |
| `docs/project-spec.md` | v2.7.1 陈旧 | v2.32.0 | refresh_spec.py 重新生成（[REFRESHED]） |
| `CLAUDE.md` | "2026-08-02 v2.0.0 已发版" | "2026-08-12 v2.32.0 已发版" | 当前状态段 + 六道防线措辞 |

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

> **CHANGELOG 缺口警示**：v2.21/v2.22/v2.23/v2.26–v2.29 在 CHANGELOG.md 无独立版本段（功能部分并入 v2.30.0 段），git log 有对应提交。已在本矩阵如实登记，未擅自补写 CHANGELOG。

## 六道防线状态

| 批次 | 契约 | SQL | 慢查询 | 变异 | 施压 | 文档同步 |
|------|------|-----|--------|------|------|----------|
| 第二十一轮 | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS | ✅ PASS |

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
