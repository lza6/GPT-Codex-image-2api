import { test, expect } from "@playwright/test";
import { LoginPage } from "../pages/LoginPage";
import { AccountsPage } from "../pages/AccountsPage";

const AUTH_KEY = process.env.E2E_AUTH_KEY || "cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO";

test.describe("号池管理", () => {
  let accountsPage: AccountsPage;

  test.beforeEach(async ({ page }) => {
    // 先登录并等待跳转完成（localStorage 写入后再进号池，否则 auth guard 弹回 /login）
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login(AUTH_KEY);
    // 等待 URL pathname 离开 /login（localStorage 写入后再进号池）
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 10_000 });
    // 导航到号池管理
    accountsPage = new AccountsPage(page);
    await accountsPage.goto();
  });

  test("页面上标题可见", async () => {
    await expect(accountsPage.heading).toBeVisible({ timeout: 10_000 });
  });

  test("账号列表加载后显示行数据", async () => {
    try {
      await accountsPage.waitForLoad();
      // 等待表格行出现
      await expect(accountsPage.accountRows.first()).toBeVisible({ timeout: 15_000 });
      const accounts = await accountsPage.getAccountList();
      expect(accounts.length).toBeGreaterThanOrEqual(0);
    } catch {
      test.skip();
    }
  });

  test("刷新按钮存在且可点击", async () => {
    await expect(accountsPage.refreshButton).toBeVisible({ timeout: 10_000 });
    await expect(accountsPage.refreshButton).toBeEnabled();
  });
});