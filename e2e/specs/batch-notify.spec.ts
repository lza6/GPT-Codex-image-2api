import { test, expect } from "@playwright/test";
import { LoginPage } from "../pages/LoginPage";

/**
 * 批量操作增强 + 通知中心 E2E 测试
 *
 * 覆盖 5.2.2 批量操作增强 + 5.2.3 通知中心：
 * 1. 通知中心铃铛入口可见（header-actions 挂载）
 * 2. 通知中心下拉：分类 tab / 空状态 / 偏好设置
 * 3. /notifications 历史页面：标题 + 偏好设置 + 筛选
 * 4. 账号页批量操作工具栏存在
 */
const AUTH_KEY = process.env.E2E_AUTH_KEY || "cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO";

test.describe("批量操作增强 + 通知中心 E2E", () => {
  test.beforeEach(async ({ page }) => {
    // 登录
    const loginPage = new LoginPage(page);
    await loginPage.goto();
    await loginPage.login(AUTH_KEY);
    await page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 10_000 });
  });

  test("通知中心铃铛入口可见并可展开分类", async ({ page }) => {
    // 铃铛按钮在 header-actions 中（移动端/桌面端各渲染一个，CSS 互斥显示，取可见的那个）
    const bellButton = page.locator('button[aria-label="通知"]:visible').first();
    await expect(bellButton).toBeVisible({ timeout: 10_000 });

    // 点击展开通知中心
    await bellButton.click();

    // 标题「通知」可见
    await expect(page.getByText("通知", { exact: true }).first()).toBeVisible({ timeout: 5_000 });

    // 分类 tab 全部可见：全部/系统通知/告警通知/操作结果/偏好
    await expect(page.getByRole("button", { name: "全部", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "系统通知", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "告警通知", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "操作结果", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "偏好", exact: true })).toBeVisible();

    // 底部「查看全部历史」链接存在（指向 /notifications）
    const historyLink = page.locator('a[href="/notifications"]');
    await expect(historyLink).toBeVisible();
  });

  test("通知中心偏好设置 tab 可交互", async ({ page }) => {
    await page.locator('button[aria-label="通知"]:visible').first().click();

    // 切到偏好 tab
    await page.getByRole("button", { name: "偏好", exact: true }).click();

    // 偏好面板显示三类通知偏好
    await expect(page.getByText("系统通知", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("告警通知", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("操作结果", { exact: true }).first()).toBeVisible();

    // 偏好项 checkbox 存在（弹 Toast / 进通知中心）
    const checkboxes = page.locator('input[type="checkbox"]');
    const count = await checkboxes.count();
    expect(count).toBeGreaterThanOrEqual(6); // 3 类 × 2 项
  });

  test("/notifications 历史页面加载正常且含偏好设置", async ({ page }) => {
    await page.goto("/notifications");
    await page.waitForLoadState("networkidle");

    // 页面标题
    await expect(page.getByRole("heading", { name: "通知中心" })).toBeVisible({ timeout: 10_000 });

    // 偏好设置区块
    await expect(page.getByText("通知偏好设置").first()).toBeVisible();

    // 类型 tab：全部/系统/告警/操作结果
    await expect(page.getByRole("tab", { name: "全部" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "系统" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "告警" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "操作结果" })).toBeVisible();

    // 全部已读/清空按钮
    await expect(page.getByRole("button", { name: "全部已读" })).toBeVisible();
    await expect(page.getByRole("button", { name: "清空" })).toBeVisible();
  });

  test("账号页批量操作工具栏可见", async ({ page }) => {
    await page.goto("/accounts");
    // 账号页有 SSE/轮询持续请求，networkidle 永不满足——确定性等待批量工具栏
    await expect(page.getByRole("button", { name: /批量驱逐失效/ })).toBeVisible({ timeout: 15_000 });

    await expect(page.getByRole("button", { name: /批量打标签/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /导出选中/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /删除所选/ })).toBeVisible();
  });
});
