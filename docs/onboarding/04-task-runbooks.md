# 04 · 常见任务 Runbook

## R1 · 新增一个 API 端点

1. **定位**：公开 API 放 `api/ai.py`（OpenAI 兼容域），管理端点按域放 `api/accounts.py` / `api/dashboard.py` / `api/system.py` / `api/proxy_pool.py` / `api/image_tasks.py`
2. **写路由**：参考同文件既有端点；错误响应用 `api/errors.py` 的统一格式
3. **业务逻辑放 services/**：api 层只做入参校验和组装，不写业务
4. **写测试**：`test/test_v1_<域>.py`，AAA 结构；不触网的标 `@pytest.mark.unit`
5. **契约验证**（改了请求/响应字段才需要）：
   ```bash
   uv run pytest test/test_contracts.py
   uv run python scripts/contract_probe.py   # 需活服务
   ```
6. **文档同步**：公开端点同步 `docs/api/openapi.yaml` + `docs/api/examples.md`（N13 约定）
7. **自查**：`uv run ruff check . && uv run pytest`

## R2 · 改前端页面

1. 页面在 `web/src/app/<页面名>/`，共享组件在 `web/src/components/`
2. API 调用走 `web/src/lib/`（axios 封装）；**字段名必须与 `services/protocol/` 输出一致**
3. 状态用 zustand（`web/src/store/`），别引入新状态库；样式用 Tailwind v4，别引新 CSS 框架
4. 验证：`cd web && npm run build`（webpack 构建过才算完，tsc 0 错误）
5. 若后端字段也变了：跑契约探测（见 R1-5）

## R3 · 写/跑测试

```bash
uv run pytest                                # 默认：不触网（排除 live/redis）
uv run pytest -m unit                        # 只跑纯单元
uv run pytest test/test_circuit_breaker.py -v   # 单文件
uv run pytest -m live                        # 需真实上游——本地一般跑不了，CI 也不跑
uv run pytest -m redis                       # 需 Redis
```

- 新测试默认不加标记即被 CI 收集；需活服务才加 `@pytest.mark.live`
- 夹具看 `test/conftest.py`，别自己造活服务连接
- live 测试与单元测试同放 `test/`，用 `-m` 区分——**项目约定，不做目录隔离**

## R4 · 改 config.json 配置

1. 改字段结构 → 同步 `services/config.py` 的 schema 校验（N12：报错带行号）
2. 验证：启动一次 `uv run python main.py`，schema 错会拒绝启动并报行号
3. 文档同步：`.env.example`（若涉及环境变量）+ `docker-compose*.yml` 注释（若部署相关）+ 本套 onboarding 03 章环境变量表
4. 密钥类字段必须支持环境变量覆盖（`CHATGPT2API_*` 前缀，参照既有模式）

## R5 · 加依赖

```bash
# 后端
uv add <package>            # 自动更新 pyproject.toml + uv.lock
uv add --dev <package>      # 开发依赖

# 前端
cd web && npm install <package>
```

- 加完跑 `uv run pip-audit` 查漏洞；新依赖在 PR 描述里说明用途
- 锁文件（`uv.lock` / `package-lock.json`）必须一起提交

## R6 · 新增存储后端

1. 实现 `services/storage/base.py` 的 6 个抽象方法：`load_accounts` / `save_accounts` / `load_auth_keys` / `save_auth_keys` / `health_check` / `get_backend_info`
2. 在 `services/storage/factory.py` 注册新后端
3. 写测试（参照 `test/test_database_storage.py`）
4. 多 Worker 安全性评估：若后端不支持多进程共享，需在 `main.py` 回退逻辑中声明
5. 同步 `.env.example` + compose 注释 + onboarding 03 章

## R7 · 多 Worker 运行

```bash
CHATGPT2API_WORKERS=4 STORAGE_BACKEND=sqlite uv run python main.py
```

- 存储后端必须是 sqlite/postgres；JSON 后端 main.py 强制回退 workers=1 并打印警告
- `PROMETHEUS_MULTIPROC_DIR` 由 main.py 自动初始化为 `data/prometheus_multiproc/`（启动时清空旧 `*.db`）
- **多进程共享状态只走存储层**：禁止模块级可变全局变量跨请求持有（项目安全红线）
- 压测基线：7912 req/min（N5 验收）

## R8 · 部署

```bash
# 生产（拉镜像）
docker compose up -d

# 本地构建验证
docker compose -f docker-compose.local.yml up -d --build

# CF 清障链（上游 403 频发时）
docker compose -f docker-compose.warp.yml up -d
```

- 端口固定 23456:80；`config.json` + `./data` 挂载进容器，不进镜像
- 镜像发布走 `.github/workflows/docker-publish.yml` → `ghcr.io/basketikun/chatgpt2api:latest`
- 部署文档详见 `docs/deployment.md`

## R9 · 调试一个线上行为

1. 日志：`data/logs.jsonl`（单文件，超 5000 条惰性裁剪到 3000，无需手动清）
2. 指标：`/metrics` + dashboard 页（调度健康度、用量、账号排行榜、延迟分布）
3. 请求追踪：响应头 `X-Request-ID`，日志全文 grep 该 ID（N17：contextvars 全链路）
4. 实时事件：SSE `/api/dashboard/stream`（EventSource，token 走 query 参数）
5. 复现：本地起服务 + `curl` 重放；live 行为问项目方要脱敏样本
6. 代码定位：`graft ask "<问题>" --source`（本仓库已索引，改完跑 `graft build` 刷新）

## R10 · 提交 PR

1. 分支：`feat/xxx` 或 `fix/xxx`
2. 提交格式：`<type>: <描述>`（feat/fix/refactor/docs/test/chore/perf/ci）
3. 必过 CI 双 job 四道门：ruff → mypy → pytest（排除 live/redis）→ pip-audit + 前端 tsc/build
4. PR 描述：动机 + 改动点 + 验证证据（测试输出/截图）
5. 若改了 `workflow_status.md` 跟踪的节点行为，同步更新该文件（项目维护期约定）
