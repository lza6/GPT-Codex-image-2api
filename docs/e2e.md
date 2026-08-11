# E2E 测试（Playwright）

真实浏览器验证前端交互链：自动拉起真实后端（23456）+ 前端（3000），用本机 Edge 跑登录/看板/账号/批量通知 4 个 spec。相比 `scripts/e2e_smoke.cjs`（轻量 10 断言冒烟），这是完整 Playwright 体系：Page Object + 失败截图/视频 + HTML 报告，更适合回归。

## 前置条件

- Node.js 20+（e2e/ 有独立依赖，不依赖 web/）
- 本机 **Microsoft Edge**（`playwright.config.ts` 用 `channel: "msedge"` + Windows 硬编码路径）
- 后端 `python main.py`（23456）与前端 `cd web && npm run dev`（3000）可正常启动——**global-setup 会自动拉起，无需手动起**
- 登录 key 与后端 auth-key 一致：登录取 `E2E_AUTH_KEY` 环境变量，默认 `cg2api-8tbkFwuqBPLZ2cUuA12f8Ldvt2mkYNlO`，必须等于 `config.json` 的 `auth-key`（或 `CHATGPT2API_AUTH_KEY` 环境变量覆盖值），否则登录断言失败

## 快速开始

```bash
cd e2e
npm install                  # 首次安装（@playwright/test + dotenv + typescript）
npm test                     # 跑全部：自动起前后端，结束后随进程退出清理
npm run test:headed          # 有头模式（可观察浏览器）
npm run report               # 打开 HTML 报告（playwright-report/）
```

单文件 / 单用例：

```bash
npx playwright test specs/login.spec.ts
npx playwright test specs/login.spec.ts -g "空密钥提交不崩溃"
```

## 结构

```
e2e/
├── playwright.config.ts   # testDir / globalSetup / 单 worker / msedge / 产物配置（已含 CI 开关）
├── global-setup.ts        # 起后端+前端、轮询等就绪、进程清理钩子
├── fixtures/auth.ts       # 认证数据（E2E_AUTH_KEY）
├── pages/                 # Page Object：LoginPage / DashboardPage / AccountsPage / SettingsPage
├── specs/                 # 用例：login / dashboard / accounts / batch-notify
├── package.json           # test / test:headed / report 脚本
└── tsconfig.json
```

## 覆盖范围

| spec | 覆盖 |
|------|------|
| login | 页面加载 / 空密钥不崩溃 / 无效密钥报错 / 空格输入 / 键盘输入 / Enter 触发登录 |
| dashboard | 页面标题 / 指标卡片 / 刷新按钮可点 / 调度排行榜表格 |
| accounts | 页面标题 / 账号列表加载出行 / 刷新按钮存在可点 |
| batch-notify | 通知中心铃铛入口展开 / 偏好 tab 交互 / /notifications 历史页 / 账号页批量工具栏 |

## 产物与清理

- 失败截图/视频在 `test-results/`，HTML 报告在 `playwright-report/`（两者均已加入 .gitignore）
- global-setup 在进程退出时 kill 前后端子进程；若偶发残留，用 `停止chatgpt2api.bat` 或 `taskkill` 清理
- E2E 期间产生的测试数据在 `data/`（如 usage_agg.json），删掉下次启动会自动重建

## 与 CI 的关系

`playwright.config.ts` 已为 CI 就绪：`forbidOnly: !!process.env.CI`（禁 only）、`retries: CI ? 2 : 0`、`workers: 1`。

**当前不进 GitHub Actions**：E2E 依赖本机 Edge（`channel: "msedge"` 硬编码 Windows 路径），而 CI runner 是 `ubuntu-latest` 无 Edge。这与 `-m live` 测试一致——作为**本地 / 部署前真实链路验证工具**。若将来需要进 CI：改用自托管 Windows runner，或把 `channel` 改为 `chromium` 并在 CI 里 `npx playwright install chromium` 装浏览器。

## 稳定性约定

- 账号页/看板页有 SSE 与轮询请求，`waitForLoadState("networkidle")` 永不满足——**禁止用它等页面**，改用确定性 locator 等待（如批量工具栏按钮 `toBeVisible`）
- 后端 `-m live` 联网测试同理默认排除，E2E 只验证真实前后端交互，不依赖上游可达
