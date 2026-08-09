# 常见问题

## 一、运维 FAQ

### Docker 部署

**Q: docker compose up 启动后端口 23456 没反应？**

A: 检查三项：
1. `docker compose ps` 确认容器状态为 `Up`，非 `Exit` 或 `Restarting`
2. 防火墙是否放开 23456；Windows 下 Docker 映射默认走 `0.0.0.0:23456`，若宿主机另有进程占用了该端口，映射会失败
3. `docker logs chatgpt2api` 查看启动日志，确认 schema 校验是否通过

**Q: 容器日志反复 Restarting？**

A: 最常见原因是 `config.json` 配置错误（字段名不对、auth-key 不满足长度要求）。查看日志确认错误信息，修完配置文件后 `docker compose up -d` 重新启动。

**Q: 数据目录（data/）权限问题？**

A: 容器内 uid 为 1000，宿主机 `data/` 目录须可写：
```bash
mkdir -p data
chmod -R 777 data   # 快速解决，生产建议 chown 1000:1000
```
`data/` 存放账号、日志、图片、任务记录等运行时数据，务必保留不被删除。

**Q: 如何升级？**

A: 按顺序执行：
```bash
# 1. 备份
tar -czf backups/chatgpt2api-$(date +%Y%m%d-%H%M%S).tgz config.json .env data

# 2. 拉取新代码和镜像
git pull
docker compose pull   # 或 docker compose -f docker-compose.warp.yml pull

# 3. 重启
docker compose up -d
```

**Q: 怎么回滚到旧版本？**

A:
```bash
git log --oneline -n 20           # 找到要回滚的 commit
git checkout <旧版本commit>
docker compose up -d --build      # 本地构建
```
或直接复用旧镜像 tag。

**Q: WARP/FlareSolverr 部署后上游请求仍然被 CF 拦截？**

A: 检查 FlareSolverr 日志 `docker logs chatgpt2api-flaresolverr` 是否正常。常见问题：
- FlareSolverr 启动慢（首次需要下载 Chrome），等待 2-3 分钟
- WARP 连接失败：检查 `WARP_LICENSE_KEY` 是否有效
- 代理链配置不对：确认 `docker-compose.warp.yml` 中 `init-config` 容器的 `CHATGPT2API_PROXY_RUNTIME_PROXY_URL` 指向正确的代理地址

### 端口冲突

**Q: 端口 23456 被占用？**

A: 先查谁占的：
```bash
netstat -ano | findstr :23456
```
拿到 PID 后：
```bash
taskkill /F /PID <PID>
```
或运行 `停止chatgpt2api.bat`（会自动清理残留进程）。如需改端口，修改 `main.py` 和 `docker-compose*.yml` 并全局同步。

**Q: 本地启动时端口 3000 被占（前端）？**

A: 前端开发服务默认 `0.0.0.0:3000`，可修改 `web/package.json` 的 `dev` 脚本或通过环境变量 `PORT=3001 npm run dev` 指定。

### config.json 与配置

**Q: 启动报 schema 校验错？**

A: 错误信息会带 config.json 行号，按行号修。常见原因：
- 手抖改了字段名（与 `services/config.py` 中的 schema 定义不一致）
- 忘记加 `auth-key` 或长度不足 12 位
- 新增字段但未更新 schema（需要同步改 `services/config.py` 和 `.env.example`）

**Q: 多 Worker 启动警告 "workers 回退到 1"？**

A: `STORAGE_BACKEND=json` 时 `workers>1` 不被允许——多进程各持独立账号副本会导致数据损坏。换 sqlite/postgres 后端或接受单 worker。

**Q: 环境变量和 config.json 同时存在时谁优先？**

A: 环境变量 `CHATGPT2API_*` 覆盖 `config.json` 同名配置。但 `config.json` 中不存在的配置项，环境变量也不生效（schema 校验层决定）。

### 监控与排查

**Q: 怎么看当前请求量？**

A: 访问 `http://localhost:23456/metrics?token=<auth-key>` 获取 Prometheus 格式指标（v2.0.0 起 /metrics 需要鉴权）。

**Q: 日志文件太大怎么办？**

A: 日志已按天轮转切分 `logs-YYYY-MM-DD.jsonl`，不会无限增长。如需清理旧日志：
```bash
rm data/logs-2025-*.jsonl   # 按需调整日期范围
```
注意：用量聚合缓存 `usage_agg` 依赖日志，清理后历史趋势数据会丢失。建议在后台设置页配置 R2 备份后，再清理本地日志。

**Q: 怎么知道哪些账号快死了？**

A: 看控制台 dashboard 的调度排行榜——健康档位会标注 healthy/warm/risky。寿命预测功能会按近期失败率趋势给账号降档预警。如果配置了告警 webhook，账号失效时也会推送通知。

---

## 二、开发 FAQ

### 新增端点

**Q: 我想加一个 API 端点，流程是什么？**

A: 四步走：

1. **加路由**：在 `api/` 下对应 router（`ai.py`/`accounts.py`/`dashboard.py`/`system.py` 等）中新增端点函数，用 `@router.get/post/delete` 声明
2. **加业务逻辑**：在 `services/` 中新增或扩展对应模块
3. **加测试**：在 `test/` 中新增测试文件，按 AAA 模式编写
4. **更新契约文档**：`docs/api/openapi.yaml` + `docs/api/examples.md`，然后跑双验证：
   ```bash
   uv run pytest test/test_contracts.py
   python scripts/contract_probe.py   # 需活服务
   ```

**Q: 新增配置项需要改哪些地方？**

A: 项目有"六步链路"惯例：
1. `config.json` 加默认值
2. `services/config.py` 加 `@property` + getter
3. `services/config.py` 的 schema 校验里加字段定义
4. `.env.example` 加注释
5. `web/src/lib/api.ts` 加类型定义
6. 如果前端设置页需要可视化编辑，同步更新对应的 config-card 组件

**Q: 新增端点后前端怎么调用？**

A: 前端项目在 `web/src/`，按页面组织：
- 调用后端 API 走 `web/src/lib/api.ts` 中的封装函数
- 新增页面需在 `web/src/app/` 下新建目录
- 前后端字段名须与 `services/protocol/` 中的定义一致

### 修改前端

**Q: 前端改了，怎么验证构建？**

A:
```bash
cd web && npm run build
```
构建产物到 `web/out/` + `web_dist/`。注意：Turbopack 在中文路径下会失败，项目已固定用 `next build --webpack`，别改回。

**Q: 前端引入新库要注意什么？**

A: 前端栈已固定：zustand（状态管理）+ Tailwind v4（样式）+ Recharts（图表）。不要引入新的状态管理库或 CSS 框架。shadcn/ui 组件可用，但需要随项目一起维护。

**Q: 改了 API 字段名，前端怎么同步？**

A: 改 API 字段名是高危操作。必须同步：
1. `services/protocol/` 对应模块
2. `web/src/lib/api.ts` 的接口类型
3. `web/src/` 中所有使用该字段的组件
4. `docs/api/openapi.yaml`
5. 跑双验证：`test_contracts.py` + `contract_probe.py`

### 测试模式

**Q: 测试文件怎么分组的？**

A: 测试全在 `test/` 目录，用 pytest 的 `-m` 标记区分：
- `uv run pytest`（默认）：排除 `live` 和 `redis` 标记，不触网，CI 用
- `uv run pytest -m live`：需要真实上游，本地手动运行
- `uv run pytest -m unit`：纯单元测试，无外部依赖
- `uv run pytest test/xxx.py`：单文件调试

不做目录隔离，live 测试与单元测试混放。

**Q: 测试跑不过怎么办？**

A: 先用 `-v` 看详细日志：
```bash
uv run pytest -v test/xxx.py
```
常见原因：
- `image_tasks_api` 全量跑偶发竞态失败，单独跑应全过
- 测试依赖的测试数据被前一个测试改了（检查 fixture 隔离性）
- 环境变量 `CHATGPT2API_AUTH_KEY` 未设置

**Q: 怎么写一个新测试？**

A: 遵循 AAA 模式：
```python
async def test_xxx():
    # Arrange — 准备数据
    # Act — 执行被测逻辑
    # Act — 断言结果
```
测试文件以 `test_` 前缀命名，放在 `test/` 目录下。mock 外部依赖，确保默认集不触网。

**Q: 契约测试是什么？**

A: 前后端契约回归工具：
- `test/test_contracts.py`：快速验证 API 字段一致性的自动化测试
- `scripts/contract_probe.py`：对活服务做全量请求，验证响应格式
- `scripts/contract_guard.py`：断链检测 + 快照 diff

改动 API 字段后必须跑双验证。

### 编码规范

**Q: ruff 规则是什么？**

A: 规则集：E/F/I/UP，line-length 120，target Python 3.13。
```bash
uv run ruff check .    # 检查
uv run ruff check --fix .   # 自动修复
```

**Q: 类型检查怎么跑？**

A:
```bash
uv run mypy services/ api/
```
当前存量宽松，但新代码不应引入新的类型错误。

**Q: 函数最大多少行？文件最大多少行？**

A: 函数 < 50 行，文件 < 800 行。超过先拆分再提交。

---

## 三、使用 FAQ

### 账号导入

**Q: 怎么导入账号？**

A: 进入后台设置页的账号管理，支持三种方式：
1. **手动导入**：输入 `access_token`（支持批量），可选 `refresh_token`
2. **账号密码导入**：输入邮箱+密码，系统自动尝试登录获取 token（导入后状态为"待登录"，需触发登录）
3. **CPA 池导入**：从 CLI Proxy API 的远程 auth 文件批量导入

还支持：
- 从 sub2api 管理端批量导入 OAuth 账号
- 导出账号列表（`/api/accounts/export`）

**Q: 导入后账号状态是"待登录"怎么办？**

A: 待登录表示已有邮箱密码但尚未成功获取 access_token。触发登录：
1. 在账号管理页面找到该账号，点击"重新登录"
2. 系统会自动尝试登录并获取 token
3. 如果持续失败，可能是密码错误或账号被风控

**Q: 怎么批量操作账号？**

A: 账号管理页面支持批量：
- 批量刷新 token
- 批量删除
- 批量导出
- 批量重新登录

**Q: 账号被封了怎么看？**

A: 后台 dashboard 的调度排行榜会标注健康档位（banned）。SSE 实时推送也包含账号状态变化。如果配置了告警 webhook，封号事件会推送。

**Q: OAuth 登录怎么用？**

A: OAuth 登录用于处理 ChatGPT 的 OAuth 认证流程：
1. 在设置页获取 OAuth 链接
2. 用浏览器打开链接完成认证
3. 将返回的凭据填入系统

需要配合 91kami 等取码服务，配置 `mail_credential` 后可自动取验证码。

### 代理配置

**Q: 代理怎么配置？**

A: 两种方式：
1. **全局代理**：在 `config.json` 中设置代理地址，或通过环境变量 `CHATGPT2API_PROXY_RUNTIME_PROXY_URL` 配置
2. **每号独立 IP**：系统支持 kookeey 住宅 IP，按账号邮箱 md5[:8] 粘性分配，确保同一账号始终走同一出口 IP

**Q: ChatGPT 请求被 Cloudflare 拦截了怎么办？**

A: 使用 `docker-compose.warp.yml` 部署，启动 WARP + Privoxy + FlareSolverr 清障链：
```bash
docker compose -f docker-compose.warp.yml up -d --build
```
部署后，在后台设置页的 FlareSolverr tab 中测试清障是否正常。

**Q: 代理模式有哪些？**

A: 代理池支持三种调度策略（可在设置页切换）：
- 轮询（round-robin）：轮流使用
- 加权（weighted）：按权重分配
- 最少连接（least-connections）：优先分配给连接数最少的代理

代理池健康检查自动隔离失效代理，恢复后自动重新加入。

**Q: 出口 IP 怎么看？**

A: 控制台 dashboard 的"出口 IP 探测"功能（定时 2h 自动探测），显示当前每个账号的出口 IP 和归属地。

### 配置与调优

**Q: 最小配置是什么？**

A: 只需要一个 `config.json`：
```json
{"auth-key": "your-secret-key-at-least-12-chars"}
```
其他配置都有默认值。

**Q: 怎么限制请求频率？**

A: 支持两种限流：
- 全局限流：`CHATGPT2API_RATE_LIMIT_RPM`（每分钟请求数）
- 单 IP 限流：`CHATGPT2API_RATE_LIMIT_PER_IP_RPM`

默认 0 表示不限。多 Worker 下如需精确限流，需要配置 Redis 共享状态。

**Q: 怎么配置多 Worker？**

A: 设置 `CHATGPT2API_WORKERS=N`（N>1）。注意：
- 存储后端必须是 sqlite 或 postgres（json 后端自动回退到 workers=1）
- 多 Worker 各进程的限流计数/聊天缓存/熔断器状态各自独立（状态分裂）
- 如需跨进程一致的状态，配置 Redis：`python scripts/init_redis_state.py`

**Q: 存储后端怎么切换？**

A: 通过环境变量 `STORAGE_BACKEND` 切换，可选 json / sqlite / postgres / git。切换后原有数据不会自动迁移，建议先导出再切换。具体连接串格式见 `docs/deployment.md`。

### 监控看板

**Q: 控制台在哪里？**

A: 浏览器打开 `http://localhost:23456`，用 auth-key 登录。如果前端未构建，访问 `http://localhost:23456/docs` 使用 Swagger UI。

**Q: dashboard 上怎么看关键指标？**

A: dashboard 主要页面：
- **调度看板**：账号健康分布（healthy/warm/risky/banned）、调度排行榜（前 10 名）
- **容量看板**：账号池容量使用率、配额耗尽预测
- **用量看板**：近 24h/7d 请求量趋势、成功率
- **延迟看板**：各模型/端点平均延迟、P99 延迟
- **熔断看板**：当前熔断的账号列表、熔断次数
- **kookeey 流量看板**：住宅 IP 流量消耗、额度明细
- **审计日志**：管理面操作留痕

**Q: 怎么配置告警？**

A: 在 `config.json` 中设置：
```json
{
  "alert_webhook_url": "https://your-webhook-url",
  "alert_events": ["circuit_breaker", "account_banned", "backup_failed", "quota_exhausted"]
}
```
支持的事件类型：熔断触发、账号被封、备份失败、配额耗尽、账号失效等。告警会 POST JSON 到配置的 webhook URL。

**Q: 怎么看日志？**

A: 调用日志按天轮转写入 `data/logs-YYYY-MM-DD.jsonl`，可通过 `/api/logs` 端点按 type/日期范围查询。审计日志写入 `audit-YYYY-MM-DD.jsonl`。管理面操作（401/403 必记、写操作与轮询 GET 成功记）自动留痕。

**Q: 怎么备份？**

A: 三种方式：
1. 手动备份：`tar -czf backups/chatgpt2api-$(date +%Y%m%d).tgz config.json .env data`
2. 后台设置页配置 Cloudflare R2 备份（定时自动备份）
3. 备份加密：配置 `backup.passphrase`，备份文件经 OpenSSL + HMAC 加密

### 常见报错

**Q: 调用 API 返回 401？**

A: 请求头缺少 `Authorization: Bearer <auth-key>`，或 auth-key 不正确。如果是 production 环境，auth-key 不足 12 位会被拒绝启动。

**Q: 图片生成返回 404？**

A: 图片下载失败，原因可能是：
1. 图片 URL 过期（上游返回的 URL 有时效性）
2. 下载请求未携带正确的 web cookies（cf_clearance/_cfuvid/oai-sc 等）
3. 存储后端空间不足

**Q: 返回 429 表示什么？**

A: 请求被限流。可能是全局限流、单 IP 限流或上游账号配额耗尽（free 账号有限）。查看 `resets_after` 字段知道多久后恢复。

**Q: 错误信息是英文的？**

A: 后端错误信息经 `public_image_error_message` 转译，屏蔽上游真实原因（防泄漏）。如需排查，查看日志文件的 `detail` 字段获取完整诊断信息。