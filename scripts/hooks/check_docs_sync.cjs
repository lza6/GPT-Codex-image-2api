#!/usr/bin/env node
/**
 * 文档保鲜 pre-commit 钩子执行器（VII-03）。
 *
 * 调用 scripts/docs_sync_check.py 校验 VERSION 与核心文档内嵌版本一致，
 * 不一致则让 git 拒绝本次提交（防「bump VERSION 漏同步文档」P0 复现）。
 *
 * 环境降级策略：
 *   - 找到 .venv 的 python → 执行校验，不一致 exit 1（阻塞提交）；
 *   - 找不到 python → 打印警告并 exit 0（不阻塞，CI/run_all_guards 兜底）。
 *
 * 安装（一次性）：
 *   node scripts/hooks/install.cjs      # 设置 git config core.hooksPath
 * 卸载：
 *   git config --unset core.hooksPath
 */
"use strict";

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");

function findPython() {
  const candidates = [
    path.join(ROOT, ".venv", "Scripts", "python.exe"), // Windows
    path.join(ROOT, ".venv", "bin", "python"), // POSIX
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function main() {
  const python = findPython();
  if (!python) {
    console.warn(
      "[docs-sync-hook] 未找到 .venv python，跳过提交前文档同步校验（CI/run_all_guards 已兜底）。"
    );
    process.exit(0);
  }

  const script = path.join(ROOT, "scripts", "docs_sync_check.py");
  const res = spawnSync(python, [script], {
    cwd: ROOT,
    encoding: "utf-8",
    stdio: "inherit",
  });

  if (res.error) {
    console.warn(`[docs-sync-hook] 执行 docs_sync_check.py 失败：${res.error.message}`);
    process.exit(1);
  }
  process.exit(res.status ?? 1);
}

main();
