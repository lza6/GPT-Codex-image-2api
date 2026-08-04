# ChatGPT2API 工作流状态 — 第十一轮（onboarding 初级版落地 + 文档漂移全量修复）

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
| E | config.py 误导 docstring 修正（"超限返回 413"→死配置标注） | ✅ | services/config.py:571,582 |
| F | project-spec 经 refresh_spec.py 重新保鲜 | ✅ | docs/project-spec.md（413 描述已去除，与 config.py docstring 同步） |
| G | 验证全绿 | ✅ | pytest **308 passed / 0 failed / 30 deselected**（19s）；create_app OK v2.3.0 |

## 文档漂移修复明细（文档与真实代码不一致，本轮逐一核实修正）

| 文档 | 原过时内容 | 核实后的真实状态 |
|------|-----------|-----------------|
| 01-architecture.md | mermaid 中间件"Metrics → CORS → 请求大小 → 限流 → 安全头" | 仅 X-Request-ID 注入 / CORS / 限流(默认关)（api/app.py） |
| 01-architecture.md | 安全表"请求大小 → api/request_size_limit.py" | 文件已删；`max_request_body_mb_*` 为死配置（config 仍读取但无消费） |
| 01-architecture.md | 安全表"安全头 → api/security_headers.py" | 文件已删（内网自用，安全由调用方处理） |
| 01-architecture.md | 安全表无 SSRF 行 | 补：SSRF 校验保留在图片抓取路径（ssrf_guard.py ← image_inputs.py:261） |
| 03-setup.md | max_request_body_mb_* 环境变量"请求体上限（MB）" | 标注历史遗留死配置 |
| README.md | "移除 RateLimitMiddleware/.../SSRF 防护" | 限流已在 v2.3.0 重新接线（S-R15）；SSRF 校验保留 |
| README.md | "限流在 v2.3.1 已重新接线" | 版本号实为 **v2.3.0**（无 v2.3.1） |
| golden-examples.md | 引用已删文件 `api/security_headers.py` | 加"文件已删，模式仍可参考 + 当前中间件清单"注记 |
| SKILL.md | "已移除 RateLimitMiddleware/.../SSRF 防护" | 限流已接线、SSRF 仍在；已移除的仅 SecurityHeaders/RequestSizeLimit/MetricsMiddleware |

## 五道防线状态

| 批次 | 契约守卫 | SQL | 慢查询 | 变异 | 施压 |
|------|---------|-----|--------|------|------|
| 第十一轮 | ✅ | ✅ | ✅ | ✅ | ✅ |

> 本轮改动为纯文档 + 2 处 docstring（零行为变化），五道防线全绿无影响。防线输出：`reports/`

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
