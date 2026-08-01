---
name: chatgpt2api-workflow
description: ChatGPT2API 项目的完整开发工作流。用于新功能开发、API 接入、配置修改、看板扩展、账号池/代理池/熔断器/可观测性相关改动时，确保架构一致性和生产级质量。
---

# ChatGPT2API 开发工作流

> 在本项目做任何改动前**必须先读本技能**，判断是否过时（对照实际代码），过时则更新本技能，未过时则按本技能编码。

## 何时使用

- 新增 API 接口/路由
- 新增配置项
- 新增前端页面/看板
- 修改账号调度/代理池/熔断器/限流/可观测性
- 修改启动脚本/部署配置

## 项目架构（当前真实状态）

```
chatgpt2api/
├── api/                      # FastAPI 路由层
│   ├── app.py                # 应用入口 + 中间件(Metrics/RateLimit/CORS) + 路由注册
│   ├── ai.py                 # OpenAI 兼容 AI 接口 (/v1/*)
│   ├── accounts.py           # 账号管理 CRUD + 刷新
│   ├── dashboard.py          # 看板 API (scheduler/ops/usage/latency/stream/metrics)
│   ├── image_tasks.py        # 图片任务提交/轮询
│   ├── proxy_pool.py         # 代理池管理 API (proxies/egress-ip/probe-ip)
│   ├── rate_limit.py         # 滑动窗口限流中间件
│   ├── metrics_middleware.py # 请求指标中间件(追踪ID/延迟/inflight)
│   ├── system.py             # 设置/日志/图片/备份
│   └── support.py            # 鉴权/工具函数
├── services/                 # 业务逻辑层
│   ├── account_service.py    # 账号池 + 智能调度(健康档位/调度分) + 熔断器接入
│   ├── circuit_breaker.py    # 上游熔断器状态机
│   ├── session_pool.py       # TLS 连接池复用
│   ├── metrics_service.py    # 指标收集 + Prometheus 导出
│   ├── proxy_pool.py         # 代理池管理(持久化到 data/proxies.json)
│   ├── proxy_service.py      # 代理配置/CF clearance
│   ├── config.py             # 配置加载 + schema 校验
│   ├── log_service.py        # 日志服务(惰性自动清理)
│   └── storage/              # 存储后端 (json/sqlite/postgres/git)
├── web/                      # Next.js 前端 (webpack 构建，中文路径必须 --webpack)
│   └── src/
│       ├── app/              # 页面路由
│       │   ├── dashboard/    # 运维看板 (延迟/使用中账号/延迟分布)
│       │   ├── proxy-pool/   # IP 池管理
│       │   ├── accounts/     # 号池管理
│       │   ├── image/        # 在线画图
│       │   ├── logs/         # 日志管理
│       │   └── settings/     # 系统设置
│       └── lib/api.ts        # API 请求封装 + 类型定义
├── config.json               # 运行时配置 (启动时 schema 校验)
├── main.py                   # 启动入口 (多 worker, JSON 存储自动回退 workers=1)
├── 启动chatgpt2api.bat        # Windows 一键启动 (GBK+CRLF 无 BOM)
└── 停止chatgpt2api.bat        # Windows 停止服务
```

## 核心模块关键逻辑

### 1. 智能调度（services/account_service.py）

- 健康档位：healthy / warm / risky（状态 + 错误率 + 配额 + 近期错误）
- 调度分：基础分 + 配额占比 + 成功加成 - 失败惩罚 - 冷却惩罚
- 选取顺序：优先级 > 档位 > 调度分
- **熔断器接入**：`get_available_access_token` 里，熔断账号跳过；`record_success` **必须在 `_is_image_account_available` 确认后调用**（历史 bug：在返回后立即调用导致误判）

### 2. 熔断器（services/circuit_breaker.py）

- 状态机：CLOSED → OPEN → HALF_OPEN → CLOSED
- 连续失败 5 次熔断，30s 冷却，半开 3 次成功恢复
- 全局注册表 `circuit_breaker_registry` 按 token 管理

### 3. 可观测性（services/metrics_service.py + api/metrics_middleware.py）

- `/metrics` Prometheus 端点（无需鉴权）
- 中间件注入 `X-Request-ID` + `X-Response-Time-Ms`
- `/api/dashboard/latency` 延迟统计（总数/错误率/平均延迟/按路径/在途）
- **注意**：中间件异常路径必须 `status = 500` 默认值，response 存在才注入头（历史 P0 bug）

### 4. SSE 实时推送（api/dashboard.py `/api/dashboard/stream`）

- EventSource 无法传 header，用 `?token=` 查询参数鉴权
- `event_generator` 必须外层 `try/except asyncio.CancelledError` 处理客户端断开（历史 P1 bug）

### 5. TLS 连接池（services/session_pool.py）

- 按 (代理配置, impersonate, verify) 缓存 Session，复用 TCP/TLS 连接
- 5 分钟 TTL，最多 200 个配置，惰性清理

### 6. 代理池（services/proxy_pool.py）

- 持久化到 `data/proxies.json`，重启自动加载
- 三种调度：轮询 / 加权 / 最少连接
- 健康检查 + 自动隔离恢复

## 开发规范

### 新增 API 路由

1. 在 `api/` 下新建文件，实现 `create_router()`
2. 在 `api/app.py` 导入并 `app.include_router()`
3. 鉴权用 `require_identity()` 或 `require_admin()`
4. 同步调用用 `run_in_threadpool` 包装

### 新增配置项（必须 6 步全做，缺一不可）

1. `config.json` 加默认值
2. `services/config.py` 加 `@property` 读取（含环境变量覆盖 `CHATGPT2API_*`）
3. `get()` 方法暴露该配置
4. `_validate_schema` 加类型校验
5. `web/src/lib/api.ts` 的 `SettingsConfig` 加字段
6. `web/src/app/settings/store.ts` 的 `normalizeConfig` 加默认值 + `config-card.tsx` 加 UI

### 新增前端页面

1. `web/src/app/` 创建目录 + `page.tsx`
2. `useAuthGuard()` 钩子鉴权
3. `web/src/components/top-nav.tsx` 加导航项
4. `web/src/lib/api.ts` 加类型和请求函数
5. **构建必须 webpack**：`cd web && npm run build`（package.json 已配 `--webpack`），中文路径 Turbopack 会崩

### 新增后端模块

1. 小文件职责单一（参考 metrics_service/circuit_breaker/session_pool 模式）
2. 线程安全（Lock/RLock）
3. 全局单例放文件末尾
4. 写单元测试到 `test/`

## 验收清单（每次改动后必做）

### 启动验证
- [ ] `uv run python -c "from api.app import create_app; app=create_app()"` 无报错
- [ ] 服务启动后关键 API 返回 200

### 构建验证
- [ ] `cd web && npm run build` 成功（webpack）
- [ ] `rm -rf web_dist && cp -r web/out web_dist`

### 契约验证
- [ ] 后端 API 返回结构与前端类型字段完全对齐（用真实 TestClient 调用对比）
- [ ] TypeScript `npx tsc --noEmit` 0 错误

### 单元测试
- [ ] `uv run pytest test/ -q --ignore=<HTTP集成测试>` 通过
- [ ] 新增逻辑有对应测试

### 代码审查（零容忍）
- [ ] 无 `dir()` 判断局部变量（用默认值 + try/finally）
- [ ] 熔断器 record_success 在可用性确认后调用
- [ ] SSE 有 CancelledError 处理
- [ ] 无未使用导入
- [ ] 异常路径有指标/追踪/日志

## 历史 bug 警示（不可再犯）

| bug | 文件 | 教训 |
|-----|------|------|
| metrics_middleware `dir()` 崩溃 | api/metrics_middleware.py | 永远不要用 `dir()` 判断局部变量，用默认值 + try/finally |
| 熔断器误标成功 | services/account_service.py | record_success 必须在可用性确认后调用 |
| SSE 协程泄漏 | api/dashboard.py | event_generator 必须有 CancelledError 处理 |
| bat 闪退 | 启动chatgpt2api.bat | bat 必须 GBK + CRLF + 无 BOM，不能 UTF-8 |
| Turbopack 中文路径崩 | web/package.json | 中文路径构建必须 `--webpack` |

## 关键文件速查

| 需求 | 文件 |
|------|------|
| 调度 | services/account_service.py |
| 熔断 | services/circuit_breaker.py |
| 连接池 | services/session_pool.py |
| 指标 | services/metrics_service.py + api/metrics_middleware.py |
| 代理池 | services/proxy_pool.py + api/proxy_pool.py |
| 限流 | api/rate_limit.py |
| 配置 | services/config.py |
| 日志 | services/log_service.py |
| 看板 | api/dashboard.py + web/src/app/dashboard/page.tsx |
| IP 池 | web/src/app/proxy-pool/page.tsx |
| API 文档 | docs/api/* |
