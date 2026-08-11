import { type Page, type Locator, expect } from "@playwright/test";

/**
 * 登录页面 Page Object Model
 */
export class LoginPage {
  readonly page: Page;
  readonly authKeyInput: Locator;
  readonly submitButton: Locator;
  readonly errorToast: Locator;
  readonly heading: Locator;

  constructor(page: Page) {
    this.page = page;
    this.authKeyInput = page.locator("#auth-key");
    this.submitButton = page.getByRole("button", { name: "登录" });
    this.errorToast = page.locator("[data-sonner-toaster] [data-title]").first();
    this.heading = page.getByRole("heading", { name: "欢迎回来" });
  }

  async goto() {
    await this.page.goto("/login");
    await this.page.waitForLoadState("networkidle");
  }

  async login(authKey: string) {
    await this.authKeyInput.fill(authKey);
    await this.submitButton.click();
  }

  async isLoggedIn(): Promise<boolean> {
    try {
      // 登录成功后会跳转到看板（admin）或生图（user），URL pathname 不再是 /login
      await this.page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 5_000 });
      return true;
    } catch {
      return false;
    }
  }

  async getErrorMessage(): Promise<string> {
    // toast 错误消息
    await expect(this.errorToast).toBeVisible({ timeout: 5_000 });
    return (await this.errorToast.textContent()) ?? "";
  }

  async waitForLoad() {
    await expect(this.heading).toBeVisible({ timeout: 10_000 });
  }
}