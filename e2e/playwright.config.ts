import { defineConfig, devices } from "@playwright/test";
import { config } from "dotenv";
import { resolve } from "path";

// 加载项目根目录 .env（如有）
config({ path: resolve(__dirname, "..", ".env") });

export default defineConfig({
  testDir: "./specs",
  // 起真实后端(23456)+前端(3000)并等待就绪，测试结束后随进程退出清理
  globalSetup: "./global-setup.ts",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },

  reporter: [
    ["html", { outputFolder: "playwright-report" }],
    ["list"],
  ],

  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        channel: "msedge",
        launchOptions: {
          executablePath:
            "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        },
      },
      dependencies: [],
    },
  ],
});