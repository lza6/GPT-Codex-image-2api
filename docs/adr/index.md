# ADR-001: 智能调度系统

## 状态
已实施（2026-08-01）

## 背景
账号池需要根据账号的健康状态、配额、成功率动态选择最优账号，而非简单轮询。

## 决策
移植 codex2api 的 fast_scheduler 三阶段调度模型：
1. 优先级排序（config.scheduler_priority）
2. 健康档位（healthy > warm > risky）
3. 调度分竞争（配额占比 + 成功加成 - 失败惩罚 - 冷却惩罚）

## 后果
- 正面：账号利用率提升，失败率降低
- 负面：调度分计算增加 CPU 开销（可忽略）
- 风险：调度优先级配置不当可能导致账号饥饿

# ADR-002: 限流方案

## 状态
已实施（2026-08-01）

## 背景
防止突发流量打崩上游 API 导致账号全封。

## 决策
采用内存滑动窗口限流，两级限流：
- 全局 RPM（rate_limit_rpm）
- 单 IP RPM（rate_limit_per_ip_rpm）

## 后果
- 正面：零外部依赖，毫秒级判断
- 限制：多进程下各自独立，总限流数为 workers × 单机限流

# ADR-003: 多 Worker 策略

## 状态
已实施（2026-08-01）

## 背景
单进程无法利用多核 CPU，高并发场景需要多进程。

## 决策
- JSON 存储后端时自动回退 workers=1 并警告
- SQLite/Postgres 存储后端时允许多 Worker
- 通过 config.workers 和 CHATGPT2API_WORKERS 环境变量控制

## 后果
- 正面：4 Worker 压测达 7912 req/min
- 限制：JSON 存储下无法多 Worker

# ADR-004: 代理池

## 状态
已实施（2026-08-02）

## 背景
账号级代理绑定需要独立的管理系统，支持健康检查和自动切换。

## 决策
移植 codex2api ProxyPool 的完整模型：
- 三种选择策略：轮询 / 加权 / 最少连接
- 健康检查：定时检测代理可用性
- 自动隔离：连续失败 N 次后隔离，超时自动恢复

## 后果
- 正面：代理故障自动切换，减少人工干预
- 约束：健康检查需要目标 URL 可达
---

# ADR-005: TLS 会话池 key 含账号标识 + 指纹（第七轮强化）

## 状态
已实施（2026-08-02，v2.0.0 后第七轮审计强化）

## 背景
Session 池化第六轮已接线，但第七轮审计实证发现：池 key 仅含 token 末 8 位时，同账号不同指纹的实例仍共享 Session；且 `OpenAIBackendAPI.__init__` 往共享 Session 的 headers 注入 Authorization，后构造实例覆盖先构造者——串号实证（b1 请求带 b2 的 token）。

## 决策
- 池 key 加入 `fp_key`（oai-device-id 指纹标识），同账号同指纹才共享
- Authorization 永不写 `session.headers`，改为请求级 headers= 传参
- UA/Sec-Ch-UA 等指纹头经 fp_key 绑定池 key，池上只写会话级身份头（OAI-Device-Id/OAI-Session-Id）
- fp 从 access_token 确定性派生（uuid5），同账号每次实例化同指纹

## 后果
- 正面：串号免疫（实证 + 回归测试）；同 token 复用 Session（TLS 只握手一次）
- 代价：匿名链路（无 token）不池化（随机指纹）
- 教训：池化共享对象禁止写实例级数据——"池化接线完成"不等于"池化正确"

# ADR-006: 统一重试预算——流式首字节后永不重试

## 状态
已实施（2026-08-02，v2.0.0）

## 背景
流式响应开始后重试会吐出重复/错乱内容，且图片/计费场景重复扣费。

## 决策
- 幂等 GET：指数退避 ≤2 次
- 流式首字节前：换号 ≤1 次
- 流式开始后：`can_retry_stream(emitted=True)` 恒 False，绝不重试

## 后果
- 正面：宁可失败也不冒重复扣费/出图风险；变异探针对上限做回归
- 约束：调用方需接受流式中断即失败（前端有 resume-poll 兜底）

# ADR-007: bat/Docker 统一走 main.py 启动（守卫不可绕过）

## 状态
已实施（2026-08-02，第七轮修复）

## 背景
bat 与 Dockerfile 此前直接 `uvicorn main:app`，绕过 main.py `__main__` 块的 workers 回退与 PROMETHEUS_MULTIPROC_DIR 初始化——workers 配置静默无效、多进程指标永不聚合。

## 决策
- workers 解析模块级化（`resolve_workers()`），uvicorn CLI 与 `python main.py` 两条路径共享
- bat 启动命令改 `uv run python main.py`；Dockerfile CMD 改 `["uv","run","python","main.py"]`
- 端口保留 CHATGPT2API_PORT 环境变量（Docker 80 / 本地 23456）

## 后果
- 正面：JSON 存储 workers>1 回退在所有启动路径生效；multiproc 指标聚合在 Docker 下可用
- 约束：uvicorn CLI 直跑（`uvicorn main:app`）不再有守卫——文档统一引导 main.py

# ADR-008: JSON 存储原子写 + 损坏拒绝静默

## 状态
已实施（2026-08-02，第七轮修复）

## 背景
accounts.json/auth_keys.json/config.json/image_tags.json/logs.jsonl 此前均裸 write_text 整文件覆写；且 `_load_json_list` 对损坏文件 `except: return []`——监控全绿的情况下账号池静默清空。

## 决策
- 统一 `_atomic_write_text`：唯一 tmp（pid+uuid）+ replace（原子）+ Windows 瞬态锁退避重试
- 损坏文件 load 抛 ValueError（拒绝静默吞），health_check 解析校验（损坏报 unhealthy）
- log delete/_auto_cleanup 加进程内互斥锁

## 后果
- 正面：半写截断不可能；损坏即启动失败（可感知可恢复）而非静默丢数据
- 代价：损坏时服务拒绝启动，需人工从备份恢复——这是特性不是 bug

# ADR-009: 无 GitHub 远程、纯本地 tag 发版

## 状态
已实施（2026-08-02，v2.0.0）

## 背景
内部工具 + 逆向合规红线（README 免责声明不可删），不投放公共协作平台。

## 决策
- git remote 移除（防误推上游作者仓库）
- 发版仅本地 `git tag`；docker-compose 引用上游镜像，内部 fork 的 docker-publish.yml 推到自己的 ghcr owner

## 后果
- 正面：合规安全；无外部协作面
- 约束：无 PR 流程，质量门靠本地五道防线 + CI

# ADR-010: pytest 标记区分（live/redis/unit）而非目录隔离

## 状态
已实施（2026-08-01）

## 背景
live 测试需真实上游，CI 不能触网。

## 决策
- 同目录混放，`pyproject.toml addopts = "-m 'not live and not redis'"` 默认排除
- 本地手动 `-m live` 跑活测试

## 后果
- 正面：维护成本低，测试与实现同域
- 代价：依赖每个贡献者记得 -m；conftest autouse fixture 隔离环境污染

# ADR-011: CI 四道门分级——ruff/mypy/pip-audit 宽限 + pytest/前端 tsc 硬阻断

## 状态
已实施（2026-08-01）

## 背景
存量 lint/mypy/依赖债大，一次性清零不现实。

## 决策
- ruff/mypy/pip-audit 设 `continue-on-error: true`（提示不阻断，分期偿还）
- pytest（排除 live/redis）+ 前端 tsc --noEmit + npm run build 硬阻断

## 后果
- 正面：不再新增红；存量债可见
- 风险：pip-audit 软门意味着依赖漏洞不阻断——需定期人工复核

# ADR-012: CORS 默认收紧 + /metrics 需鉴权（v2.0.0 破坏性变更）

## 状态
已实施（2026-08-02，v2.0.0）

## 背景
安全默认值偏弱（CORS=*、metrics 裸奔暴露账号规模）。

## 决策
- CORS 配置驱动，production 下 `*` 启动告警
- /metrics 加 require_identity（Authorization 或 ?token=）

## 后果
- 正面：管理面指标不公网暴露
- 代价：v2.0.0 前抓取的 Prometheus 升级后 401，需改 scrape 配置（README 已给迁移指引）

# ADR-013: 五道防线工具化（终局审计的产物固化）

## 状态
已实施（2026-08-02，第七轮）

## 背景
用户要求"契约防坑/极限施压/慢查询/SQL 安全/测试有效性"五道防线可持续执行，而非一次性审计。

## 决策
- `scripts/run_all_guards.py` 一键执行五道：contract_guard（断链+快照 diff）/ sql_audit / slow_query_report / mutation_probe / stress_test
- 报告落盘 reports/（gitignore）；任何 FAIL 不许交付
- 注入 chatgpt2api-workflow skill 的终局交付门禁

## 后果
- 正面：第七轮已抓真 bug——契约守卫抓 1 断链假功能、变异探针抓 1 测试盲区（熔断默认阈值逃逸）
- 约束：mutation_probe 变异锚点随代码漂移需维护（锚点漂移会显式报 anchor-drift 而非静默）
