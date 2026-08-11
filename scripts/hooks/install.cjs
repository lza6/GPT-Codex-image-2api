#!/usr/bin/env node
/**
 * 一次性安装文档保鲜 git hook（VII-03）：
 *   node scripts/hooks/install.cjs
 *
 * 执行 `git config core.hooksPath scripts/hooks/githooks`，让仓库使用提交入库的
 * pre-commit 钩子。卸载：`git config --unset core.hooksPath`。
 */
"use strict";

const { spawnSync } = require("node:child_process");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "../..");
const hooksRel = path.relative(ROOT, path.join(__dirname, "githooks")).split(path.sep).join("/");

const res = spawnSync("git", ["config", "core.hooksPath", hooksRel], {
  cwd: ROOT,
  stdio: "inherit",
  shell: process.platform === "win32",
});
if (res.status === 0) {
  console.log(`[docs-sync-hook] 已安装 core.hooksPath=${hooksRel}`);
  console.log("[docs-sync-hook] 后续每次 git commit 会先校验 VERSION 与文档版本一致性。");
} else {
  console.error("[docs-sync-hook] 安装失败，请手动执行：git config core.hooksPath scripts/hooks/githooks");
}
process.exit(res.status ?? 1);
