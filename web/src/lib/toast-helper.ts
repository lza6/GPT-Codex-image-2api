"use client";

/**
 * Toast 工具函数 — 统一错误提取与展示。
 *
 * 设计约定（与 web/src/lib/request.ts 拦截器配套）：
 * - 拦截器不 toast；异步错误由调用方 catch 后经本工具的错误提取展示。
 * - 本工具不负责请求拦截器层的 toast（避免双重 toast 历史 bug）。
 *
 * 用法：
 * ```tsx
 * import { toastError, toastSuccess } from "@/lib/toast-helper";
 *
 * try {
 *   await riskyOperation();
 *   toastSuccess("操作成功");
 * } catch (error) {
 *   toastError(error, "操作失败");
 * }
 * ```
 */
import * as React from "react";
import { toast } from "sonner";

import { ProgressBar } from "@/components/ui/progress-bar";

/**
 * 从各种错误形态中提取用户可读消息。
 * 支持 Axios 错误（含 userMessage）、Error 实例、字符串、对象。
 */
export function extractErrorMessage(error: unknown, fallback = "操作失败"): string {
  if (typeof error === "string") return error;
  if (!error) return fallback;

  // Axios 拦截器挂载的 userMessage
  const axiosErr = error as { userMessage?: string };
  if (axiosErr.userMessage) return axiosErr.userMessage;

  // Error 实例
  if (error instanceof Error) return error.message;

  // 对象含 detail
  const objErr = error as { detail?: unknown };
  if (objErr.detail) {
    if (typeof objErr.detail === "string") return objErr.detail;
    const detailObj = objErr.detail as { message?: string; error?: string };
    if (detailObj.message) return detailObj.message;
    if (detailObj.error) return detailObj.error;
  }

  // 对象含 message
  const msgErr = error as { message?: string };
  if (msgErr.message) return msgErr.message;

  return fallback;
}

/**
 * 显示错误 Toast，自动提取错误消息。
 */
export function toastError(error: unknown, fallback?: string): void {
  toast.error(extractErrorMessage(error, fallback), { duration: 5000 });
}

/**
 * 显示成功 Toast。
 */
export function toastSuccess(message: string): void {
  toast.success(message, { duration: 3000 });
}

/**
 * 显示信息 Toast。
 */
export function toastInfo(message: string): void {
  toast.info(message, { duration: 3000 });
}

/**
 * 显示可撤销的 Toast。
 */
export function toastWithUndo(
  message: string,
  onUndo: () => void,
  options?: { duration?: number; label?: string },
): void {
  toast(message, {
    action: {
      label: options?.label ?? "撤销",
      onClick: onUndo,
    },
    duration: options?.duration ?? 5000,
  });
}

/**
 * 分组 Toast — 将相同 key 的 toast 合并为一条，显示计数。
 * 例如批量操作多条错误时，相同错误只显示一条并累加计数。
 */
const groupedToastMap = new Map<string, { count: number; dismiss: () => void }>();

export function groupedToast(key: string, message: string, type: "error" | "success" | "info" = "info"): void {
  const existing = groupedToastMap.get(key);
  if (existing) {
    existing.count += 1;
    const fn = type === "error" ? toast.error : type === "success" ? toast.success : toast.info;
    fn(`${message} (${existing.count})`, { id: key, duration: 4000 });
    return;
  }

  const fn = type === "error" ? toast.error : type === "success" ? toast.success : toast.info;
  fn(message, { id: key, duration: 4000 });
  groupedToastMap.set(key, {
    count: 1,
    dismiss: () => {
      toast.dismiss(key);
      groupedToastMap.delete(key);
    },
  });
  // 自动清理
  setTimeout(() => groupedToastMap.delete(key), 5000);
}

/**
 * 进度 Toast — 显示带进度条的 toast。
 * @returns 更新进度的函数
 */
export function progressToast(
  message: string,
  initialProgress = 0,
): { update: (progress: number, newMessage?: string) => void; dismiss: () => void } {
  const id = `progress-${Date.now()}`;
  let currentProgress = initialProgress;

  const render = () => {
    toast(
      React.createElement("div", { className: "flex flex-col gap-2" },
        React.createElement("span", { className: "text-sm text-stone-700 dark:text-stone-200" }, message),
        React.createElement(ProgressBar, { value: currentProgress, size: "sm", label: `${Math.round(currentProgress)}%` }),
      ),
      { id, duration: Infinity },
    );
  };

  render();

  return {
    update: (progress: number, newMessage?: string) => {
      currentProgress = progress;
      if (newMessage) message = newMessage;
      render();
      if (progress >= 100) {
        setTimeout(() => toast.dismiss(id), 1000);
      }
    },
    dismiss: () => toast.dismiss(id),
  };
}

/**
 * 位置定制 Toast — 可指定显示位置。
 */
export function toastPositioned(
  message: string,
  type: "success" | "error" | "info" = "info",
  position: "top-center" | "bottom-center" | "top-left" | "top-right" | "bottom-left" | "bottom-right" = "top-center",
): void {
  const fn = type === "error" ? toast.error : type === "success" ? toast.success : toast.info;
  fn(message, { position });
}