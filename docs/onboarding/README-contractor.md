# ChatGPT2API 开发者 Onboarding（外包/承包商版）

> 受众：外包与承包商工程师。目标：**最小上下文上手，明确能改什么、不能改什么、怎么验证。**
> 生成日期：2026-08-02 · 项目状态：15 个功能节点全部闭环，处于维护期

## 这套文档

| 文档 | 什么时候读 |
|------|-----------|
| [01-architecture.md](01-architecture.md) | 上手前：系统长什么样、数据怎么流 |
| [02-key-files.md](02-key-files.md) | 动手前：20 个关键文件 + **危险修改清单（必读）** |
| [03-setup.md](03-setup.md) | 第一天：从 clone 到跑通测试 |
| [04-task-runbooks.md](04-task-runbooks.md) | 干活时：加端点/改前端/写测试的固定步骤 |
| [05-debugging.md](05-debugging.md) | 出问题时：真实错误 → 修复对照表 |
| [06-contributing.md](06-contributing.md) | 提交前：边界、验证清单、PR 要求 |

## 60 秒速览

- **是什么**：ChatGPT 官网能力的逆向封装，对外暴露 OpenAI 兼容 API（图片生成/编辑、chat completions），带号池管理、智能调度、运维看板的自托管服务。
- **技术栈**：后端 Python 3.13 + FastAPI（uv 管理依赖）；前端 Next.js 16 + React 19（`web/`）；存储可切 JSON/SQLite/PostgreSQL/Git。
- **端口**：后端固定 **23456**；前端 dev 3000。
- **本地最快验证**：`uv sync` → `uv run pytest`（默认不触网）→ `python main.py` → 访问 `http://localhost:23456`。
- **最重要的三条边界**：
  1. **端口 23456 全局固定**，改端口要同步 Docker/bat/前端/文档全套。
  2. **`workers > 1` 时存储后端必须 SQLite/Postgres**，JSON 后端下多进程会丢账号数据。
  3. **改任何 API 字段后必须跑契约探测**：`scripts/contract_probe.py` + `test/test_contracts.py`。

## 前置假设（已按 "just draft it" 原则默认）

- 你在 Windows 上开发（bat 启动脚本仅 Windows；macOS/Linux 用 `python main.py`）。
- 你不会接触真实上游 OpenAI 账号——live 测试由项目方在内部跑。
- 交付走 git PR，CI（`.github/workflows/ci.yml`）四道质量门必须通过。
