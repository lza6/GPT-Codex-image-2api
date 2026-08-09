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
import { toast } from "sonner";

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
  toast.error(extractErrorMessage(error, fallback));
}

/**
 * 显示成功 Toast。
 */
export function toastSuccess(message: string): void {
  toast.success(message);
}

/**
 * 显示信息 Toast。
 */
export function toastInfo(message: string): void {
  toast.info(message);
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