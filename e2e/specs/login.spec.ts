import { test, expect } from "@playwright/test";
import { LoginPage } from "../pages/LoginPage";

test.describe("登录页面", () => {
  let loginPage: LoginPage;

  test.beforeEach(async ({ page }) => {
    loginPage = new LoginPage(page);
    await loginPage.goto();
  });

  test("登录页面加载正常", async () => {
    await loginPage.waitForLoad();
    // 验证页面元素可见
    await expect(loginPage.authKeyInput).toBeVisible();
    await expect(loginPage.submitButton).toBeVisible();
    // 提交按钮初始状态为可用（非禁用）
    await expect(loginPage.submitButton).toBeEnabled();
  });

  test("空密钥提交不崩溃", async ({ page }) => {
    // 不输入任何内容直接点击登录
    await loginPage.submitButton.click();
    // 页面不应跳转，仍停留在登录页
    await expect(page).toHaveURL(/\/login/);
    // 输入框仍可见
    await expect(loginPage.authKeyInput).toBeVisible();
  });

  test("无效密钥显示错误", async ({ page }) => {
    // 提交无效密钥
    await loginPage.login("invalid-key-12345");
    // 不应跳转
    await expect(page).toHaveURL(/\/login/);
    // 应有错误提示（toast）
    const errorMsg = await loginPage.getErrorMessage();
    expect(errorMsg.length).toBeGreaterThan(0);
    // 仍可继续输入
    await expect(loginPage.authKeyInput).toBeVisible();
  });

  test("空格输入不崩溃", async ({ page }) => {
    await loginPage.authKeyInput.fill("   ");
    await loginPage.submitButton.click();
    // 不应跳转
    await expect(page).toHaveURL(/\/login/);
  });

  test("输入框接受键盘输入", async () => {
    await loginPage.authKeyInput.fill("sk-test-key");
    await expect(loginPage.authKeyInput).toHaveValue("sk-test-key");
  });

  test("按 Enter 键触发登录", async ({ page }) => {
    // 输入后按 Enter 应触发登录尝试
    await loginPage.authKeyInput.fill("enter-test-key");
    await loginPage.authKeyInput.press("Enter");
    // 页面不应立即跳转（无效密钥），应显示错误
    await expect(page).toHaveURL(/\/login/);
  });
});