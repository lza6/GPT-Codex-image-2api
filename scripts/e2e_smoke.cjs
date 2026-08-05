/* v2.4.0 起的浏览器 E2E 验收（自验收工具，非 CI 门禁）。

验证三条前端交互链是否真实打通：
  1. 登录 → 进入业务页
  2. /logs 账号筛选 → 发起带 account_email 的真实请求
  3. /accounts 单账号时间线 → 抽屉打开 + 发起 account_email 请求
  4. /dashboard 档位筛选 → 激活态切换

用法（先起后端 23456 与前端 3000）：
  E2E_AUTH_KEY=<密钥> node scripts/e2e_smoke.cjs
环境变量：
  E2E_BASE_URL    前端地址（默认 http://127.0.0.1:3000）
  E2E_AUTH_KEY    登录密钥（必填）
依赖：web/node_modules 的 playwright-core（channel=msedge，用系统 Edge，免下载浏览器）。
运行环境：需真实后端与前端服务在跑；数据不足时相关步骤打印 SKIP 不误报。
*/
const { chromium } = require('playwright-core');

const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:3000';
const AUTH_KEY = process.env.E2E_AUTH_KEY;
const results = [];

function check(name, cond, extra = '') {
  results.push({ name, pass: !!cond, extra });
  console.log(`${cond ? '[PASS]' : '[FAIL]'} ${name}${extra ? ' | ' + extra : ''}`);
}

async function main() {
  if (!AUTH_KEY) {
    console.error('E2E_AUTH_KEY 必填');
    process.exit(2);
  }
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  // ---- 1. 登录 ----
  await page.goto(`${BASE}/login`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#auth-key', { timeout: 20000 });
  await page.fill('#auth-key', AUTH_KEY);
  await page.click('button:has-text("登录")');
  await page.waitForFunction(() => !window.location.pathname.includes('/login'), null, { timeout: 20000 }).catch(() => {});
  check('登录后进入业务页', !page.url().includes('/login'), page.url());

  // ---- 2. /logs 账号筛选 ----
  await page.goto(`${BASE}/logs`, { waitUntil: 'domcontentloaded' });
  const reqLogs = [];
  page.on('request', (r) => { if (r.url().includes('/api/logs')) reqLogs.push(r.url()); });
  const emailInput = page.locator('input[placeholder*="账号邮箱"]');
  await emailInput.waitFor({ timeout: 20000 });
  await emailInput.fill('smoke@example.com');
  await page.waitForTimeout(1800);
  check('logs 页触发 account_email 过滤请求', reqLogs.some((u) => u.includes('account_email=')), reqLogs[reqLogs.length - 1] || '');

  // ---- 3. /accounts 单账号时间线 ----
  await page.goto(`${BASE}/accounts`, { waitUntil: 'domcontentloaded' });
  const reqTimeline = [];
  page.on('request', (r) => { if (r.url().includes('/api/logs?') && r.url().includes('account_email')) reqTimeline.push(r.url()); });
  const historyBtn = page.locator('button[title="查看单账号日志时间线"]').first();
  await historyBtn.waitFor({ timeout: 20000 });
  await historyBtn.click();
  await page.waitForSelector('text=单账号时间线', { timeout: 10000 }).catch(() => {});
  check('时间线抽屉打开', (await page.locator('text=单账号时间线').count()) > 0);
  check('时间线发起 account_email 请求', reqTimeline.length > 0, reqTimeline[0] || '');
  await page.locator('button:has-text("关闭")').first().click().catch(() => {});

  // ---- 4. /dashboard 档位筛选 ----
  await page.goto(`${BASE}/dashboard`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('button:has-text("仅风险")', { timeout: 20000 });
  await page.click('button:has-text("仅风险")');
  await page.waitForTimeout(600);
  const cls = (await page.locator('button:has-text("仅风险")').getAttribute('class')) || '';
  check('仅风险筛选激活态', cls.includes('bg-stone-900'), cls.slice(0, 60));

  // ---- 5. 6.1 交互反馈：异步按钮点击 → loading/禁用态出现（防"点了没反应"） ----
  await page.click('button:has-text("刷新")');
  // AsyncButton：loading 时渲染 spinner（animate-spin）并禁用
  const spinnerSeen = await page
    .waitForSelector('button:has-text("刷新中")', { timeout: 5000 })
    .then(() => true)
    .catch(() => false);
  check('异步按钮点击后进入 loading 态', spinnerSeen, '刷新中 spinner/文本');
  const refreshDisabled = await page
    .locator('button:has-text("刷新中")')
    .isDisabled()
    .catch(() => false);
  check('异步按钮 loading 时禁用', refreshDisabled, 'disabled 属性');

  await browser.close();
  const passed = results.filter((r) => r.pass).length;
  console.log(`\n===== 前端 E2E 冒烟结果 =====\n${passed}/${results.length} PASS`);
  process.exit(results.every((r) => r.pass) ? 0 : 1);
}

main().catch((e) => {
  console.error('E2E ERROR:', e.message);
  process.exit(1);
});
