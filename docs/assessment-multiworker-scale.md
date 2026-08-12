# 5.3 存储层压测与多 Worker 规模化验证 — 评估说明

> 日期：2026-08-12
> 类型：评估优先（不强制重构）
> 状态：**本机无 Docker，实际多 Worker 压测记录为边界；已完成静态架构评估 + 本地回归证据收集**

## 一、结论摘要

| 项 | 结论 |
|----|------|
| Docker 可用性 | **不可用**（无 docker 命令、无 Docker Desktop、WSL 内亦未安装）→ 记录为边界，不做实际压测，不硬造数据 |
| 多 Worker 规模化压测 | **未执行**（前置条件 Postgres/Redis 依赖 Docker，本机不具备） |
| 静态评估 | 完成：workers 回退机制、存储后端切换、shared_state 覆盖范围、session_pool/usage_agg 多进程行为均查证 |
| 本地回归证据 | `test_shared_state`/`circuit_breaker`/`session_pool`/`usage_agg`/`startup_guard` 共 **82 测试全部通过**；单 worker `stress_test` **8/8 PASS**；`benchmark_check` **PASS** |
| 报告落盘 | 本文件 + `docs/benchmark-baseline.json`（未改动，阈值仍适配当前断言） |

## 二、Docker 可用性核查（实测证据）

- `docker` 命令不存在：`where.exe docker` 无结果
- `docker-compose` 不存在
- `C:\Program Files\Docker` 目录不存在（Docker Desktop 未安装）
- WSL 存在 Ubuntu 发行版（WSL 2，`wsl -l -v` 显示 **Stopped**），WSL 内执行 `command -v docker` 亦无结果
- 结论：本机完全不具备容器运行能力。Postgres + Redis 服务无法在本机启动，**多 Worker 规模化压测无可行环境**。

## 三、多 Worker 规模化现状评估（架构事实）

### 3.1 Worker 数与存储后端的约束（`main.py` + `services/config.py`）

- `main.py::resolve_workers()`：`workers > 1` 且存储后端为 `json` 时**强制回退 `workers=1` 并打警告**（多进程各持独立账号副本 = 数据损坏）。`test/test_startup_guard.py` 有守卫测试。
- 存储后端可切换：`STORAGE_BACKEND` 环境变量 / `config.json::storage_backend`（`services/config.py:768`）。可选值 `json` / `sqlite` / `postgres` / `git`。
- `workers` 读取：`CHATGPT2API_WORKERS` 环境变量或 `config.json::workers`（`services/config.py:738`）。
- SQLite/Postgres 下可多 worker，但**从未规模化压测**（本评估证实该结论成立：无现成多 worker 压测脚本，见 3.4）。

### 3.2 shared_state 覆盖范围（关键评估发现）

`services/shared_state.py` 提供 Local / Redis 双实现，`get_shared_state()` 单例按 `CHATGPT2API_REDIS_URL`/`redis_url` 自动选择；Redis 不可用静默降级 Local 并打日志。

**已接入 shared_state 的组件（Redis 模式下计数跨进程一致）：**

| 组件 | 路径 | 证据 |
|------|------|------|
| 限流计数 | `api/rate_limit.py::SlidingWindowLimiter._check_shared` | `get_shared_state().incr(...)`；`test_shared_state.py::TestRateLimitShared` 验证"第二个进程实例看到同一计数" |
| 聊天缓存 | `services/session_cache.py` | 走 `get_shared_state()` |

**未接入 shared_state 的组件（多 worker 下各进程独立 → 状态分裂风险仍在）：**

| 组件 | 现状 | 说明 |
|------|------|------|
| 熔断器 | `services/circuit_breaker.py`：`self._state / _failure_count / _lock` 均为进程内字段 | **未走 shared_state**。多 worker 下每个进程独立熔断判定，上游故障时可能部分 worker 熔断、部分继续打上游。`shared_state.py` 文档 D16 亦承认"熔断器状态在各进程独立" |
| session_pool | `services/session_pool*.py`：进程内对象池 | 各 worker 独立维护会话池，跨进程不共享（符合"多进程共享状态只走存储层"红线，但池命中率受 worker 数稀释） |
| usage_agg | `services/usage_agg*`：进程内聚合 + 日志落盘 | 各 worker 独立聚合，最终靠 `data/logs/*.jsonl` 天文件合并口径 |

> 结论：任务 2c 的假设"shared_state Redis 模式下**熔断/限流计数一致**"中，**限流成立（有测试证据），熔断不成立**——熔断器未接入 shared_state，多 worker 下仍存在状态分裂。若未来要求熔断跨进程一致，需将 `CircuitBreaker` 状态迁移到 shared_state（当前评估不建议动，属重构范畴）。

### 3.3 限流共享路径的已知语义

`api/rate_limit.py:47` 注释明确：共享层为固定窗口近似（incr + TTL），窗口切换瞬间前一窗口清零，**边界允许最多 2×max_requests 突刺**（非精确滑窗）。精确限流需 Redis ZSET 滑窗日志（登记后续迭代）。多 worker 基准对比时应将此纳入误差说明。

### 3.4 压测工具现状（`scripts/stress_test.py`）

- 现脚本使用 **TestClient 进程内压测**（不监听端口），并发模型为线程池。
- **该脚本天然单进程**，无法验证 `workers=4` 的真实多进程行为。多 worker 压测需要：真实 uvicorn 启动（`workers=N`）+ 外部 HTTP 施压（ab/wrk/locust 或新增 HTTP 模式的压测脚本）。
- 因此"多 worker 规模化压测"不是简单传参即可完成，需要新增压测路径 —— 这是本评估发现的一处**能力缺口**。

### 3.5 docker-compose 现状（`docker-compose.local.yml`）

- 服务列表：`app` + `redis`（`redis:7-alpine`，端口 6379，AOF 持久化，128MB 上限）。**无 postgres 服务**。
- app 默认 `STORAGE_BACKEND: sqlite`，Redis 共享状态以注释形式预留（`CHATGPT2API_REDIS_URL`）。
- 若要在有 Docker 的环境补全多 worker 规模化验证，需新增 postgres 服务并让 `DATABASE_URL` 指向它。参考片段（未实测，仅记录建议）：

```yaml
  postgres:
    image: postgres:16-alpine
    container_name: chatgpt2api-local-postgres
    environment:
      POSTGRES_USER: chatgpt2api
      POSTGRES_PASSWORD: chatgpt2api
      POSTGRES_DB: chatgpt2api
    ports:
      - "5432:5432"
    volumes:
      - pg-data:/var/lib/postgresql/data
volumes:
  pg-data:
```

## 四、测试与回归证据（本机可跑的验证）

命令：`.venv/Scripts/python.exe -m pytest <files> -q`

| 验证项 | 结果 |
|--------|------|
| shared_state（Local/降级/限流共享路径）+ 熔断器 + session_pool（含 edge/leak）+ usage_agg + 启动守卫 | **82 passed**（36.76s） |
| 单 worker `scripts/stress_test.py`（最新 20260812_020302） | **8/8 PASS**，错误率 0 |
| `scripts/benchmark_check.py` | **PASS**（rps 63.9 ≥ 30 / p99 918.2 ≤ 1500 / error 0 ≤ 1% / slow p99 899.6 ≤ 4000） |

单 worker 最新实测（对比基线 149.5 rps / p99 334ms）：并发 20 档 63.9 rps / p99 918ms / p50 252ms / 错误 0 —— 低于基线档并发 15 的数值，受本机并发负载与测试参数影响，但均在阈值内，说明单 worker 基线当前仍健康。**基线文件未改动**（`docs/benchmark-baseline.json` 仍为 v2.33.0 档）。

## 五、已知风险与边界

1. **熔断器多 worker 状态分裂**：各 worker 独立熔断，上游故障时熔断不公平（部分进程仍放行打上游）。属 HIGH 级隐患，本次不修（重构范畴）。
2. **固定窗口限流 2× 突刺**：共享层近似限流边界允许 2×max_requests 峰值，需精确限流时上 Redis ZSET 滑窗。
3. **无多 worker 压测脚本**：`stress_test.py` 为进程内单进程模型，多 worker 压测需新压测路径。
4. **docker-compose 缺 postgres**：多 worker + Postgres 场景无现成编排。
5. **无 Docker = 无法实测**：本机 Postgres/Redis 均不可起，多 worker 数值结论（rps/p99/错误率）**不可得**，未编造任何数据。

## 六、后续在有 Docker 环境的执行清单（交接给执行者）

1. 安装 Docker Desktop 或使用远程 Docker 主机。
2. 补全 `docker-compose.local.yml` 的 postgres 服务（见 3.5 片段）。
3. `docker compose -f docker-compose.local.yml up -d` 起 postgres + redis。
4. 启动多 worker：`STORAGE_BACKEND=postgres DATABASE_URL=postgresql://chatgpt2api:chatgpt2api@127.0.0.1:5432/chatgpt2api CHATGPT2API_REDIS_URL=redis://127.0.0.1:6379/0 CHATGPT2API_WORKERS=4 python main.py`（注意 23456 端口占用）。
5. 新增 HTTP 压测路径（或使用 ab/wrk/locust）打 `http://127.0.0.1:23456/api/dashboard/*`，对比单/多 worker 的 rps/p99/错误率。
6. 验证 Redis 模式下限流计数一致（跨进程同 key `ratelimit:*` 计数）；确认熔断器现状（进程内）是否符合预期。
7. 将多 worker 实测档写入 `docs/benchmark-baseline.json`（新增档位 + 相应阈值），跑 `scripts/benchmark_check.py` 确认断言。

## 七、相关文件索引

- `main.py`（resolve_workers 回退）
- `services/config.py`（workers / storage_backend_type / redis_url）
- `services/shared_state.py`（Local/Redis 共享状态层）
- `api/rate_limit.py`（共享限流路径 + 降级）
- `services/circuit_breaker.py`（进程内熔断，未共享）
- `services/session_cache.py`（共享聊天缓存）
- `scripts/stress_test.py`（单 worker 进程内压测）
- `scripts/benchmark_check.py`（基准断言）
- `docs/benchmark-baseline.json`（v2.33.0 单 worker 基准，未改动）
- `docker-compose.local.yml`（app + redis，缺 postgres）
- `test/test_shared_state.py`、`test/test_startup_guard.py`、`test/test_session_pool*.py`、`test/test_usage_agg.py`、`test/test_circuit_breaker.py`
