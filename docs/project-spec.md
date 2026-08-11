# ChatGPT2API 项目规格

> 自动生成（2026-08-11 19:47:45 UTC）——由 scripts/refresh_spec.py 保鲜，手动改动会被覆盖。
> 保鲜机制：会话启动前跑 `python scripts/refresh_spec.py`，输出 [REFRESHED] 说明已过期需重读。

## 版本与部署
- 应用版本：`2.33.0`
- 端口：23456（Docker 80 映射）
- 存储后端：json / sqlite / postgres / git（config.storage_backend）
- 部署：Windows bat 一键启动 / Docker Compose（非 root + HEALTHCHECK + 优雅停机）

## 配置项（89 个）

| 配置 | 说明 |
|------|------|
| `abnormal_auto_recover_enabled` | v2.9.0：异常账号自动恢复开关（watcher 第二职责）。 |
| `abnormal_auto_recover_interval_minutes` | v2.9.0：异常账号自动恢复扫描间隔（分钟）。 |
| `abnormal_auto_recover_max_workers` | v2.9.0：异常账号自动恢复并发数上限。 |
| `account_warmup_enabled` | 新账号预热开关（默认开启）。 |
| `account_warmup_timeout_secs` | 账号预热超时秒数（默认 60）。 |
| `accounts_file` |  |
| `ai_review` |  |
| `alert_events` | 启用的告警事件列表。 |
| `alert_webhook_timeout` | 告警 webhook 超时秒数（默认 10）。 |
| `alert_webhook_url` | 告警 webhook URL（默认空 = 关闭）。 |
| `app_version` |  |
| `audit_retention_days` |  |
| `auth_key` | 高频读取（每个请求鉴权），用 cached_property 缓存。 |
| `auto_diagnose_interval_minutes` | 自动诊断间隔分钟数（默认 60）。 |
| `auto_heal_enabled` | 自动修复引擎开关（默认开启）。 |
| `auto_relogin_after_refresh` |  |
| `auto_remove_invalid_accounts` |  |
| `auto_remove_rate_limited_accounts` |  |
| `base_url` |  |
| `cf_solver_url` | OTP 登录 CF 清除服务地址（默认 http://127.0.0.1:8001）。 |
| `cleanup_old_images` |  |
| `config_watch_enabled` | 配置热加载开关（默认开启）。 |
| `cors_origins` |  |
| `default_thinking_effort` |  |
| `default_upstream_model_name` |  |
| `env` | 运行环境（development/production），用于生产安全检查。 |
| `get_backup_settings` |  |
| `get_chat_completion_cache_settings` |  |
| `get_image_storage_settings` |  |
| `get_kookeey_settings` | kookeey 动态住宅代理配置（密码登录 / OTP 取件的每号独立出口）。 |
| `get_proxy_runtime_settings` |  |
| `get_proxy_settings` |  |
| `get_public_proxy_runtime_settings` |  |
| `get_quota_management` |  |
| `get_storage_backend` | 获取存储后端实例（单例） |
| `global_system_prompt` |  |
| `image_account_concurrency` |  |
| `image_check_before_hit_enabled` | 先check再hit：通过轮询确认 file_ids 存在后再返回，而非仅依赖 SSE 事件。 |
| `image_min_free_mb` | 图片磁盘最小剩余空间阈值（MB），低于此值自动清理最旧图片。 |
| `image_parallel_generation` |  |
| `image_passthrough_enabled` | 出图直接返回上游签名 URL（服务器不下载/重托管，省服务器上下行流量与带宽压力）。 |
| `image_passthrough_ttl_secs` | 透传直链标注的有效期（秒），过期后直链 410 不可用。 |
| `image_poll_initial_wait_secs` | Image generation upstream takes ~30s; polling immediately wastes requests |
| `image_poll_interval_secs` |  |
| `image_poll_timeout_secs` |  |
| `image_remove_conversation_after_result` | 出图成功后异步隐藏 ChatGPT 本地对话记录。 |
| `image_remove_conversation_always` | 无论是否出图，画图请求结束后都异步隐藏 ChatGPT 本地对话记录。 |
| `image_retention_days` |  |
| `image_settle_enabled` | 图片二次确认机制：找到 file_ids 后等待一段时间再次确认。 |
| `image_settle_secs` | 二次确认等待时间（秒）。 |
| `image_thumbnails_dir` |  |
| `images_dir` |  |
| `log_levels` |  |
| `metrics_sample_rate` | Prometheus 指标采样率（0.0 关闭，1.0 全量采集，默认 1.0）。 |
| `model_upstream_map` |  |
| `openapi_docs_url` |  |
| `openapi_enabled` |  |
| `openapi_openapi_url` |  |
| `openapi_redoc_url` |  |
| `proactive_probe_enabled` | 低频主动探活开关（F4/B6，默认关）：周期性 fetch_remote_info 探活全部账号， |
| `proactive_probe_interval_minute` | 主动探活周期分钟数（默认 30，最小 5，防过度消耗配额）。 |
| `progress_ttl_seconds` | 进度记录（刷新/重登）在内存中的存活秒数（默认 3600，配置层最小 1s；亚秒级仅供测试经构造参数传入）。 |
| `provider_rate_limit_rpm` |  |
| `provider_weights` |  |
| `rate_limit_per_ip_rpm` | 单 IP 每分钟请求数上限（0 = 不限，默认 0）。 |
| `rate_limit_rpm` | 全局每分钟请求数上限（0 = 不限，默认 0）。 |
| `redis_url` | Redis 共享状态连接串（默认空 = Local 进程内，多 worker 状态分裂可接受时）。 |
| `refresh_account_interval_minute` |  |
| `scheduler_adaptive_enabled` | 自适应调度器开关（默认 false）。 |
| `scheduler_adaptive_interval_seconds` | 自适应调度器检查间隔（秒，默认 30，最小 5）。 |
| `scheduler_affinity_ttl_seconds` | Affinity 调度模式：同一模型路由到同一账号的亲和超时（秒，默认 300）。 |
| `scheduler_mode` |  |
| `scheduler_priority` |  |
| `self_heal_auto_replace_enabled` | 自动替换不健康账号开关（默认关闭）。 |
| `self_heal_retry_initial_secs` | 自愈指数退避初始延迟（秒，默认 60）。 |
| `self_heal_retry_max_attempts` | 自愈指数退避最大重试次数（默认 5）。 |
| `self_heal_retry_max_secs` | 自愈指数退避最大延迟（秒，默认 3600）。 |
| `sensitive_words` |  |
| `session_pool_health_check_enabled` | 连接池健康预检开关（默认开启）。 |
| `sqlite_busy_timeout_ms` | SQLite 写锁冲突时的等待毫秒数（默认 5000，0 = 立即报错）。 |
| `sqlite_wal_mode` | SQLite WAL 日志模式（多 worker 并发写安全，默认开启）。 |
| `ssrf_allow_private_ips` | SSRF 防护回退：true 时允许抓取内网图片（用户内网图床场景，默认 false 拒绝）。 |
| `storage_async_enabled` | 异步存储后端开关（默认关闭，启用后数据库操作使用 sqlalchemy.ext.asyncio）。 |
| `storage_backend_type` |  |
| `trace_buffer_size` |  |
| `trace_slow_threshold_ms` |  |
| `trusted_proxies` | 可信反向代理 IP 白名单（默认仅回环）；仅这些来源的 XFF 头被信任。 |
| `upstream_failover_enabled` | 上游 5xx/连接错误时自动切换账号（默认开启）。 |
| `workers` | uvicorn worker 进程数（高并发时调大，多核利用）。 |

## API 路由（129 个）

- `/aggregate`
- `/api/accounts`
- `/api/accounts/batch`
- `/api/accounts/detail`
- `/api/accounts/evict_stale`
- `/api/accounts/export`
- `/api/accounts/export-csv`
- `/api/accounts/groups`
- `/api/accounts/health-scores`
- `/api/accounts/oauth/finish`
- `/api/accounts/oauth/start`
- `/api/accounts/re-login`
- `/api/accounts/re-login/progress/{progress_id}`
- `/api/accounts/recover`
- `/api/accounts/refresh`
- `/api/accounts/refresh/progress/{progress_id}`
- `/api/accounts/tags`
- `/api/accounts/trash`
- `/api/accounts/trash/clear`
- `/api/accounts/trash/restore`
- `/api/accounts/update`
- `/api/audit`
- `/api/audit/export`
- `/api/auth/keys`
- `/api/auth/keys/usage`
- `/api/auth/keys/{key_id}`
- `/api/auth/keys/{key_id}/revoke`
- `/api/auth/users`
- `/api/auth/users/{key_id}`
- `/api/backup/test`
- `/api/backups`
- `/api/backups/delete`
- `/api/backups/detail`
- `/api/backups/download`
- `/api/backups/run`
- `/api/cpa/pools`
- `/api/cpa/pools/{pool_id}`
- `/api/cpa/pools/{pool_id}/files`
- `/api/cpa/pools/{pool_id}/import`
- `/api/dashboard/adaptive_scheduler`
- `/api/dashboard/capacity`
- `/api/dashboard/circuit_breakers`
- `/api/dashboard/cost`
- `/api/dashboard/events`
- `/api/dashboard/latency`
- `/api/dashboard/metrics_summary`
- `/api/dashboard/ops`
- `/api/dashboard/quota`
- `/api/dashboard/scheduler`
- `/api/dashboard/stream`
- `/api/dashboard/usage`
- `/api/dashboard/usage-forecast`
- `/api/dashboard/usage-totals`
- `/api/events/stream`
- `/api/image-storage/sync`
- `/api/image-storage/test`
- `/api/image-tasks`
- `/api/image-tasks/edits`
- `/api/image-tasks/generations`
- `/api/image-tasks/{task_id}/resume-poll`
- `/api/images`
- `/api/images/delete`
- `/api/images/download`
- `/api/images/download/{image_path:path}`
- `/api/images/proxy-download`
- `/api/images/storage`
- `/api/images/storage/cleanup-to-target`
- `/api/images/storage/compress`
- `/api/images/tags`
- `/api/images/tags/{tag}`
- `/api/kookeey/balance`
- `/api/kookeey/config`
- `/api/kookeey/extract`
- `/api/kookeey/ip-usage`
- `/api/kookeey/probe-ips`
- `/api/kookeey/stats`
- `/api/kookeey/test`
- `/api/kookeey/traffic`
- `/api/kookeey/traffic-detail`
- `/api/logs`
- `/api/logs/delete`
- `/api/providers`
- `/api/proxies`
- `/api/proxies/batch-import`
- `/api/proxies/egress-ip`
- `/api/proxies/health-check`
- `/api/proxies/kookeey-egress`
- `/api/proxies/probe-ip`
- `/api/proxies/strategy`
- `/api/proxies/weight`
- `/api/proxies/{url:path}`
- `/api/proxy/clearance/test`
- `/api/proxy/runtime`
- `/api/proxy/test`
- `/api/settings`
- `/api/storage/info`
- `/api/sub2api/servers`
- `/api/sub2api/servers/{server_id}`
- `/api/sub2api/servers/{server_id}/accounts`
- `/api/sub2api/servers/{server_id}/groups`
- `/api/sub2api/servers/{server_id}/import`
- `/api/system/diagnose`
- `/api/system/healing/clear-history`
- `/api/system/healing/history`
- `/api/system/healing/run`
- `/api/system/health/ready`
- `/api/system/healthz`
- `/api/system/log-level`
- `/auth/login`
- `/export`
- `/files/{file_path:path}`
- `/health`
- `/image-thumbnails/{image_path:path}`
- `/images/{image_path:path}`
- `/metrics`
- `/slow-queries`
- `/stats`
- `/traces`
- `/v1/chat/completions`
- `/v1/editable-file-tasks`
- `/v1/images/edits`
- `/v1/images/generations`
- `/v1/messages`
- `/v1/models`
- `/v1/ppt/generations`
- `/v1/psd/generations`
- `/v1/responses`
- `/v1/search`
- `/version`

## 服务模块（53 个）

| 模块 | 用途 |
|------|------|
| `account_lifetime.py` | 5.1：账号寿命预测——把「已消费的同一批信号」改写成趋势形态，事前预警账号衰亡。 |
| `account_service.py` |  |
| `account_warmup.py` |  |
| `adaptive_scheduler.py` | 自适应调度器：根据运行指标自动切换调度模式。 |
| `alert_service.py` | 主动告警 webhook（D18）：熔断/备份失败/账号失效/配额耗尽事件推送到运维通道。 |
| `audit_service.py` | 3.2 审计日志：管理操作留痕。 |
| `auth_service.py` |  |
| `auto_healer.py` | 自动修复引擎（Auto-Healing 2.0）：扩展自动修复能力，覆盖更多故障场景。 |
| `backup_service.py` |  |
| `circuit_breaker.py` | 上游调用熔断器：防止上游抖动导致请求排队打到坏账号雪崩。 |
| `config.py` |  |
| `config_watcher.py` | 配置热加载器：文件监听 + 增量更新 + 事件通知。 |
| `content_filter.py` |  |
| `cost_service.py` | 5.1.2：成本优化服务——全链路成本追踪与概览。 |
| `cpa_service.py` | CLIProxyAPI integration for browsing remote auth files and importing selected tokens. |
| `diagnostic_engine.py` | 自动诊断引擎：常见问题自动识别 + 修复建议。 |
| `editable_file_task_service.py` |  |
| `event_bus.py` | 轻量级事件总线：解耦模块间直接函数调用。 |
| `event_bus_init.py` | 事件总线订阅注册：集中管理所有事件订阅关系。 |
| `image_failure.py` | 统一图片失败分类（对标上游 v3.0 `image_failure.py` 的主项目裁剪版）。 |
| `image_pipeline.py` |  |
| `image_service.py` |  |
| `image_storage_service.py` |  |
| `image_tags_service.py` |  |
| `image_task_service.py` |  |
| `kookeey_service.py` | kookeey 代理服务集成（v2.9.0）。 |
| `log_index.py` |  |
| `log_service.py` |  |
| `metrics_service.py` | 生产级可观测性：Prometheus 指标、请求追踪、延迟统计。 |
| `model_service.py` |  |
| `oauth_login_service.py` | 手动 OAuth 桥服务 |
| `openai_backend_api.py` |  |
| `openai_oauth.py` |  |
| `otp_login_service.py` | 邮箱验证码登录服务（纯 HTTP 链路 + 微软 Graph 取件(优先)/98faka(兜底) + cf_solver CF 清除）。 |
| `prometheus_metrics.py` | Prometheus 指标（prometheus-client 库）。 |
| `provider_scheduler.py` |  |
| `proxy_pool.py` | 代理池管理器：账号级代理绑定、健康检查、自动切换。 |
| `proxy_service.py` | Global outbound proxy and Cloudflare clearance helpers. |
| `quota_service.py` |  |
| `request_context.py` | 请求级上下文：中间件注入，审计/日志读取。 |
| `retry_budget.py` | 统一重试预算：收敛散落的上游重试逻辑为显式规则。 |
| `router_service.py` | 模型→Provider 路由分发（Phase 3）。 |
| `session_cache.py` | 三级会话缓存：L1 内存 LRU → L2 Redis → L3 存储层。 |
| `session_pool.py` | 上游 HTTP Session 池：跨请求复用 curl_cffi Session，复用 TCP/TLS 连接。 |
| `shared_state.py` | 多 worker 共享状态抽象层（D16）：Local/Redis 双实现。 |
| `ssrf_guard.py` | SSRF 防护（D2）：image_inputs URL 抓取的协议白名单 + 内网 IP 段校验。 |
| `sub2api_service.py` | Sub2API integration for browsing and importing ChatGPT OAuth accounts from a sub2api admin. |
| `task_queue.py` |  |
| `task_queue_init.py` | 任务队列处理器注册。在 app 启动时调用。 |
| `tracing.py` | 6.1-6.3：完整请求追踪系统。 |
| `trash_service.py` | 回收站服务：记录被剔除/删除的账号（含时间、上游返回原因、来源）。 |
| `usage_agg.py` | 3.5.1：日志聚合缓存——替代 /api/dashboard/usage 与 usage_forecast 的全量日志扫描。 |
| `usage_forecast.py` | F2/A2：用量预测——按近期用量趋势线性外推号池配额耗尽时间，提前告警。 |
