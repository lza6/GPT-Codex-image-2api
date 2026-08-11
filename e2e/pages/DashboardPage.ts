import { type Page, type Locator, expect } from "@playwright/test";

/**
 * 运维看板页面 Page Object Model
 */
export class DashboardPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly refreshButton: Locator;
  readonly metricCards: Locator;
  readonly tierFilterSelect: Locator;
  readonly schedulerTable: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: "运维看板" });
    this.refreshButton = page.getByRole("button", { name: /刷新/ });
    this.metricCards = page.locator(".rounded-xl.border-stone-200.bg-white");
    this.tierFilterSelect = page.locator('button:has-text("全部")');
    this.schedulerTable = page.locator("table");
  }

  async goto() {
    await this.page.goto("/dashboard");
    // 看板 h1 在 9 个 API 请求完成后才渲染，等待标题出现（默认 15s）
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
    await this.page.waitForLoadState("networkidle");
  }

  async isVisible(): Promise<boolean> {
    try {
      await expect(this.heading).toBeVisible({ timeout: 10_000 });
      return true;
    } catch {
      return false;
    }
  }

  async getMetricCards(): Promise<{ label: string; value: string }[]> {
    const cards = await this.metricCards.all();
    const result: { label: string; value: string }[] = [];
    for (const card of cards) {
      const labelEl = card.locator("span.text-xs.font-medium");
      const valueEl = card.locator("p.mt-2");
      if ((await labelEl.count()) > 0 && (await valueEl.count()) > 0) {
        result.push({
          label: (await labelEl.textContent()) ?? "",
          value: (await valueEl.textContent()) ?? "",
        });
      }
    }
    return result;
  }

  async waitForLoad() {
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
    // 等待至少一个统计卡片加载
    await expect(this.metricCards.first()).toBeVisible({ timeout: 15_000 });
  }

  async selectTierFilter(filter: "全部" | "风险+温存" | "仅风险") {
    await this.tierFilterSelect.click();
    await this.page.getByRole("option", { name: filter }).click();
  }
}