import { test as base, type Page } from "@playwright/test";
import { LoginPage } from "../pages/LoginPage";

/**
 * 认证相关 fixture：自动登录
 */
export type AuthFixtures = {
  /** 已登录的页面（admin 角色） */
  authedAdminPage: Page;
  /** 已登录的页面（user 角色） */
  authedUserPage: Page;
};

export const test = base.extend<AuthFixtures>({
  authedAdminPage: async ({ browser }, use) => {
    const context = await browser.newContext({ storageState: "e2e/.auth/admin.json" });
    const page = await context.newPage();
    await use(page);
    await context.close();
  },

  authedUserPage: async ({ browser }, use) => {
    const context = await browser.newContext({ storageState: "e2e/.auth/user.json" });
    const page = await context.newPage();
    await use(page);
    await context.close();
  },
});

export { expect } from "@playwright/test";