# 黄金代码范例（Golden Examples）

> 给新加入者：以下片段是本项目里"值得照抄"的实现。新增同类功能时，**先复制对应范例的结构，再改业务内容**。
> 每条都经过生产验证与多轮审计，位置以 file:line 标注（行号随版本漂移，以符号名为准）。

---

## 1. 上游熔断器状态机 — `services/circuit_breaker.py`

**示范模式**：有限状态机（CLOSED → OPEN → HALF_OPEN → CLOSED）+ 线程安全 + 全局注册表。

**为什么好**：
- 状态流转全部收敛在 `state` property 里，无散落各处的 if-else
- `record_failure` 只认**正向白名单**（`is_upstream_instability_error`：5xx/超时/TLS/连接），
  业务拒绝（moderation 400）不会误熔断——这是红队审查打出来的教训，反例见历史 bug 表
- `CircuitBreakerRegistry` 按 key 管理多实例，配 `remove()` 防内存泄漏

**何时复用**：任何"外部依赖可能抖动、需要快速失败+自动恢复"的调用（新上游、新第三方 API）。

## 2. 统一重试预算 — `services/retry_budget.py`

**示范模式**：把"能不能重试"从"怎么重试"里抽出来，按请求形态分级。

**为什么好**：
- 幂等 GET：指数退避 ≤2 次；流式首字节前：换号 ≤1 次；**流式开始后绝不重试**（会吐出重复/错乱内容）
- `can_retry_stream(emitted, ...)` 一个函数说清边界，调用方不用懂内部规则

**何时复用**：新增任何对上游的 HTTP 调用，先问"它幂等吗、流式吗"，然后选对应预算函数，不要自己写 retry 循环。

## 3. TLS 连接池 — `services/session_pool.py`

**示范模式**：按配置指纹缓存昂贵资源 + TTL 惰性清理 + 池化标记防误拆。

**为什么好**：
- 池 key 含**账号标识**（token 末 8 位）——同代理多账号共享 Session 会互相覆盖
  Authorization 造成串号（第六轮修的 P0），这是"资源池化必须考虑多租户隔离"的教科书案例
- `_chatgpt2api_pooled` 标记让 `close()` 变成 `release()`，不拆连接

**何时复用**：缓存任何"建起来贵、可复用、但有隔离维度"的资源（DB 连接、浏览器实例、WebSocket）。

## 4. 纯 ASGI 安全响应头 — `api/security_headers.py`（⚠️ 该文件已于 v2.3.0 清理死文件时删除，模式仍可参考）

**示范模式**：绕过 BaseHTTPMiddleware，直接操作 ASGI 层。

**为什么好**：BaseHTTPMiddleware 在异常路径（413/流式中断）可能丢响应头；纯 ASGI
中间件对所有响应（含 4xx/5xx/413）都生效。这是"框架抽象漏了边界场景时，下沉一层"的范例。

**何时复用**：需要"无条件对所有响应生效"的逻辑（CORS 细化、缓存头、自定义追踪头）。
（注：当前项目中间件仅剩 X-Request-ID 注入 / CORS / 限流，见 `api/app.py`。）

## 5. 契约探测 — `scripts/contract_probe.py` + `scripts/contract_guard.py`

**示范模式**：用 TestClient 真实调用 + 字段签名快照 diff，把"前后端对不齐"变成可执行的回归。

**为什么好**：第七轮它真实抓到一个断链（前端调 `/api/proxy`，后端从未注册——孤儿组件残留）。
probe 打印结构给人看，guard 做机器 diff 给 CI 用。

**何时复用**：改任何 API 响应字段后跑一次；新增端点后把端点加进 `SNAPSHOT_ENDPOINTS`。

## 6. 惰性自动清理 — `services/log_service.py` (`_auto_cleanup`)

**示范模式**：不设后台线程，在写路径上每 N 次惰性触发维护。

**为什么好**：单文件项目里省掉后台任务的生命周期管理（多 worker 下后台线程是竞态重灾区）；
`每 200 条检查一次、超 5000 裁到 3000` 的阈值设计让维护成本与写入频率自适应。

**何时复用**：任何"会无限增长但不需要实时精确"的资源（缓存、临时文件、历史记录）。

## 7. 结构化日志 + request_id 全链路 — `services/metrics_service.py` (contextvars) + `log_service.py` (`add`)

**示范模式**：contextvars 传递请求级上下文，日志在写入点统一注入。

**为什么好**：中间件生成的 request_id 通过 contextvar 流到日志层，text/json 两种格式
都带上——前端响应头里的 request_id 可以直接在日志里搜到（第七轮前的 P1：日志里搜不到）。

**何时复用**：任何需要"跨层传递但不想改函数签名"的上下文（租户 ID、追踪 ID、实验分桶）。

## 8. 测试环境污染隔离 — `test/conftest.py`

**示范模式**：autouse fixture 固定环境变量，防模块级 `os.environ.setdefault` 污染。

**为什么好**：曾有模块级 `setdefault` 改 auth-key，导致测试执行顺序不同结果不同
（9 failed 的 CI 击穿）。autouse fixture 让每个测试的环境确定。

**何时复用**：任何依赖环境变量的配置系统，测试侧必须有对应隔离 fixture。

---

## 反例速查（不要这么写）

| 反模式 | 出处 | 正确做法 |
|--------|------|---------|
| `dir()` 判断局部变量是否定义 | metrics_middleware 历史 P0 | 默认值 + try/finally |
| `except Exception` 后吞掉不抛出 | 多处历史 P1 | 记录日志/指标后 re-raise 或转契约错误 |
| `os.environ.setdefault` 模块级调用 | 测试环境污染事件 | conftest autouse fixture |
| 池化 key 不含租户/账号标识 | Session 串号 P0 | key 必须含隔离维度 |
| 前端调用未注册的 `/api/*` 路径 | `/api/proxy` 断链 | 改完跑 `contract_guard.py` |
