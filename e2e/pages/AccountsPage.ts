import { type Page, type Locator, expect } from "@playwright/test";

/**
 * 号池管理页面 Page Object Model
 */
export class AccountsPage {
  readonly page: Page;
  readonly heading: Locator;
  readonly refreshButton: Locator;
  readonly accountRows: Locator;
  readonly statusFilter: Locator;
  readonly searchInput: Locator;

  constructor(page: Page) {
    this.page = page;
    this.heading = page.getByRole("heading", { name: /号池管理/ });
    this.refreshButton = page.getByRole("button", { name: /一键刷新/ });
    this.accountRows = page.locator("table tbody tr");
    this.statusFilter = page.locator('button:has-text("状态")');
    this.searchInput = page.locator("input[placeholder*='搜索']");
  }

  async goto() {
    await this.page.goto("/accounts");
    // 账号页有 SSE/轮询持续请求，networkidle 永不满足——改用确定性等待标题
    await this.waitForLoad();
  }

  async isVisible(): Promise<boolean> {
    try {
      await expect(this.heading).toBeVisible({ timeout: 10_000 });
      return true;
    } catch {
      return false;
    }
  }

  async getAccountList(): Promise<{ email: string; status: string; tier: string }[]> {
    const rows = await this.accountRows.all();
    const result: { email: string; status: string; tier: string }[] = [];
    for (const row of rows) {
      const cells = await row.locator("td").all();
      // 根据实际表格列顺序提取
      const email = (await cells[0]?.textContent()) ?? "";
      const status = (await cells[2]?.textContent()) ?? "";
      const tier = (await cells[3]?.textContent()) ?? "";
      result.push({ email: email.trim(), status: status.trim(), tier: tier.trim() });
    }
    return result;
  }

  async refreshAccounts() {
    await this.refreshButton.click();
    // 等待刷新完成（进度条消失或账号列表更新）
    await this.page.waitForTimeout(2_000);
  }

  async filterByStatus(status: string) {
    await this.statusFilter.click();
    await this.page.getByRole("option", { name: status }).click();
  }

  async openTimeline(accountEmail: string) {
    // 找到该账号行的时间线按钮
    const row = this.accountRows.filter({ hasText: accountEmail });
    const timelineBtn = row.getByRole("button").filter({ has: this.page.locator(".lucide-history") });
    await timelineBtn.first().click();
    // 等待时间线弹窗/抽屉出现
    await expect(this.page.locator('[role="dialog"]')).toBeVisible({ timeout: 5_000 });
  }

  async waitForLoad() {
    await expect(this.heading).toBeVisible({ timeout: 15_000 });
  }
}