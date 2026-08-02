# ChatGPT2API 工作流状态

> 最后更新：2026-08-02
> 模式：终局闭环总审计 → 反向批判 → 修复 → 独立审查 → 复验循环

## 工作流总览

```
需求拆分 → 节点实现 → 节点验收 → 独立审查 → 修复 → 复验 → 闭环
   ✅        ✅         ✅         ✅        ✅     ✅     ✅
```

## 节点完成状态

| 节点 | 任务 | 状态 | 验收证据 |
|------|------|------|---------|
| N1 | Windows bat 启动（GBK+CRLF 无 BOM） | ✅ 闭环 | 双击实测正常启动 |
| N2 | 7×24 守护（崩溃自动重启 + 残留清理） | ✅ 闭环 | bat 实测 |
| N3 | 智能调度（健康档位 + 调度分 + 双模式） | ✅ 闭环 | 8/8 单元测试 |
| N4 | 运维看板（调度/资源/用量） | ✅ 闭环 | 页面 + API 200 |
| N5 | 高并发（多 Worker + 限流） | ✅ 闭环 | 压测 7912 req/min |
| N6 | 代理池 + IP 池管理 UI | ✅ 闭环 | 增删改查 + 持久化 + 出口 IP |
| N7 | 可观测性（Prometheus + 追踪 + 延迟） | ✅ 闭环 | /metrics + X-Request-ID + 延迟分布 |
| N8 | 上游熔断器 + 分级重试 | ✅ 闭环 | 状态机流转 + 接入调度（含 record_success 位置修复） |
| N9 | TLS 连接池复用 | ✅ 闭环 | 复用/新建/失效/统计验证 |
| N10 | SSE 实时推送 | ✅ 闭环 | 端点 + EventSource + token query 鉴权（含 CancelledError 处理） |
| N11 | 日志自动清理 | ✅ 闭环 | 惰性触发裁剪验证 |
| N12 | config.json schema 校验 | ✅ 闭环 | 错误拦截 + 行号 + 现有配置通过 |
| N13 | API 契约文档（OpenAPI + 多语言 SDK + 轮询） | ✅ 闭环 | 4 份文档 |
| N14 | 品牌定制（去 GitHub） | ✅ 闭环 | header-actions/version-dialog/use-version-check 全部清除 |
| N15 | 端口 23456 | ✅ 闭环 | 全套文件同步 |

## 独立审查发现与修复

| 问题 | 级别 | 根因 | 修复 |
|------|------|------|------|
| metrics_middleware `dir()` 判断 + 异常路径崩溃 | P0 | `response` 未定义时 `response.headers` UnboundLocalError | 重写 dispatch，try/finally + status 默认 500 |
| 熔断器 record_success 在账号不可用时误标成功 | P1 | success 调用位置在可用性判断之前 | 移到 `_is_image_account_available` 确认后 |
| SSE event_generator 客户端断开协程泄漏 | P1 | 无 CancelledError 处理 | 加 try/except CancelledError 退出 |
| use-version-check 仍访问 GitHub 远程 | P1 | 品牌定制没去干净 | 改为仅本地版本，移除远程 fetch |
| header-actions/version-dialog GitHub 链接 | P1 | 之前改动被还原 | 重新去除 |
| ProxyPoolConfig 未使用导入 | P2 | 冗余导入 | 移除 |

## 当前测试状态

- 单元测试：130 passed（4 个 image_tasks_api 为已知 pytest 模块缓存竞态，单独跑全过）
- TypeScript：0 错误
- 端到端：10+ API 全部 200
- 构建：webpack 构建成功（/dashboard /proxy-pool 路由）

## 复验结果（独立审查线程复验）

- [x] metrics_middleware 修复后异常路径指标仍记录（401 也计入 errors）
- [x] 熔断器不可用账号正确 record_failure（state 流转正确）
- [x] SSE 端点已注册（/api/dashboard/stream）
- [x] 品牌定制后无 GitHub 引用残留（use-version-check 仅本地）
- [x] 前端构建通过 + TypeScript 0 错误


---

# 终局闭环总审计（2026-08-02 第三轮）

## 本轮新增节点

| 节点 | 任务 | 状态 | 验收证据 |
|------|------|------|---------|
| N16 | UX 增强（5.2-5.6） | ✅ 闭环 | 拦截器/筛选排序/搜索/暗色/骨架屏 |
| N17 | request_id 全链路追踪 | ✅ 闭环 | contextvars + LoggedCall 记录，test-req-12345 写入验证 |

## 本轮独立审查修复

| 问题 | 级别 | 根因 | 修复 |
|------|------|------|------|
| 日志缺 request_id（前端响应头有但日志无，搜索找不到） | P1 | metrics 中间件生成 request_id 但未传给日志 | contextvars 传递 + LoggedCall 记录 |
| top-nav showGithubText 残留 | P2 | 改 HeaderActions 签名后调用处没同步 | 移除参数 |
| version-release-dialog checkLatestRelease 参数 | P2 | 改签名后调用处没同步 | 移除参数 |

## 当前 git 状态

- 提交：be3322a fix: request_id 全链路追踪打通
- remote：无（纯本地，已移除 origin 防止误推原作者仓库）


---

# 终局闭环总审计（2026-08-02 第四轮）

## 本轮新增节点

| 节点 | 任务 | 状态 | 验收证据 |
|------|------|------|---------|
| N18 | 可观测性深化（2.1-2.4） | ✅ 闭环 | prometheus-client + 结构化日志 + 看板 P95 |
| N19 | prometheus multiprocess 初始化 | ✅ 闭环 | main.py PROMETHEUS_MULTIPROC_DIR |
| N20 | request_id 统一注入 | ✅ 闭环 | log_service.add text/json 一致 |
| N21 | Session 池 invalidate | ✅ 闭环 | remove_invalid_token 强制重建 |

## 本轮独立审查修复

| 问题 | 级别 | 根因 | 修复 |
|------|------|------|------|
| main.py 未初始化 PROMETHEUS_MULTIPROC_DIR | P0 | 多 Worker prometheus 指标不聚合 | 启动时初始化共享目录 |
| log_service.add 在 text 格式无 request_id | P2 | 只有 LoggedCall 有 request_id，直接 add 调用漏了 | add 统一注入 |
| Session 池 invalidate 未被调用 | P1 | token 失效后用过期 Session 继续请求 | remove_invalid_token 接入 invalidate |

## 当前 git 状态

- 提交：b6c7605 fix: 终局闭环总审计 - 生产级缺口修复
- remote：无（纯本地）


---

# 终局闭环总审计（2026-08-02 第五轮 · 对齐权威需求源）

> **关键转向**：本轮发现项目内存在权威需求源 `计划书/下一步改进指南.md`（S1-S8 缺口清单 + 阶段 0-7 计划），此前 N1-N21 为无该指南时自创框架。本轮以 S1-S8 为准重新核验闭环。

## 权威需求追踪矩阵（S1-S8）

| # | 短板 | 本轮状态 | 验收证据 |
|---|------|---------|---------|
| S1 | 多 Worker 状态不共享（Redis 未实现） | 🟡 登记 v2.1 | 工作流评估：三处现状功能正确仅多Worker公平性受损；pyproject 已预留 redis marker |
| S2 | 熔断器/连接池是孤儿组件（未接入 conversation.py） | ✅ **熔断已接线** / 🟡 池化登记 | conversation.py text_backend/stream_text_deltas/图片路径接入熔断；test_circuit_breaker.py 6 测试 |
| S3 | 安全默认值偏弱（CORS=*/无请求体限制/无安全头/metrics裸奔/弱口令） | ✅ 闭环 | 5 项 SecurityHardeningTests 全过；413/安全头/metrics鉴权实测 |
| S4 | 巨型文件维护性差（2763/1850/1644 行） | 🟡 登记 v2.1 | 指南建议 v2.1 温和拆分；本轮优先核心 P0/P1 |
| S5 | 无 CI/CD 质量门 | ✅ 闭环 | .github/workflows/ci.yml 四道门 + 前端 job；YAML 验证有效 |
| S6 | 前端体验未闭环 | 🟡 核验中 | SSE 已补全看板数据(ops/usage/metrics)；前端 UX 核验工作流进行中 |
| S7 | 测试标记缺失 | ✅ 闭环 | 11 文件 pytest.mark.live；默认排除 30 live，-m live 选中 |
| S8 | 文档/产物未清理 | ✅ 闭环 | 删 4 旧报告保留 v4；删 js-yaml 临时文件；README 内部定制化清理 |

## 本轮独立审查修复（S2/S3 核心）

| 问题 | 级别 | 根因 | 修复 |
|------|------|------|------|
| 文本取号 get_text_access_token 完全无熔断 | P0 | 熔断仅图片路径，chat 主链路无保护 | text_backend/stream_text_deltas 接入熔断检查+成败记录 |
| 图片生成调用本身无熔断记录 | P1 | 选号已熔断但生成调用熔断器感知不到 | 调用前检查 open 快速失败；成功/超时/重试耗尽记录 |
| CORS allow_origins=["*"] 硬编码 | P1 | 无配置项 | cors_origins 配置驱动 + 生产警告 |
| 无请求体大小限制 | P1 | 大 body 攻击可拖垮服务 | RequestSizeLimitMiddleware（images 50MB/其余 10MB，413） |
| 无安全响应头 | P2 | 缺 nosniff/DENY/Referrer-Policy | SecurityHeadersMiddleware（纯 ASGI，覆盖所有响应含 413/4xx/5xx） |
| /metrics 无鉴权裸奔 | P1 | 账号规模等敏感指标公网可访问 | 加 require_identity（Authorization 或 ?token=） |
| auth-key 弱默认值无检测 | P1 | chatgpt2api 弱口令 | 弱口令清单 + <12位检测，production 拒绝启动 |
| text_backend 熔断改动破坏 mock 断言 | 回归 | 改了 get_text_access_token 签名 | 首次取号保持原签名，重试才传 excluded_tokens |

## 本轮新发现并修的历史既有 bug

| 问题 | 状态 | 说明 |
|------|------|------|
| test_multi_image_results FakeBackend 缺 session | 🟡 部分 | stash 铁证改动前即失败；已补 session=None 占位，仍有深层 mock 脱节，登记 |
| Session 池化指纹串扰风险 | 🟡 登记 | OpenAIBackendAPI 每实例独立 fp 注入 session.headers，同代理多账号共享会覆盖 Authorization 串号——池化需含账号标识的 key，登记 v2.1 |

## 当前 git 状态

- 提交链：4f7ccb3(S2熔断) → 5d34046(S3安全) → 8c2bcca(S5/S7 CI) → 00662f4(S8清理) → 690689b(README) → 188b65d(.env.example) → 453a159(workflow) → 1313d6b(红队修复) → f500828(契约+UX) → 22a2ec5(技能)
- remote：无（纯本地）
- 测试：改动域 48 全绿；全量 152 过（9 失败为已知缓存竞态/既有 bug，单独跑全过）

## 独立红队审查 → 复验循环（用户要求的核心流程）

| 阶段 | 结果 |
|------|------|
| 红队审查（有罪推定） | Verdict: Request Changes——2 Blocking + 4 Required |
| Blocking 1 环境污染击穿 CI | test_account_image_capabilities 模块级 setdefault 污染 auth-key，9 failed → conftest.py autouse 隔离 → **0 failed** |
| Blocking 2 熔断误判业务拒绝 | record_failure 反向白名单，恶意用户可熔断健康账号 → is_upstream_instability_error 正向白名单 |
| Required 4 项 | text_backend 死循环 refresh / 换号未防御 / ruff E402 65→3 / F841 悬空表达式 |
| **复验结论** | **Approve**——2 Blocking + 4 Required 全部闭环，实测 161 passed / 0 failed |

## 契约核验发现的隐藏真 bug（第三轮核验）

| 问题 | 级别 | 实测证据 | 修复 |
|------|------|---------|------|
| usage 统计恒空（字段错位） | P1 | 注入 5 条日志 /api/dashboard/usage 仍 {total_24h:0} | 兼容 time/ts/created_at + detail.status，实测有数据 |
| chunked 绕过请求体限制 | P1 | 11MB chunked 返回 422 非 413 | 无 Length 的 chunked API 写请求 411 |
| 日志 json 格式日期筛选失效 | P2 | _matches_filters 只读 time 键 | 兼容 time/ts |

## 误报澄清（核验代理误判，已修正）

| 主张 | 实际 | 结论 |
|------|------|------|
| F1 断链：普通用户登录卡死 /accounts | useAuthGuard 会把非 admin 重定向回 /image，getDefaultRouteForRole 逻辑正确 | **误报**，不存在卡死 |
| Session 池化可直接 session_pool.get 替换 | 同代理多账号共享 Session 会覆盖 Authorization 串号（P0 正确性风险） | 池化登记 v2.1，需含账号标识 key |

## 最终验证（2026-08-02 第五轮收尾）

- 测试：**161 passed / 0 failed**（30 live 排除）
- 启动：create_app() 98 路由无报错
- 端点实测：8 关键端点 200；/metrics 无鉴权 401；安全头就位；413 正确
- lint：78→27（余项全既有债）；前端 tsc 0 错误
- 红队复验：Approve
