# 06 · 贡献指南（高级工程师版）

## 修改风险分区

### 🟢 自由区（正常 PR）
- `web/src/` 前端页面、样式、交互、新组件（不改 API 字段名）
- 新增测试（`test/`）、文档（`docs/`）
- 新增 `utils/` 工具函数（不改既有签名）
- `services/` 新增独立服务模块（经 factory/依赖注入接入）

### 🟡 协调区（PR 描述里必须论证）
- 调度算法（`account_service.py`）、熔断状态机（`circuit_breaker.py`）行为变更 —— 有 8/8 调度单测 + 熔断测试守护，改完必须全绿
- 存储接口（`storage/base.py`）签名变更 —— 4 个后端全量回归
- config.json 字段删除/改名 —— 同步 schema 校验 + `.env.example` + compose 注释
- 中间件装配顺序（`api/app.py`）
- 端口、worker 数等部署级常量

### 🔴 禁区（永远不做）
- 删除 README 免责声明（逆向项目合规底线）
- 提交 `config.json`、`data/`、`.env`（gitignore 已挡，不要 force add）
- 硬编码任何密钥/账号凭据
- 把 bat 脚本转存为 UTF-8（必须 GBK + CRLF + 无 BOM）
- 引入新状态管理库 / 新 CSS 框架（前端栈已固定：zustand + Tailwind v4）
- 模块级可变全局变量跨请求持有（多 Worker 安全红线）
- 商业/批量/滥用用途的任何改动（项目定位：逆向研究）

## 提交前验证清单

```bash
uv run ruff check .          # 1. lint：新代码零新增告警
uv run mypy services/ api/   # 2. 类型：别引入新错误
uv run pytest                # 3. 测试：默认集全绿（排除 live/redis）
uv run pip-audit             # 4. 安全：无新增高危漏洞
cd web && npm run build      # 5.（动过前端才需要）tsc 0 错误 + webpack 构建通过
```

改动涉及 API 字段时追加：

```bash
uv run pytest test/test_contracts.py
uv run python scripts/contract_probe.py   # 需活服务，跑不了就在 PR 里注明
```

## CI 质量门（`.github/workflows/ci.yml`）

| Job | 步骤 | 阻断性 |
|-----|------|--------|
| backend-quality | ruff check | 暂 `continue-on-error`（存量清零中），**新代码必须零新增告警** |
| backend-quality | mypy | 同上 |
| backend-quality | pytest `-m "not live and not redis"` | **硬阻断** |
| backend-quality | pip-audit | 暂 `continue-on-error` |
| frontend-build | `tsc --noEmit` | **硬阻断** |
| frontend-build | `npm run build`（webpack） | **硬阻断** |

镜像发布：`.github/workflows/docker-publish.yml` → `ghcr.io/basketikun/chatgpt2api:latest`。

## 代码风格

- 与所在文件现有风格一致（match, don't reform）
- 函数 < 50 行，文件 < 800 行；超过先拆分再提交
- 不可变模式：返回新对象，不就地改入参
- 错误显式处理，不静默吞异常（SSE 协程泄漏是历史教训）
- 中文注释/文档用简体中文；标识符一律英文
- ruff 规则：E/F/I/UP，line-length 120，target py313

## 提交与 PR 约定

- 提交格式：`<type>: <描述>`（feat/fix/refactor/docs/test/chore/perf/ci），参照 git log 既有风格
- 正文：动机、改动点、验证证据（测试输出/截图/curl 结果）
- 单 PR 单职责；不夹带无关重构
- 发现无关问题（死代码、文档过期）→ 在 PR 里提一句，**不要顺手改**

## 文档同步点（改动时必查）

| 改了什么 | 同步哪里 |
|---------|---------|
| API 字段/端点 | `docs/api/openapi.yaml` + `docs/api/examples.md` + 契约双验证 |
| config.json 结构 | `services/config.py` schema + `.env.example` + compose 注释 + onboarding 03 章 |
| 节点行为（N1–N17 跟踪项） | `workflow_status.md` |
| 版本号/变更 | `VERSION` + `CHANGELOG.md` |
| 重大选型 | `docs/adr/`（新增 ADR 并登记 index.md） |
| 代码结构 | `graft build` 刷新索引 |

## 上下文工具（项目约定，按序优先）

1. **graft**（本仓库已索引）：`graft ask "<问题>" --source` 定位 + 内联代码；`graft callers <符号>` 看影响面；`graft grep "<字面量>"` 穷举；改完 `graft build` 刷新
2. **codegraph MCP**（`.codegraph/` 存在时）：结构性问题用 `codegraph_context` / `codegraph_callers`
3. Grep/Read 仅在上述未覆盖时使用
