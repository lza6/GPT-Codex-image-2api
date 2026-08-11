import { type Page, type Locator, expect } from "@playwright/test";

/**
 * 设置页面 Page Object Model
 */
export class SettingsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly basicTab: Locator;
  readonly saveButton: Locator;
  readonly proxyInput: Locator;
  readonly baseUrlInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "设置" });
    this.basicTab = page.getByRole("tab", { name: "基础配置" });
    this.saveButton = page.getByRole("button", { name: /保存/ });
    this.proxyInput = page.locator('input[id*="proxy"]');
    this.baseUrlInput = page.locator('input[id*="base-url"]');
  }

  async goto() {
    await this.page.goto("/settings");
    await this.page.waitForLoadState("networkidle");
  }

  async isVisible(): Promise<boolean> {
    try {
      // 设置页面 Tabs 在加载完成后可见
      await expect(this.basicTab).toBeVisible({ timeout: 10_000 });
      return true;
    } catch {
      return false;
    }
  }

  async getConfigValue(key: string): Promise<string> {
    // 根据字段标识读取对应 input 的值
    const input = this.page.locator(`input[id*="${key}"]`);
    await expect(input).toBeVisible({ timeout: 5_000 });
    return (await input.inputValue()) ?? "";
  }

  async setConfigValue(key: string, value: string) {
    const input = this.page.locator(`input[id*="${key}"]`);
    await expect(input).toBeVisible({ timeout: 5_000 });
    await input.fill(value);
  }

  async save() {
    await this.saveButton.click();
    // 保存后等待 toast 成功提示
    await expect(this.page.locator("[data-sonner-toaster] [data-title]")).toBeVisible({ timeout: 10_000 });
  }

  async waitForLoad() {
    await expect(this.basicTab).toBeVisible({ timeout: 15_000 });
  }
}