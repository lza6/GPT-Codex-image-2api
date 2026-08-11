# CLAUDE.md — ChatGPT2API 项目指南

ChatGPT 官网能力的逆向封装服务：OpenAI 兼容的图片生成/编辑 API + 号池管理 + 智能调度 + 运维看板，自托管部署，Windows 一键启动。

## 技术栈

| 层 | 技术 | 位置 |
|----|------|------|
| 后端 | Python 3.13 · FastAPI · uvicorn · curl-cffi · SQLAlchemy | `api/` `services/` `main.py` |
| 前端 | Next.js 16 · React 19 · Tailwind v4 · zustand · recharts | `web/src/` |
| 存储 | JSON / SQLite / PostgreSQL / Git（可切换） | `services/storage/` |
| 部署 | Docker Compose · Windows bat 脚本 | `Dockerfile` `启动chatgpt2api.bat` |
| 包管理 | uv（后端，阿里云镜像源）· npm/bun（前端） | `pyproject.toml` `uv.lock` |

## 常用命令

```bash
# 后端（Windows）
uv sync                          # 安装依赖（.venv）
python main.py                   # 启动，端口 23456
启动chatgpt2api.bat               # 一键启动（崩溃自动重启，双击实测）
停止chatgpt2api.bat               # 停止

# 测试（pytest 配置在 pyproject.toml）
uv run pytest                    # 默认：排除 live 和 redis 标记（不触网）
uv run pytest -m live            # 需真实上游，本地手动运行
uv run pytest -m unit            # 纯单元测试
uv run pytest test/test_v1_chat_completions.py   # 单文件

# 质量
uv run ruff check .              # lint（E/F/I/UP，line-length 120）
uv run mypy .                    # 类型检查（现状宽松）
uv run pip-audit                 # 依赖漏洞扫描

# 前端（web/ 目录）
cd web && npm run dev            # 开发（0.0.0.0:3000）
cd web && npm run build          # 构建 → web/out + web_dist

# Docker
docker compose up -d             # 端口 23456:80
```

## 架构与关键路径

```
请求 → api/ (FastAPI 网关: ai/accounts/dashboard/image/system + 限流/安全头/请求大小中间件)
     → services/ (账号池、代理池、智能调度、熔断器、图片任务、OAuth、日志、备份、认证)
     → services/storage/ (JSON | SQLite | PostgreSQL | Git)
```

| 关注点 | 位置 |
|--------|------|
| 应用入口/多 Worker/Prometheus 聚合 | `main.py` |
| 全部运行时配置（含 schema 校验） | `config.json` + `services/config.py` |
| 智能调度（healthy/warm/risky 档位 + 调度分） | `services/account_service.py` |
| 上游熔断 + 分级重试 | `services/circuit_breaker.py` |
| OpenAI 兼容端点（/v1/images/*, /v1/chat/completions, /v1/responses） | `api/ai.py` |
| 前后端契约回归工具 | `scripts/contract_probe.py` + `test/test_contracts.py` + `scripts/contract_guard.py`（断链检测+快照 diff） |
| 节点/审计状态 | `workflow_status.md` `计划书/` |

## 项目约定（必须遵守）

- **测试标记**：live 测试与单元测试同放 `test/`，用 `-m` 区分，不做目录隔离；CI 默认不触网
- **多 Worker 安全**：`workers > 1` 时存储后端必须是 SQLite/Postgres，main.py 会自动从 JSON 回退到 workers=1
- **端口固定 23456**：Docker/bat/文档全套同步，改动需全局替换
- **契约对齐**：改 API 字段后跑 `scripts/contract_probe.py` 与 `test/test_contracts.py` 双验证
- **bat 脚本**：必须 GBK 编码 + CRLF 无 BOM（chcp 65001 会破坏中文显示）
- **存储目录**：运行时数据全在 `data/`，勿提交；`config.json` 挂载进容器
- **中文环境**：回复用简体中文；代码标识符保持英文

## 安全红线

- 永不硬编码密钥；`config.json` 的 auth-key/backup 密钥用环境变量覆盖（`CHATGPT2API_AUTH_KEY` 等）
- 逆向研究项目：README 免责声明不可删；不用于商业/批量/滥用场景
- 提交前跑 `pip-audit` + `ruff check`；涉及 auth/账号/上游调用的改动先过安全审查
- 多进程共享状态只走存储层，禁止模块级可变全局变量跨请求持有

## 上下文工具（按序优先）

1. **graft**（本仓库已索引）：`graft ask "<问题>" --source` 定位+内联代码；`graft grep "<字面量>"` 穷举；`graft callers <符号>` 影响面；改完 `graft build` 刷新
2. **codegraph MCP**（`.codegraph/` 存在）：结构性问题用 `codegraph_context`/`codegraph_callers`
3. Grep/Read 仅在上述未覆盖时使用；`graft/INDEX.md` 可浏览全部节点

## 当前状态（2026-08-12，v2.33.0 已发版）

v2.33.0 已闭环：R2 图片存储配置接线 6 步齐全（前端 r2/r2_local 模式 + 五字段表单 + 按模式连接测试）+ R2Client 层测试补全 + e2e/ Playwright 体系纳入版本控制 + 变异探针增强。v2.18→v2.32 完成矩阵见 `workflow_status.md`（第二十二轮），验证基线见 `docs/verification-registry.md`。日常维护遵循：
改动 → 契约探测 → 测试 → **六道防线**（`scripts/run_all_guards.py`：契约/SQL/慢查询/变异/压测/文档同步）→ `workflow_status.md` 更新。

**会话启动协议**：动手前先读 `.claude/skills/chatgpt2api-workflow/SKILL.md` → 判过时（对照代码抽查）→ 过时先更新再编码；验收门禁见该技能"终局交付门禁"。
