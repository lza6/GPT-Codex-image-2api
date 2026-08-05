# ChatGPT2API 开发者 Onboarding

> 按受众分三版：**高级工程师版**（本 README 主索引）、**初级开发者版**（07）、**承包商版**（README-contractor）。
> 高级版生成日期：2026-08-02 · 初级版：2026-08-05 · 当前版本 **2.7.1** · 项目状态：维护期，379 测试用例
> 其他版本：[初级开发者版](07-junior-developer.md)（零基础：术语表+端到端走查+任务演练）· [外包/承包商版](README-contractor.md)（强调边界与汇报协议）

## AI 编码助手专用

如果你是 AI 助手（Claude Code 等），**先读** `.claude/skills/chatgpt2api-workflow/SKILL.md`（开发工作流+验收门禁+历史 bug 警示），再读本套文档。改动完成后跑 `scripts/run_all_guards.py`（五道防线一键回归）。

## 这套文档

| 文档 | 什么时候读 |
|------|-----------|
| [01-architecture.md](01-architecture.md) | 上手前：系统边界、数据流、安全模型、扩展极限、技术债 |
| [02-key-files.md](02-key-files.md) | 动手前：20 个关键文件 + 危险修改清单 |
| [03-setup.md](03-setup.md) | 第一天：clone → 测试全绿，含环境变量全表与三套 compose |
| [04-task-runbooks.md](04-task-runbooks.md) | 干活时：加端点/加存储后端/多 Worker/部署的固定步骤 |
| [05-debugging.md](05-debugging.md) | 出问题时：历史 P0/P1 故障档案 + 症状速查 + 诊断命令 |
| [06-contributing.md](06-contributing.md) | 提交前：CI 质量门、提交约定、文档同步点 |
| [07-junior-developer.md](07-junior-developer.md) | 零基础入门：术语表 + 一次请求端到端走查 + 三个任务演练 + 测试入门 |

## 60 秒速览

- **是什么**：ChatGPT 官网能力的逆向封装，对外暴露 OpenAI 兼容 API（`/v1/images/*`、`/v1/chat/completions`、`/v1/responses`、`/v1/messages`、`/v1/search` 等），自带号池管理、智能调度、代理池、熔断器、Prometheus 可观测性与运维看板。单体 FastAPI + Next.js 静态导出，自托管。
- **技术栈**：后端 Python 3.13 + FastAPI + curl-cffi + SQLAlchemy（uv 管理，阿里云镜像源）；前端 Next.js 16 + React 19 + Tailwind v4 + zustand（`web/`，webpack 静态导出到 `web_dist/`）；存储可切 JSON/SQLite/PostgreSQL/Git。
- **端口**：后端固定 **23456**；前端 dev 3000；Docker 映射 23456:80。
- **本地最快验证**：`uv sync` → `uv run pytest`（默认排除 live/redis，不触网）→ `python main.py` → `http://localhost:23456`。
- **三条不可逾越的红线**：
  1. **端口 23456 全局固定**，改动需 Docker/bat/前端/文档全套同步（N15 节点）。
  2. **`workers > 1` 时存储后端必须 SQLite/Postgres**，JSON 后端下 main.py 自动回退 workers=1（数据安全兜底）。
  3. **改任何 API 字段后必须双验证**：`scripts/contract_probe.py` + `test/test_contracts.py`；改完跑一次 `scripts/run_all_guards.py`（五道防线：契约/SQL/慢查询/变异/压测）。

## 前置假设

- 开发环境为 Windows（bat 脚本仅 Windows；macOS/Linux 直接 `python main.py`）。
- live 测试（`-m live`）需要真实上游账号，由项目方内部跑，CI 不触网。
- 逆向研究项目：README 免责声明不可删，不用于商业/批量/滥用场景。

## 与项目内其他文档的关系

- **CLAUDE.md**（仓库根）：项目约定速记，与本套文档互补；改约定两边同步。
- **docs/api/**：OpenAPI 3.0 契约 + 多语言 SDK 示例 + 错误码表（N13），改 API 时同步。
- **docs/adr/index.md**：架构决策记录索引，重大选型先查这里。
- **workflow_status.md**：节点闭环状态与七轮审计历史，改动节点行为后需更新。
- **计划书/**：原始需求与执行记录。
