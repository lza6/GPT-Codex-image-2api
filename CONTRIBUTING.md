# 贡献指南

## 代码风格

### Python（后端）

项目使用 ruff 进行代码检查，mypy 做类型检查。

```bash
# lint 检查
uv run ruff check .

# 自动修复
uv run ruff check --fix .

# 类型检查
uv run mypy services/ api/
```

**ruff 规则**：E/F/I/UP，line-length 120，target Python 3.13。

**编码约定**：
- 与所在文件现有风格一致（match, don't reform）
- 函数 < 50 行，文件 < 800 行；超过先拆分再提交
- 不可变模式：返回新对象，不就地改入参
- 错误显式处理，不静默吞异常（SSE 协程泄漏是历史教训）
- 中文注释/文档用简体中文；标识符一律英文

### TypeScript/JavaScript（前端）

```bash
# 类型检查
cd web && npm run build   # 构建时自动检查 tsc

# lint
cd web && npx eslint src/
```

**前端约定**：
- 组件 PascalCase，hooks 用 `use` 前缀
- 状态管理用 zustand，样式用 Tailwind v4
- 不引入新的状态管理库或 CSS 框架

---

## 分支命名

| 分支类型 | 格式 | 示例 |
|---------|------|------|
| 功能分支 | `feat/<简短描述>` | `feat/account-batch-import` |
| 修复分支 | `fix/<简短描述>` | `fix/image-download-404` |
| 重构分支 | `refactor/<简短描述>` | `refactor/config-schema` |
| 文档分支 | `docs/<简短描述>` | `docs/faq-contributing` |
| 性能分支 | `perf/<简短描述>` | `perf/usage-agg-cache` |
| 杂项分支 | `chore/<简短描述>` | `chore/update-deps` |

**规则**：
- 分支名全小写，单词用连字符分隔
- 描述要能看出意图，不要 `fix/abc123` 这种无意义名
- 从 `main` 分支创建功能分支

---

## 提交消息格式

```
<类型>: <描述>

<可选正文 - 动机、改动点、验证证据>
```

**类型**：feat / fix / refactor / docs / test / chore / perf / ci

**示例**：
```
feat: 支持账号密码批量导入

- 新增 /api/accounts/batch 端点，支持邮箱+密码批量导入
- 导入后自动触发登录，状态为"待登录"
- 前端新增批量导入对话框 UI
- 测试：test_batch_import 覆盖正常/重复/无效三种场景

测试：uv run pytest test/test_accounts.py -x 通过
```

**规则**：
- 第一行不超过 72 字符
- 正文可选，但复杂改动必须写动机和验证证据
- 单 PR 单职责；不夹带无关重构
- 发现无关问题（死代码、文档过期）→ 在 PR 里提一句，**不要顺手改**

---

## PR 流程

### 1. 创建 PR 前

```bash
# 确保分支与 main 同步
git fetch origin
git rebase origin/main

# 运行质量门禁
uv run ruff check .          # lint：新代码零新增告警
uv run mypy services/ api/   # 类型：不引入新错误
uv run pytest                # 测试：默认集全绿
uv run pip-audit             # 安全：无新增高危漏洞

# 动过前端才需要
cd web && npm run build      # tsc 0 错误 + 构建通过

# 改动涉及 API 字段时追加
uv run pytest test/test_contracts.py
```

### 2. 创建 PR

- 标题：`<类型>: <描述>`（与提交消息格式一致）
- 正文包含：
  - 改动动机
  - 改动点摘要
  - 测试计划与结果
  - 截图（涉及 UI 改动）
- 标注修改风险分区（见下方风险分区）

### 3. 代码审查

PR 创建后，至少有一人审查通过才能合并。审查标准：
- **CRITICAL**：安全漏洞或数据丢失风险 → 必须修复，阻止合并
- **HIGH**：Bug 或重大质量问题 → 应修复，阻止合并
- **MEDIUM**：可维护性问题 → 考虑修复
- **LOW**：风格或次要建议 → 可选

### 4. 合并

- 使用 squash merge 保持 main 提交历史整洁
- 合并后删除功能分支

---

## 测试要求

### 覆盖率目标

最低测试覆盖率：**80%**。

### 测试类型

| 类型 | 工具 | 覆盖内容 |
|------|------|---------|
| 单元测试 | pytest | 单个函数、工具、服务模块 |
| 集成测试 | pytest + httpx | API 端点、数据库操作 |
| 契约测试 | pytest + contract_probe | API 字段一致性 |
| E2E 测试 | pytest（-m live） | 关键用户流程（本地手动跑） |

### TDD 工作流（强制）

```
1. 写测试（RED）     → 运行 → 应失败
2. 写实现（GREEN）   → 运行 → 应通过
3. 重构（IMPROVE）   → 运行 → 仍通过
4. 验证覆盖率 ≥ 80%
```

### 测试运行

```bash
# 默认集（CI 用，不触网）
uv run pytest

# 单文件调试
uv run pytest test/xxx.py -v

# 实网测试（本地手动运行）
uv run pytest -m live

# 纯单元测试
uv run pytest -m unit

# 契约测试
uv run pytest test/test_contracts.py
```

### 测试编写规范

- 遵循 AAA 模式（Arrange-Act-Assert）
- 测试文件以 `test_` 前缀命名，放在 `test/` 目录
- 不触网：mock 外部依赖，确保默认集无网络调用
- 测试不依赖执行顺序，每个测试独立可重复

---

## 修改风险分区

### 自由区（正常 PR）

- `web/src/` 前端页面、样式、交互、新组件（不改 API 字段名）
- 新增测试（`test/`）、文档（`docs/`）
- 新增 `utils/` 工具函数（不改既有签名）
- `services/` 新增独立服务模块（经 factory/依赖注入接入）

### 协调区（PR 描述里必须论证）

- 调度算法（`account_service.py`）、熔断状态机（`circuit_breaker.py`）行为变更
- 存储接口（`storage/base.py`）签名变更 —— 4 个后端全量回归
- config.json 字段删除/改名 —— 同步 schema 校验 + `.env.example` + compose 注释
- 中间件装配顺序（`api/app.py`）
- 端口、worker 数等部署级常量

### 禁区（永远不做）

- 删除 README 免责声明（逆向项目合规底线）
- 提交 `config.json`、`data/`、`.env`（gitignore 已挡，不要 force add）
- 硬编码任何密钥/账号凭据
- 把 bat 脚本转存为 UTF-8（必须 GBK + CRLF + 无 BOM）
- 引入新状态管理库 / 新 CSS 框架（前端栈已固定：zustand + Tailwind v4）
- 模块级可变全局变量跨请求持有（多 Worker 安全红线）
- 商业/批量/滥用用途的任何改动（项目定位：逆向研究）

---

## 文档同步点

| 改了什么 | 同步哪里 |
|---------|---------|
| API 字段/端点 | `docs/api/openapi.yaml` + `docs/api/examples.md` + 契约双验证 |
| config.json 结构 | `services/config.py` schema + `.env.example` + compose 注释 |
| 重大选型 | `docs/adr/`（新增 ADR 并登记 index.md） |
| 版本号/变更 | `VERSION` + `CHANGELOG.md` |

---

## CI 质量门

| Job | 步骤 | 阻断性 |
|-----|------|--------|
| backend-quality | ruff check | 暂 `continue-on-error`，新代码必须零新增告警 |
| backend-quality | mypy | 同上 |
| backend-quality | pytest（排除 live/redis） | **硬阻断** |
| backend-quality | pip-audit | 暂 `continue-on-error` |
| frontend-build | tsc --noEmit | **硬阻断** |
| frontend-build | npm run build | **硬阻断** |

镜像发布：`.github/workflows/docker-publish.yml` → `ghcr.io/basketikun/chatgpt2api:latest`。

---

## 上下文中工具

按序优先使用（项目约定）：
1. **graft**（本仓库已索引）：`graft ask "<问题>" --source` 定位 + 内联代码；`graft callers <符号>` 看影响面；`graft grep "<字面量>"` 穷举；改完 `graft build` 刷新
2. **codegraph MCP**（`.codegraph/` 存在时）：结构性问题用 `codegraph_context` / `codegraph_callers`
3. Grep/Read 仅在上述未覆盖时使用