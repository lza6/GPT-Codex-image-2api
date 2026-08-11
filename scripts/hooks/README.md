# 文档保鲜 git hook（VII-03）

在每次 `git commit` 前校验 `VERSION` 与核心文档（CLAUDE.md / workflow_status.md /
docs/verification-registry.md / SKILL.md）内嵌的版本号一致，防「bump VERSION 漏同步文档」
P0 复现。与 `scripts/docs_sync_check.py`（run_all_guards 第六道防线、CI guards job）同一套校验。

## 为什么是 git hook 而非 husky

仓库当前无 husky；为不扰动 `web/` 的 npm 依赖与 CI 构建管线（`npm ci` 会触发 prepare 脚本），
采用**提交入库的 githooks 目录 + `core.hooksPath`** 方案。钩子本体为 Node（Windows 禁 .sh）。

- `scripts/hooks/check_docs_sync.cjs` — Node 执行器，定位 .venv python 并调用 docs_sync_check.py
- `scripts/hooks/githooks/pre-commit` — 钩子入口（Node shebang，委托上面的执行器）
- `scripts/hooks/install.cjs` — 一次性安装脚本

## 安装 / 卸载

```bash
# 安装（在仓库根目录）
node scripts/hooks/install.cjs

# 卸载
git config --unset core.hooksPath
```

## 行为

- 找到 `.venv/Scripts/python.exe`（Windows）或 `.venv/bin/python`（POSIX）→ 执行校验，
  `docs_sync_check.py` 返回非 0 时**阻塞提交**，并提示同步哪些文档。
- 找不到 python → 打印警告并放行（不阻塞），由 CI guards job / run_all_guards 兜底。

## 注意

- 在 POSIX 克隆上，若 `core.hooksPath` 生效但钩子未被执行，请确保钩子文件有执行位：
  `git update-index --chmod=+x scripts/hooks/githooks/pre-commit`（Windows Git Bash 通常无此问题）。
- 本钩子是「文档保鲜」的本地增强；CI 侧由 `run_all_guards.py` 与 `.github/workflows/ci.yml`
  guards job 强制，二者不依赖本钩子安装。
