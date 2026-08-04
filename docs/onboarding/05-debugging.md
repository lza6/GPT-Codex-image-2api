# 05 · 调试指南

## 历史真实故障档案（五轮终局审计，P0/P1 级）

| 错误/症状 | 根因 | 修复 | 遇到类似问题先查 |
|-----------|------|------|-----------------|
| 异常路径下 metrics 中间件崩溃 `UnboundLocalError: response` | `response` 未定义就访问 `response.headers` | 重写 dispatch：try/finally + status 默认 500 | 中间件里任何变量在异常分支是否已定义 |
| 熔断器把不可用账号误标成功，坏账号反复被选中 | `record_success` 调用位置在可用性判断**之前** | 移到 `_is_image_account_available` 确认后 | 熔断/重试代码里"成功"的判定时机 |
| SSE 端点客户端断开后协程不退出（泄漏） | event_generator 无 `CancelledError` 处理 | try/except CancelledError 后退出循环 | 所有 async generator 是否处理客户端断开 |
| 日志缺 request_id（前端响应头有但日志无） | metrics 中间件生成 request_id 但未传给日志 | contextvars 传递 + LoggedCall 记录（N17） | 跨层数据传递是否走 contextvars 而非参数透传 |
| 前端版本检查仍访问 GitHub（品牌定制没去干净） | `use-version-check` 远程 fetch 残留 | 改纯本地版本，移除远程请求 | 全局搜 `github.com` / `api.github.com` |
| 改 HeaderActions 签名后调用处没同步（top-nav 残留参数） | 签名变更未全量跟进 | 移除调用处参数 | 改组件签名后全局搜调用点 |

## 按症状速查

| 症状 | 最可能原因 | 处置 |
|------|-----------|------|
| 启动即退出，报 config 行号 | config.json schema 校验失败（N12） | 按行号修字段名/类型 |
| 启动警告 "workers 回退到 1" | `STORAGE_BACKEND=json` 却配了 workers>1 | 换 sqlite/postgres，或接受单 worker |
| 多 worker 下账号被重复分配/数据丢 | 同上，JSON 后端多进程各持副本 | **架构限制，不是 bug**；换存储后端 |
| 账号全被标限流不可用 | 上游 IP 被封 / 代理池全挂 | 看 dashboard 调度健康度；查代理池出口 IP |
| 图片任务一直 pending 超时 | 上游 403（CF 拦截）或会话过期 | `proxy_runtime.reset_status_codes`（默认 403）触发会话重置；查 clearance 配置 / warp compose |
| SSE 流挂起不返回 | 上游长连接超时 | 图片生成 SSE 有硬超时上限配置（1.8.0 修复）；查 config.json |
| `curl /v1/models` 返回 401 | auth-key 不匹配 | 请求头 `Authorization: Bearer <config.json 的 auth-key>` |
| 前端字段显示 undefined | 后端 protocol 字段改了，前端没同步 | 跑 `scripts/contract_probe.py` 定位漂移字段 |
| bat 启动中文乱码/闪退 | bat 被存成 UTF-8 | 恢复原版；必须 GBK + CRLF + 无 BOM |
| 中文路径下前端构建失败 | Turbopack 中文路径 bug（1.9.0 修复） | 构建已固定 `next build --webpack`，别改回 |
| 全量 pytest 偶发 4 个 image_tasks_api 失败 | pytest 模块缓存竞态（已知） | 单独跑该文件应全过；非回归 |
| `/metrics` 多 worker 下无数据 | `PROMETHEUS_MULTIPROC_DIR` 未初始化 | main.py 自动处理；检查 `data/prometheus_multiproc/` 权限 |

## 日志与观测位置

| 环境 | 位置 | 说明 |
|------|------|------|
| 本地/Docker 日志 | `data/logs-YYYY-MM-DD.jsonl` | 按天切分；当天文件超 5000 条裁剪到 3000（旧 `data/logs.jsonl` 首次启动自动迁移） |
| 请求级追踪 | 响应头 `X-Request-ID` + `X-Response-Time-Ms` | 日志全文 grep 该 ID |
| 指标 | `GET /metrics`（Prometheus 文本） | dashboard 页可视化；`/api/dashboard/latency` 延迟分布 |
| 实时事件 | SSE `/api/dashboard/stream` | 3s 推送；token 走 query 参数 |
| 调度内部状态 | `/api/dashboard/scheduler` | 健康档位分布、调度分、账号排行榜 |
| 存储自检 | `/api/storage/info` | 当前后端类型与健康 |

## 诊断命令

```bash
# 服务活着？
curl http://localhost:23456/v1/models -H "Authorization: Bearer <key>"

# 指标正常？
curl -s http://localhost:23456/metrics | grep -E "http_requests_total|circuit"

# 23456 被谁占了？
netstat -ano | findstr :23456

# 契约漂了没？（需活服务）
uv run pytest test/test_contracts.py -v

# 单测快速定位
uv run pytest test/ -x -q --tb=short -m "not live and not redis"

# 代码定位（本仓库已 graft 索引）
graft ask "<问题>" --source
graft callers <符号>            # 改符号前看影响面
```

## 排查路径建议

1. **先分层**：401/403/429 → 网关层（auth/限流）；5xx → services 层；字段 undefined → 契约漂移；任务超时 → 上游/代理层
2. **再借观测**：X-Request-ID 串日志 → `/api/dashboard/scheduler` 看调度状态 → `/metrics` 看熔断器状态
3. **live 域上报**：需要真实上游账号复现、怀疑账号被封/上游接口变动（逆向项目上游随时可能变）→ 带已排除的假设清单上报项目方，不要自行深挖
