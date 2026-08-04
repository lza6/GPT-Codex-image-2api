# ChatGPT2API 项目规格

> 自动生成（2026-08-04 10:08:51 UTC）——由 scripts/refresh_spec.py 保鲜，手动改动会被覆盖。
> 保鲜机制：会话启动前跑 `python scripts/refresh_spec.py`，输出 [REFRESHED] 说明已过期需重读。

## 版本与部署
- 应用版本：`2.1.0`
- 端口：23456（Docker 80 映射）
- 存储后端：json / sqlite / postgres / git（config.storage_backend）
- 部署：Windows bat 一键启动 / Docker Compose（非 root + HEALTHCHECK + 优雅停机）

## 配置项（57 个）

| 配置 | 说明 |
|------|------|
| `accounts_file` |  |
| `ai_review` |  |
| `alert_events` | 启用的告警事件列表。 |
| `alert_webhook_timeout` | 告警 webhook 超时秒数（默认 10）。 |
| `alert_webhook_url` | 告警 webhook URL（默认空 = 关闭）。 |
| `app_version` |  |
| `auth_key` |  |
| `auto_relogin_after_refresh` |  |
| `auto_remove_invalid_accounts` |  |
| `auto_remove_rate_limited_accounts` |  |
| `base_url` |  |
| `cleanup_old_images` |  |
| `cors_origins` |  |
| `default_thinking_effort` |  |
| `default_upstream_model_name` |  |
| `env` | 运行环境（development/production），用于生产安全检查。 |
| `get_backup_settings` |  |
| `get_chat_completion_cache_settings` |  |
| `get_image_storage_settings` |  |
| `get_proxy_runtime_settings` |  |
| `get_proxy_settings` |  |
| `get_public_proxy_runtime_settings` |  |
| `get_storage_backend` | 获取存储后端实例（单例） |
| `global_system_prompt` |  |
| `image_account_concurrency` |  |
| `image_check_before_hit_enabled` | 先check再hit：通过轮询确认 file_ids 存在后再返回，而非仅依赖 SSE 事件。 |
| `image_min_free_mb` | 图片磁盘最小剩余空间阈值（MB），低于此值自动清理最旧图片。 |
| `image_parallel_generation` |  |
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
| `max_request_body_mb_chat` | chat/responses 类请求体上限（MB），超限返回 413。 |
| `max_request_body_mb_image` | 图片编辑类请求体上限（MB，base64 图占体积），超限返回 413。 |
| `proactive_probe_enabled` | 低频主动探活开关（F4/B6，默认关）：周期性 fetch_remote_info 探活全部账号， |
| `proactive_probe_interval_minute` | 主动探活周期分钟数（默认 30，最小 5，防过度消耗配额）。 |
| `progress_ttl_seconds` | 进度记录（刷新/重登）在内存中的存活秒数（默认 3600，配置层最小 1s；亚秒级仅供测试经构造参数传入）。 |
| `rate_limit_per_ip_rpm` | 单 IP 每分钟请求数上限（0 = 不限，默认 0）。 |
| `rate_limit_rpm` | 全局每分钟请求数上限（0 = 不限，默认 0）。 |
| `redis_url` | Redis 共享状态连接串（默认空 = Local 进程内，多 worker 状态分裂可接受时）。 |
| `refresh_account_interval_minute` |  |
| `scheduler_mode` |  |
| `scheduler_priority` |  |
| `sensitive_words` |  |
| `sqlite_busy_timeout_ms` | SQLite 写锁冲突时的等待毫秒数（默认 5000，0 = 立即报错）。 |
| `sqlite_wal_mode` | SQLite WAL 日志模式（多 worker 并发写安全，默认开启）。 |
| `ssrf_allow_private_ips` | SSRF 防护回退：true 时允许抓取内网图片（用户内网图床场景，默认 false 拒绝）。 |
| `storage_backend_type` |  |
| `trusted_proxies` | 可信反向代理 IP 白名单（默认仅回环）；仅这些来源的 XFF 头被信任。 |
| `workers` | uvicorn worker 进程数（高并发时调大，多核利用）。 |

## API 路由（81 个）

- `/api/accounts`
- `/api/accounts/evict_stale`
- `/api/accounts/export`
- `/api/accounts/oauth/finish`
- `/api/accounts/oauth/start`
- `/api/accounts/re-login`
- `/api/accounts/re-login/progress/{progress_id}`
- `/api/accounts/refresh`
- `/api/accounts/refresh/progress/{progress_id}`
- `/api/accounts/update`
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
- `/api/dashboard/circuit_breakers`
- `/api/dashboard/latency`
- `/api/dashboard/metrics_summary`
- `/api/dashboard/ops`
- `/api/dashboard/scheduler`
- `/api/dashboard/stream`
- `/api/dashboard/usage`
- `/api/dashboard/usage-forecast`
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
- `/api/images/storage`
- `/api/images/storage/cleanup-to-target`
- `/api/images/storage/compress`
- `/api/images/tags`
- `/api/images/tags/{tag}`
- `/api/logs`
- `/api/logs/delete`
- `/api/proxies`
- `/api/proxies/egress-ip`
- `/api/proxies/health-check`
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
- `/auth/login`
- `/files/{file_path:path}`
- `/health`
- `/image-thumbnails/{image_path:path}`
- `/images/{image_path:path}`
- `/metrics`
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

## 服务模块（28 个）

| 模块 | 用途 |
|------|------|
| `account_service.py` |  |
| `alert_service.py` | 主动告警 webhook（D18）：熔断/备份失败/账号失效/配额耗尽事件推送到运维通道。 |
| `auth_service.py` |  |
| `backup_service.py` |  |
| `circuit_breaker.py` | 上游调用熔断器：防止上游抖动导致请求排队打到坏账号雪崩。 |
| `config.py` |  |
| `content_filter.py` |  |
| `cpa_service.py` | CLIProxyAPI integration for browsing remote auth files and importing selected tokens. |
| `editable_file_task_service.py` |  |
| `image_service.py` |  |
| `image_storage_service.py` |  |
| `image_tags_service.py` |  |
| `image_task_service.py` |  |
| `log_service.py` |  |
| `metrics_service.py` | 生产级可观测性：Prometheus 指标、请求追踪、延迟统计。 |
| `model_service.py` |  |
| `oauth_login_service.py` | 手动 OAuth 桥服务 |
| `openai_backend_api.py` |  |
| `openai_oauth.py` |  |
| `prometheus_metrics.py` | Prometheus 指标（prometheus-client 库）。 |
| `proxy_pool.py` | 代理池管理器：账号级代理绑定、健康检查、自动切换。 |
| `proxy_service.py` | Global outbound proxy and Cloudflare clearance helpers. |
| `retry_budget.py` | 统一重试预算：收敛散落的上游重试逻辑为显式规则。 |
| `session_pool.py` | 上游 HTTP Session 池：跨请求复用 curl_cffi Session，复用 TCP/TLS 连接。 |
| `shared_state.py` | 多 worker 共享状态抽象层（D16）：Local/Redis 双实现。 |
| `ssrf_guard.py` | SSRF 防护（D2）：image_inputs URL 抓取的协议白名单 + 内网 IP 段校验。 |
| `sub2api_service.py` | Sub2API integration for browsing and importing ChatGPT OAuth accounts from a sub2api admin. |
| `usage_forecast.py` | F2/A2：用量预测——按近期用量趋势线性外推号池配额耗尽时间，提前告警。 |
