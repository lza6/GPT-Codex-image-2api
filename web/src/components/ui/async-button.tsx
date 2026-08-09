"use client";

/**
 * 增强版异步按钮 — 自带 success/error 状态机与反馈闭环。
 *
 * 状态流：
 *   idle → loading → success (2s 自动回 idle)
 *                   → error   (5s 自动回 idle)
 *
 * 使用示例：
 * ```tsx
 * <AsyncButton
 *   action={refreshAccount}
 *   onSuccess={() => showToast("刷新成功")}
 *   onError={(err) => showToast(err.message)}
 * >
 *   刷新账号
 * </AsyncButton>
 * ```
 */
import * as React from "react";
import { CheckCircle2, LoaderCircle, XCircle } from "lucide-react";

import { Button } from "./button";
import { cn } from "@/lib/utils";

type ButtonState = "idle" | "loading" | "success" | "error";

export type AsyncButtonProps = Omit<
  React.ComponentProps<typeof Button>,
  "disabled" | "onClick"
> & {
  /** 异步操作，返回 Promise */
  action?: () => Promise<unknown>;
  /** 外部控制的 loading（优先级高于内部状态机） */
  isLoading?: boolean;
  /** loading 时显示的文本（默认显示 children） */
  loadingText?: string;
  /** 成功状态显示时长 ms（默认 2000） */
  successDuration?: number;
  /** 错误状态显示时长 ms（默认 5000） */
  errorDuration?: number;
  /** 成功后回调 */
  onSuccess?: (result: unknown) => void;
  /** 失败后回调 */
  onError?: (error: Error) => void;
  /** 图标（loading 时替换为 spinner，success 时替换为勾，error 时替换为叉） */
  icon?: React.ReactNode;
  /** 兼容旧的 onClick 签名 */
  onClick?: (event: React.MouseEvent<HTMLButtonElement>) => void | Promise<unknown>;
  /** 是否启用按钮震动反馈（默认 true） */
  haptic?: boolean;
};

function AsyncButtonBase(
  {
    action,
    isLoading: externalLoading,
    loadingText,
    successDuration = 2000,
    errorDuration = 5000,
    onSuccess,
    onError,
    icon,
    children,
    className,
    onClick,
    haptic = true,
    ...rest
  }: AsyncButtonProps,
  ref: React.Ref<HTMLButtonElement>,
) {
  const [state, setState] = React.useState<ButtonState>("idle");
  const mountedRef = React.useRef(true);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  const loading = externalLoading ?? state === "loading";
  const isSuccess = state === "success";
  const isError = state === "error";
  const disabled = loading || isSuccess || isError;

  React.useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const handleClick = async (event: React.MouseEvent<HTMLButtonElement>) => {
    if (disabled) return;

    // 优先执行 action prop，兼容旧 onClick
    const fn = action ?? onClick;
    if (!fn) return;

    // 震动反馈（移动端）
    if (haptic && typeof navigator !== "undefined" && "vibrate" in navigator) {
      navigator.vibrate(10);
    }

    setState("loading");
    try {
      const result = await fn(event);
      if (!mountedRef.current) return;
      setState("success");
      onSuccess?.(result);
      clearTimer();
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) setState("idle");
      }, successDuration);
    } catch (error) {
      if (!mountedRef.current) return;
      setState("error");
      const err = error instanceof Error ? error : new Error(String(error));
      onError?.(err);
      clearTimer();
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) setState("idle");
      }, errorDuration);
    }
  };

  const renderIcon = () => {
    if (loading) {
      return <LoaderCircle className="size-4 animate-spin" aria-hidden="true" />;
    }
    if (isSuccess) {
      return <CheckCircle2 className="size-4 text-green-600" aria-hidden="true" />;
    }
    if (isError) {
      return <XCircle className="size-4 text-red-600" aria-hidden="true" />;
    }
    return icon;
  };

  const renderText = () => {
    if (loading && loadingText) return loadingText;
    if (isSuccess) return children;
    if (isError) return children;
    return children;
  };

  return (
    <Button
      ref={ref}
      className={cn(
        "relative transition-all",
        isSuccess && "border-green-300 bg-green-50 text-green-700 hover:bg-green-50 dark:border-green-700 dark:bg-green-950/30 dark:text-green-300",
        isError && "border-red-300 bg-red-50 text-red-700 hover:bg-red-50 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300",
        className,
      )}
      disabled={disabled}
      onClick={(event) => {
        void handleClick(event);
      }}
      aria-busy={loading}
      aria-label={loading && loadingText ? loadingText : undefined}
      {...rest}
    >
      {renderIcon()}
      {renderText()}
    </Button>
  );
}

const AsyncButton = React.forwardRef<HTMLButtonElement, AsyncButtonProps>(
  AsyncButtonBase,
);
AsyncButton.displayName = "AsyncButton";

export { AsyncButton };