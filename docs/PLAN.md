# ChatGPT2API 增强计划

> 目标：Windows 一键启动、7×24 稳定运行、调度看板、万级并发
> 参考：`寻雷科技产品（AI模块独立应用）\AI视频故事版`（bat 风格）、`codex2api`（调度/看板/运维）

## 现状盘点

| 能力 | 当前状态 | 说明 |
|------|----------|------|
| Windows 启动 | ✅ 已完成 | bat 一键启动，chcp 65001 UTF-8，自动检测环境 |
| 7×24 稳定运行 | ✅ 已完成 | bat 崩溃自动重启 + 守护线程（account-watcher、image-cleanup、backup） |
| 智能调度 | ✅ 已完成 | 健康档位（healthy/warm/risky）+ 调度分 + 双模式 + 优先级 |
| 运维看板 | ✅ 已完成 | 调度看板、运维概览、用量统计（3 个 API + 前端页面） |
| 限流 | ✅ 已完成 | 滑动窗口 RPM 限流（全局 + 单 IP），配置可调 |
| 高并发 | ✅ 已完成 | 多 Worker（config.workers）、连接池调优、压测 7912 req/min |
| 独立代理 | 🟡 已有 | 全局 proxy + WARP 运行时，缺代理池/账号级绑定（后续迭代） |
| 号池 | ✅ 完整 | 导入/刷新/状态机/自动移除/健康档位调度 |
| 配置管理 | ✅ 已完成 | 5 个新配置项：scheduler_mode、scheduler_priority、rate_limit_rpm、rate_limit_per_ip_rpm、workers |

## 各阶段完成情况

### 阶段 1：Windows 一键启动 bat（✅ 已闭环）
- `启动chatgpt2api.bat`：chcp 65001 UTF-8、venv 自动创建、uv sync、前端构建（webpack 兼容中文路径）、启动 uvicorn、端口检测、优雅退出、崩溃自动重启
- `停止chatgpt2api.bat`：按端口杀进程
- `package.json`：build 脚本改为 `next build --webpack` 避免中文路径 Turbopack 崩溃

### 阶段 2：7×24 稳定运行（✅ 已闭环）
- 启动脚本增加崩溃自动重启循环（Ctrl+C 退出，非 0 退出码 3 秒后自动重启）
- 守护线程：account-watcher（5min 刷新限流/过期账号）、image-cleanup（30min 清磁盘）、backup_service

### 阶段 3：调度升级（✅ 已闭环）
- 移植自 codex2api fast_scheduler 的调度核心
- 健康档位：healthy（健康）、warm（温存）、risky（风险）
- 调度分：基础分 + 配额占比 + 成功加成 - 失败惩罚 - 错误时间惩罚
- 优先级：config.scheduler_priority 按 email/token 配置（-100 ~ 100）
- 双模式：round_robin（轮询）、remaining_quota（按剩余配额降序）
- 选取顺序：优先级 > 健康档位 > 调度分
- 单元测试通过（4 个测试用例全部 PASS）

### 阶段 4：看板与运维页面（✅ 已闭环）
- 后端 3 个 API：
  - `/api/dashboard/scheduler`：调度健康度 + 账号排行榜（含档位、调度分、优先级）
  - `/api/dashboard/ops`：运维概览（平台/CPU/内存/磁盘/存储/运行时长）
  - `/api/dashboard/usage`：近 24h 调用统计（成功/失败/类型分布/最近记录）
- 前端页面：运维看板 `/dashboard`（账号池总览卡、资源占用卡、调度排行榜表、调用分布标签）
- 导航栏新增"运维看板"入口

### 阶段 5：高并发万级（✅ 已闭环）
- 多 Worker：`main.py` 自动读取 `config.workers` 配置启动多进程
- 限流中间件：滑动窗口算法，全局 RPM + 单 IP RPM，线程安全
- 连接池优化：`--limit-concurrency 512 --backlog 1024`
- 压测验证：4 Worker 达 7912 req/min，0 连接失败/崩溃
- **注意**：真正的万级 RPM 需要多实例 + Redis 共享存储 + 充足的账号池，当前架构已达单机瓶颈上限

### 终局审计与闭环（✅ 已闭环）
- 修复：workers 配置项未在 config.get() 中暴露 → 前端无法读取
- 修复：前端 SettingsConfig 类型缺失 scheduler_mode/rate_limit_rpm/workers
- 修复：前端 settings store 缺失对应的 setter 方法
- 修复：前端设置页面缺少新配置项 UI（调度模式选择、限流输入、Worker 数输入）
- 修复：dashboard.py 中不规范写法（`__import__('datetime')` 改为直接 import）
- 修复：中文路径下 Turbopack 构建失败（改为 webpack）
- 修复：前端导航栏未包含运维看板

## 未完成项（后续迭代）

| 项目 | 原因 | 优先级 |
|------|------|--------|
| 代理池/账号级绑定代理 | 需要 codex2api proxy_pool.go 完整移植 | P2 |
| 多实例 Redis 分布式限流 | 当前内存限流单机够用 | P2 |
| 用量趋势图可视化 | ✅ 已用 Recharts 实现 | P2 |
| 账号池批量导入 UI 优化 | 当前可用 | P3 |
| 环境变量覆盖新配置项 | ✅ 已实现（CHATGPT2API_* 前缀） | P3 |
| 多 Worker + JSON 存储数据安全性 | ✅ 已修复（自动回退 workers=1 + 警告） | P0 |
| 生产部署文档 | ✅ 已添加至 README.md | P1 |