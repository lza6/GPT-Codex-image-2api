# ChatGPT2API 工作流状态 — 第七轮（规范固化 + 五道防线增量闭环）

> 最后更新：2026-08-02（本轮启动）
> 模式：终局闭环第七轮 —— Spec Kit 技能固化 + 全量增量审计 + 五道防线工具化 + 盲区扫描 + 终审校验清单注入
> 历史基线（第六轮收尾，已提交 git）：N1–N28 闭环、S1–S8 核验、182 passed/0 failed、tsc 0 错误、v2.0.0 已发版、web_dist 已构建同步

## 本轮权威需求源（用户本轮指令逐条结构化）

| 编号 | 需求（原文浓缩） | 类型 | 当前状态 | 证据/位置 | 缺口 → 动作 |
|------|----------------|------|---------|-----------|------------|
| R1 | 使用 Spec Kit 技能（本地优先，缺失则联网安装），把项目沉淀为"工作流+技能"，先读文档/记忆/规则判过时→更新→编码 | 显式 | 🟡 部分 | `.claude/skills/chatgpt2api-workflow`（22a2ec5 已建，需判过时并更新）；speckit 相关技能本地已安装 | 需注入：终审校验清单、五道防线、五角色门禁、Reviewer-Gate、盲扫条款、AI 先读规则 |
| R2 | 必须使用 addyosmani/agent-skills 的技能 | 显式 | 🟡 适配中 | 该仓库为 Web 性能类技能集（web-perf、performance-budget、core-web-vitals 等） | 按适用性注入到 skill；全量硬塞会引入无证据误报，已在盲区扫描记录权衡 |
| R3 | 生成 workflow_status.md 并循环直至闭环 | 显式 | ✅ 本文件 | 本文件 | 持续更新 |
| R4 | 最终 HTML 报告（上下文/直觉/变更/底部必过测验） | 显式 | 🔲 未做 | 前例 `final-report-v5.html` | 产出 `final-report-v7.html`，含本轮证据链+测验 |
| R5 | 完成后启动独立审查线程（六维：需求完整性/逻辑正确性/边界/代码质量/测试覆盖/实际运行），循环修复复验 | 显式 | 🔲 未做 | 前轮已执行过红队审查（Approve） | 本轮对新产物（skill/工具/文档）做独立审查循环 |
| R6 | 严苛代码审查者（有罪推定/零懒惰/输出格式 Summary/Critical/Required/Suggestions/Verdict） | 显式 | 🔲 未做 | — | 作为 skill 的 reviewer 门禁 + 本轮对增量产物执行 |
| R7 | 契约防坑测试（前后端字段对齐回归） | 显式 | 🟡 存在需加强 | `scripts/contract_probe.py`、`test/test_contracts.py` | 需审计覆盖度：是否所有页面×端点契约对都覆盖；缺口补齐 |
| R8 | 极限施压/防穿透（极端情况系统不崩、数据不错乱） | 显式 | 🟡 部分 | 第六轮压测 7912 req/min；内存/慢存取边界未测 | 产出 `scripts/stress_test.py`：worker 内存模拟压测 + 慢存储注入 + 关键响应预算 + 并发一致性 |
| R9 | 慢查询猎杀与索引优化 | 显式 | 🔲 未做 | SQLite/JSON 存储 | 产出 `scripts/slow_query_report.py`：top 表数据量分布、n² 扫描点、索引/分页建议（只读，不改库） |
| R10 | SQL 安全与正确性审查（锁表/死锁/注入） | 显式 | 🟡 部分 | 存储层参数化（待证实） | 产出 `scripts/sql_audit.py`：存储层注入面、事务边界、并发写冲突静态审查报告 |
| R11 | 覆盖率 80% 但上线仍出 Bug → 测试有效性 | 显式 | 🟡 部分 | 182 测试全绿 | 产出 `scripts/mutation_probe.py`：关键判断种子变异，验证测试是否真能抓住回归 |
| R12 | 项目门面与"新人保姆"文档生成器 | 显式 | ✅ 已存在未提交 | `docs/onboarding/`（7 篇，git 未跟踪） | 验真 + 提交 git |
| R13 | 逆向生成架构资产与 ADR | 显式 | 🔲 未做 | `计划书/` 有执行记录 | 产出 `docs/adr/`（关键决策记录） |
| R14 | 提取黄金代码范例 | 显式 | 🔲 未做 | — | 产出 `docs/golden-examples.md` |
| R15 | 目录重构与文档索引自动化 | 显式 | 🟡 部分 | 根目录 docs/计划书/graft/ 等 | 盘点 → 低风险归位 + 索引 |
| R16 | 目录整理、杜绝屎山 | 显式 | 🟡 部分 | S4 巨文件已登记 v2.1（不重拆） | 低风险清理 + 索引，不做大重构 |
| R17 | 产品头脑风暴（资深产品总监视角，商业化/留存/增长） | 显式 | 🔲 未做 | 内部工具定位（记忆中已知） | 产出 `docs/product-strategy.md`（诚实标注适用边界） |
| R18 | Agent 管理 Agent，自动挑选高价值改进项 | 显式 | 🟡 本轮即执行 | 本轮多代理编排 | 扫描→排级→落地可落地的，登记不可落地的 |
| R19 | 一次调用就能跑通（调用者/使用者零门槛） | 显式 | 🟡 待验 | onboarding 03-setup 已写 | 文档步骤复核 + 冒烟脚本核验 |
| R20 | 全面查漏补缺、未知未知（盲区扫描） | 显式 | 🔲 本轮核心 | — | 五角色并行审计 + 盲区合成 |

## 本轮执行计划（节点 → 验证）

```
P0 基线复验: pytest 全量 + 前端 build + 启动冒烟 → 验证: 命令输出
P1 并行审计（5 子代理）: 后端链路/前端衔接/部署运维/契约数据/安全 → 验证: 发现清单
P2 盲区合成 + 反向批判 → 验证: 盲区清单分级
P3 五道防线工具化（R7-R11）→ 验证: 各脚本可运行且报告落盘
P4 资产沉淀（R12-R16: ADR/黄金范例/目录索引/文档提交）
P5 skill 更新（R1/R2/R6: 校验清单+防线+门禁+AI 先读规则）
P6 产品策略（R17）
P7 独立审查（六维）→ 修复 → 复验循环
P8 HTML 报告（R4）+ workflow_status 收尾 + git 提交
```

## 第七轮执行日志（边做边记）

### 基线复验（P0 完成）
- 后端：182 passed / 0 failed（30 live 排除），与第六轮一致 ✅
- 前端：npm run build 成功，10 路由静态导出 ✅

### 五道防线工具化（P3 完成，全部实测）
| 防线 | 脚本 | 结果 |
|------|------|------|
| 契约守卫 | scripts/contract_guard.py | 首跑抓 1 断链 → 修复后 0 断链 0 漂移 |
| SQL 安全 | scripts/sql_audit.py | P0=0 P1=0，ORM 全参数化，多 worker 守卫就位 |
| 慢查询 | scripts/slow_query_report.py | logs.jsonl 全量读为最大热点（P1 登记 v2.1 切分），DB 索引已就位 |
| 变异探针 | scripts/mutation_probe.py | 3 变异点，首轮 1 逃逸（熔断默认阈值）→ 补回归测试 → 3/3 抓住 |
| 极限施压 | scripts/stress_test.py | 6/6 PASS（突刺 130req/s 零错误、RSS +8.6MB、慢注入真实命中、并发写零损坏） |
| 一键执行 | scripts/run_all_guards.py | 五道全绿 25.5s |

### 第七轮真实发现与修复（截至当前）
| 问题 | 级别 | 根因 | 修复 | 证据 |
|------|------|------|------|------|
| 前端断链假功能：settings 代理卡片"保存"调 POST /api/proxy 后端从未注册 | P1（未遂） | proxy-settings.tsx 孤儿组件残留（页面实际挂 proxy-settings-card.tsx）+ api.ts 残留 fetchProxy/updateProxy | 删孤儿组件 + 删 api.ts 断链函数 + 注释说明真实链路 | tsc 0 错误；contract_guard 断链 1→0 |
| 熔断默认阈值 5 变异逃逸 | P1 | 全部熔断测试用自定义阈值(3)，默认值无人看守 | test_circuit_breaker.py 补 2 条默认阈值回归 | mutation_probe 3/3 caught |
| 慢存储注入首版假阳性 | 工具自身 bug | 注入点在启动期一次加载，请求路径不经过 | 注入点改 log_service 真实读取通道 + 命中计数证明 | 报告含"命中 33 次"实测 |

### 资产沉淀（P4/P6 完成）
- docs/golden-examples.md：8 个黄金范例 + 反例速查（符号引用已验证）
- docs/product-strategy.md：产品总监视角分析；最大缺口=主动告警 webhook（P2 建议）；SaaS 化明确不建议
- docs/adr/index.md：已存在（ADR-001~004），待审计代理考古结果扩充
- docs/onboarding/README.md：版本引用修正（1.9.0+→2.0.0，N17→N28，补五道防线引用）

### skill 更新（R1/R2/R6 完成）
.claude/skills/chatgpt2api-workflow/SKILL.md 注入：AI 会话启动协议（先读→判过时→再编码）、终局交付门禁 8 项、Reviewer 门禁（有罪推定/分级/复验循环）、六视角盲区扫描、五道防线规程、Web 性能快查（addyosmani 精神适配）、Session 池 key 修正、历史 bug 表 +4 条新教训

## 独立审查循环记录（第七轮）

### 六路审计代理回报（全部收到并合成）
1. **audit-backend**：P0=2（Session 串扰 B1 / 弱密钥入库 S-a）+ P1=11 + 安全 13 项 + 存储 6 项
2. **audit-frontend**：HIGH=4（无确认 F1 / SSE localStorage F2 / 死文件 F3 / 假进度条#2）+ 契约盲区 C1-C12
3. **audit-deploy**：P0=3（deployment 3000 端口 / 上游仓库地址 / config.json 入库悖论）+ P1=8
4. **audit-blindspot**：覆盖率 46% + 假测试 7 项 + 变异 3/3 caught + 盲区 16 项
5. **audit-assets**：ADR 素材 13 项 + 目录熵 9 项 + onboarding 验真（3 篇需修）
6. **audit-product**：产品策略修正 5 处（已落盘 docs/product-strategy.md）

### 第七轮已修复（按级别）

| # | 级别 | 问题 | 修复 | 证据 |
|---|------|------|------|------|
| 1 | P0 | Session 池化串扰：Authorization 被后构造实例覆盖串号（实证复现：b1 带 B token） | 池 key 加 fp 标识 + Authorization 改请求级 + 版本头实例级 + fp 从 token 确定性派生 | 实证：不同 token 不同 Session、池上无 Authorization、同 token 复用；test_session_pool +1 测试；194 全绿 |
| 2 | P0 | resume_poll 调用即 TypeError（proxy_url 形参不存在，六轮零测试放过） | 改 OpenAIBackendAPI() 无参构造（代理经 session_pool 生效） | 实证：旧调用 TypeError 复现、新构造 OK；194 全绿 |
| 3 | P0 | bat/Docker 绕过 main.py 守卫（workers/multiproc 静默无效） | main.py 守卫模块级化（uvicorn CLI 同样经过）；bat/Dockerfile CMD 切到 main.py；CHATGPT2API_PORT 保留 | test_startup_guard.py 2 测试；bat 编码验证（GBK+CRLF 无 BOM） |
| 4 | P0 | JSON 存储非原子写（半写截断丢全部账号）+ 损坏静默吞（监控全绿丢账号） | _atomic_write_text（唯一 tmp+replace+Win 瞬态锁重试）；损坏抛 ValueError；health_check 解析校验 | test_json_storage_safety.py 8 测试全绿；并发写 120 次零 PermissionError |
| 5 | P0 | config.json 含弱密钥且被 git 跟踪（文档/.gitignore/黑名单三方打架） | 登记待用户决策（git rm --cached + config.example.json 化涉及数据迁移，不单方面动） | 弱口令检测已在 production 拒绝启动 |
| 6 | P1 | SSE 从 localStorage 读 token（恒 null，流通道静默失效） | 改 getStoredAuthKey()（localforage/IndexedDB）+ onerror 关连接 + cancelled 守卫 | tsc 0 错误 |
| 7 | P1 | accounts 页三个破坏性操作无二次确认（删除/驱逐/清理异常） | 统一 ConfirmAction Dialog（与 image-manager/logs 模式对齐） | tsc 0 错误 |
| 8 | P1 | 假进度条（150ms 机械 +1 + 2s 固定兜底，不反映后端状态） | 改完成态直显（relogin 服务端已同步完成） | tsc 0 错误 |
| 9 | P1 | 死文件 3 个（proxy-settings.tsx/proxy-settings-card.tsx/base-url-card.tsx 零 import） | 全部删除 + api.ts 断链函数（fetchProxy/updateProxy）清除 | contract_guard 断链 1→0；tsc 0 错误 |
| 10 | P1 | 假测试 4 项（pass/assertTrue(True)/path 非 None/print 不 fail） | 改真实行为断言（429/401/裸 except 为零） | test_security 9 测试全绿 |
| 11 | P1 | deployment.md 端口 3000/上游仓库地址/bun | 全部修正为 23456/内部仓/npm | grep 0 命中 |
| 12 | P1 | onboarding 验收清单 /metrics 无鉴权 curl（必然 401） | 加 ?token= 参数 + 说明 401 是正确行为 | 03-setup.md |
| 13 | P1 | docs 日志路径 data/logs/（实际 logs.jsonl 单文件） | 04/05 两篇修正 | — |
| 14 | P1 | config._save / image_tags / log delete+cleanup 非原子写/无锁 | 全部接 _atomic_write_text + log 加进程内互斥锁 | 194 全绿 |
| 15 | P2 | 熔断默认阈值 5 变异逃逸（测试全用自定义阈值） | test_circuit_breaker 补 2 条默认阈值回归 | mutation_probe 3/3 caught |
| 16 | P2 | examples.md 响应头大小写与 HTTP/2 实际不符 | 改小写 x-request-id/x-response-time-ms | — |
| 17 | P2 | README/onboarding sqlite URL 3 斜杠（SQLAlchemy 绝对路径须 4） | 全部改 4 斜杠 | grep 0 命中 |
| 18 | P2 | onboarding 模块计数错误（services 24→25/protocol 11→12/web 217→77）+ passphrase 表述 + 版本引用过时 | 全部修正 | — |
| 19 | P2 | as any 绕过（Account.created_at 类型缺失） | api.ts 补类型声明，消灭 as any | tsc 0 错误 |

### 第七轮登记待办（未修，明确边界）

| # | 级别 | 问题 | 阻塞/边界 |
|---|------|------|----------|
| D1 | P0 | config.json 含弱密钥且 git 跟踪 | 需用户决策：git rm --cached + config.example.json 化会动 git 历史与现有部署的数据流，不单方面执行 |
| D2 | P1 | SSRF（image_inputs URL 抓取无内网校验） | 需设计协议白名单+IP 段校验，涉及功能面（用户可能 legit 抓内网图床），登记 v2.1 |
| D3 | P1 | XFF 伪造绕过按 IP 限流 | 需 trusted_proxy 配置设计（部署形态相关），登记 v2.1 |
| D4 | P1 | 熔断器注册表孤儿化（remove 零调用） | 账号删除/轮换路径接入清理，登记 v2.1 |
| D5 | P1 | ~~进度字典无界增长~~ | ✅ **已闭环（阶段 2，2026-08-02）**：`_prune_progress_dict` monotonic 惰性淘汰（refresh/relogin 双字典），TTL 默认 3600s 可配置（`progress_ttl_seconds`），配置 6 步全接入，10 个 TTL 专项测试全绿，五道防线 5/5 PASS |
| D6 | P1 | codex 裸 urllib 绕过代理/池/熔断/指标 | 改 curl_cffi 池化，涉及逆向协议验证，登记 v2.1 |
| D7 | P1 | 搜索路径无熔断+backend 泄漏 | 接熔断+补 close，登记 v2.1 |
| D8 | P1 | ~~SQLite 无 WAL/busy_timeout~~ | ✅ **已闭环（阶段 1，2026-08-02）**：WAL+busy_timeout+synchronous=NORMAL 落地，配置 6 步全接入，stress_test SQLite 并发写用例 PASS，五道防线 5/5 PASS |
| D9 | P1 | 备份失败完全静默 | 接日志/看板指示，登记 v2.1（产品策略已列告警为最高价值项） |
| D10 | P1 | /files/{path} 下载无鉴权 | 挂 require_identity+归属校验，登记 v2.1 |
| D11 | P1 | 备份端点 key 白名单 | 接 _is_backup_object，登记 v2.1 |
| D12 | P2 | 账号导出时区 UTC+8 硬编码 + 测试时区污染 | 改 UTC ISO8601 + 测试断言同步（breaking 导出格式），登记 v2.1 |
| D13 | P2 | 覆盖率 46%（openai_backend_api 27%/image_service 15% 等） | 系统性补测工程，登记 v2.1 分批 |
| D14 | P2 | live-only 6 条核心链路无离线等价物 | mock 化离线重放（chat_completion_cache 已有范式），登记 v2.1 |
| D15 | P2 | 优雅停机（SIGTERM 处理 + close_all 零调用） | 接 lifespan 钩子，登记 v2.1 |
| D16 | P2 | 多 worker 状态分裂（chat_completion_cache/SSE 聚合/熔断稀释） | S1 Redis 已登记，本批为补充场景，同 v2.1 |
| D17 | P2 | 时间体系三套混用（time.time/datetime.now/UTC+8） | 统一 UTC epoch + 展示层转换，登记 v2.1 |
| D18 | P2 | 主动告警 webhook（产品策略最高价值项） | 新功能约 200-300 行（六步配置链路），登记 v2.1 |
| D19 | P3 | docs 归档（deployment/upstream-sse/final-report-v4/重复 workflow_status） | 低风险整理，本轮保留原位（避免链接断） |

## 第七轮独立审查循环（R5 六维验证）

| 阶段 | 结果 |
|------|------|
| review-round7 六维审查 | **Verdict: Approve**——无 Blocking；Required #1（OAuth 池化分池注释/行为不符，登记 v2.1 选 a 方案）、#2（log _auto_cleanup 静默吞错） |
| 主线程预审修复 | bat CHATGPT2API_PORT 导出（审查证实链路闭合）；OAuth 分池合理性（审查实证不串扰） |
| review #2 已修 | log _auto_cleanup 静默吞错 → logging.warning(exc_info)；run_all_guards 硬编码 .venv → sys.executable 回退 |
| 探针自身漏洞修复 | mutation_probe 加 _purge_pyc（变异残留污染 pyc 缓存，曾导致默认值 5 实测为 6） |
| **复验结论** | **194 passed / 0 failed + 五道防线 5/5 PASS + tsc 0 错误 + ruff 本轮改动文件全绿** |

## 当前 git 状态

- 基线提交：a6139c0（v2.0.0 发版收尾）
- 本轮提交：19 修复 + 五道防线 6 脚本 + 3 新测试文件 + ADR-005~013 + 黄金范例 + 产品策略 + skill 更新 + 文档修正 + final-report-v7.html
- 未跟踪提交后清零（CLAUDE.md、docs/onboarding/ 等全部入库；reports/ 已 gitignore）
- remote：无（纯本地，不发 GitHub）
- 测试：194 passed / 0 failed（182→194，+12 新测试；30 live 排除）
- 独立审查：Approve（review-round7）

## 第八轮增量（D8 SQLite WAL + D5 进度 TTL，2026-08-02）

| 阶段 | 结果 |
|------|------|
| 阶段 1 D8 SQLite 可靠性 | ✅ WAL+busy_timeout+synchronous 落地；PRAGMA 经 connect 事件在每连接重放（synchronous 曾被反向批判揪出只在单连接生效，改为监听器）；配置 6 步接入（sqlite_wal_mode/sqlite_busy_timeout_ms） |
| 阶段 2 D5 进度字典 TTL | ✅ `_prune_progress_dict` monotonic 惰性淘汰（init/get 路径）；配置 6 步接入（progress_ttl_seconds）；11 个专项测试 |
| review-round8 六维审查 | **Verdict: Request Changes**——Critical①类属性进度字典×实例TTL跨实例误删（本次放大既有包袱）②monotonic created_at 直出 API 污染契约；Required③prune docstring 不符④postgres no-op 伪测试⑤config/服务层 TTL 语义不一致未文档化 |
| 主线程修复 | ①字典挪为实例属性+跨实例隔离防回归测试 ②`_public_progress` 出口过滤 created_at ③docstring 改"仅 init/get"④伪断言删除改文档化双保险+补 busy_timeout=0 锁冲突测试⑤docstring 注明配置层最小 1s；附加 NaN 守卫+WAL 不联动 synchronous docstring |
| **复验结论** | **Approve（review-round8）**——216 passed / 0 failed + 五道防线 5/5 PASS + tsc 0 错误 + ruff 改动范围全绿 + 前端 build 成功 + web_dist 同步 |
