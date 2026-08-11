// 测量各路由页面首屏 JS 的 gzip 大小（基于 out/ 静态导出的 HTML script 引用）。
// 用法: node scripts/bundle-size.mjs [pagePaths...] [--grep=字符串]
// 默认页面: index dashboard accounts logs image-manager image settings
import { readFileSync, statSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import zlib from "node:zlib";

const root = process.cwd().endsWith("web") ? process.cwd() : join(process.cwd(), "web");
const outDir = join(root, "out");
const staticDir = join(outDir, "_next", "static");

function gzipSize(file) {
  const buf = readFileSync(file);
  return zlib.gzipSync(buf).length;
}

function human(n) {
  return n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`;
}

const grepArg = process.argv.find((a) => a.startsWith("--grep="));
const grep = grepArg ? grepArg.slice("--grep=".length) : null;

const pagePaths = process.argv
  .slice(2)
  .filter((a) => !a.startsWith("--") && !a.endsWith("bundle-size.mjs"));
const targets = pagePaths.length ? pagePaths : ["index", "dashboard", "accounts", "logs", "image-manager", "image", "settings"];

for (const p of targets) {
  const rel = p === "index" ? "index.html" : `${p}/index.html`;
  const htmlFile = join(outDir, rel);
  if (!existsSync(htmlFile)) {
    console.log(`[${p}] 缺 HTML: ${htmlFile}`);
    continue;
  }
  const html = readFileSync(htmlFile, "utf8");
  const srcs = [...html.matchAll(/<script[^>]*src="([^"]+)"/g)].map((m) => m[1]);
  let total = 0;
  const lines = [];
  for (const src of srcs) {
    const file = join(outDir, src.replace(/^\//, ""));
    if (!existsSync(file)) continue;
    const size = gzipSize(file);
    total += size;
    lines.push(`  ${size}\t${human(size)}\t${src}`);
  }
  console.log(`\n==== ${p} — 首屏脚本 ${lines.length} 个, gzip 合计 ${human(total)} ====`);
  lines.sort((a, b) => parseInt(b) - parseInt(a));
  console.log(lines.join("\n"));

  if (grep) {
    const matches = [];
    for (const src of srcs) {
      const file = join(outDir, src.replace(/^\//, ""));
      if (!existsSync(file)) continue;
      try {
        const content = readFileSync(file, "utf8");
        if (content.includes(grep)) {
          matches.push(`${src} (${human(gzipSize(file))})`);
        }
      } catch {
        /* ignore */
      }
    }
    if (matches.length) {
      console.log(`  --- 含 "${grep}" 的 chunk ---`);
      for (const m of matches) console.log(`  ${m}`);
    } else {
      console.log(`  --- 未找到含 "${grep}" 的 chunk ---`);
    }
  }
}

// 全部 chunks 汇总（去重）供总览
const allChunks = new Set();
const walk = (dir) => {
  for (const name of readdirSync(dir)) {
    const f = join(dir, name);
    if (statSync(f).isDirectory()) walk(f);
    else if (name.endsWith(".js")) allChunks.add(f);
  }
};
if (existsSync(staticDir)) {
  walk(staticDir);
  let total = 0;
  for (const f of allChunks) total += gzipSize(f);
  console.log(`\n==== 全部静态 chunk（${allChunks.size} 个）gzip 合计 ${human(total)} ====`);
}
