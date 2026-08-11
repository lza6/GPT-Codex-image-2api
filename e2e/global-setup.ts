/**
 * 全局 setup：启动后端和前端服务，等待服务就绪后执行认证预登录。
 *
 * 注意：此文件作为 globalSetup 运行，不在浏览器上下文中。
 */
import { type FullConfig } from "@playwright/test";
import { spawn, type ChildProcess } from "child_process";
import * as http from "http";
import { resolve } from "path";

const PROJECT_ROOT = resolve(__dirname, "..");
const BACKEND_PORT = 23456;
const FRONTEND_PORT = 3000;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const FRONTEND_URL = `http://localhost:${FRONTEND_PORT}`;

/** 轮询等待 HTTP 服务返回 200 */
function waitForUrl(url: string, timeoutMs = 60_000): Promise<void> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const poll = () => {
      if (Date.now() - start > timeoutMs) {
        reject(new Error(`Timeout waiting for ${url}`));
        return;
      }
      http
        .get(url, (res) => {
          if (res.statusCode === 200) {
            resolve();
          } else {
            setTimeout(poll, 1_000);
          }
        })
        .on("error", () => setTimeout(poll, 1_000));
    };
    poll();
  });
}

/**
 * 启动后端服务（python main.py）
 */
function startBackend(): ChildProcess {
  const proc = spawn("python", ["main.py"], {
    cwd: PROJECT_ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
    shell: true,
  });
  proc.stdout?.on("data", (data: Buffer) => {
    process.stdout.write(`[backend] ${data.toString()}`);
  });
  proc.stderr?.on("data", (data: Buffer) => {
    process.stderr.write(`[backend] ${data.toString()}`);
  });
  return proc;
}

/**
 * 启动前端服务（npm run dev）
 */
function startFrontend(): ChildProcess {
  const proc = spawn("npm", ["run", "dev"], {
    cwd: resolve(PROJECT_ROOT, "web"),
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env },
    shell: true,
  });
  proc.stdout?.on("data", (data: Buffer) => {
    process.stdout.write(`[frontend] ${data.toString()}`);
  });
  proc.stderr?.on("data", (data: Buffer) => {
    process.stderr.write(`[frontend] ${data.toString()}`);
  });
  return proc;
}

export default async function globalSetup(_config: FullConfig) {
  console.log("--- Global Setup: Starting services ---");

  // 启动后端
  const backendProc = startBackend();
  console.log("Waiting for backend...");
  await waitForUrl(`${BACKEND_URL}/health`).catch(() => {
    // 后端可能没有 /health 端点，尝试 /api/dashboard
    return waitForUrl(`${BACKEND_URL}/api/dashboard/scheduler`);
  });
  console.log("Backend is ready.");

  // 启动前端
  const frontendProc = startFrontend();
  console.log("Waiting for frontend...");
  await waitForUrl(FRONTEND_URL);
  console.log("Frontend is ready.");

  // 保持进程运行
  process.on("exit", () => {
    backendProc.kill();
    frontendProc.kill();
  });
  process.on("SIGINT", () => {
    backendProc.kill();
    frontendProc.kill();
    process.exit(0);
  });
  process.on("SIGTERM", () => {
    backendProc.kill();
    frontendProc.kill();
    process.exit(0);
  });

  console.log("--- Global Setup: Complete ---");
}