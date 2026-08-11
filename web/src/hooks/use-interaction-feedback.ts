"use client";

/**
 * useInteractionFeedback — 统一交互反馈 Hook。
 *
 * 管理按钮/输入/操作的交互状态机，提供：
 * - 点击涟漪坐标
 * - 加载/成功/错误三态
 * - 焦点/悬停/激活状态
 * - 震动反馈（移动端）
 *
 * ```tsx
 * const { rippleProps, feedbackState, handleAction, feedbackStyles } = useInteractionFeedback({
 *   action: saveData,
 *   onSuccess: () => toastSuccess("保存成功"),
 * });
 * ```
 */
import { useCallback, useRef, useState } from "react";

export type FeedbackState = "idle" | "loading" | "success" | "error";

export interface InteractionFeedbackOptions {
  /** 异步操作 */
  action?: () => Promise<unknown>;
  /** 成功回调 */
  onSuccess?: (result: unknown) => void;
  /** 失败回调 */
  onError?: (error: Error) => void;
  /** 成功状态持续时间（ms） */
  successDuration?: number;
  /** 错误状态持续时间（ms） */
  errorDuration?: number;
  /** 是否启用震动反馈（默认 true） */
  haptic?: boolean;
}

export function useInteractionFeedback(options: InteractionFeedbackOptions = {}) {
  const {
    action,
    onSuccess,
    onError,
    successDuration = 2000,
    errorDuration = 5000,
    haptic = true,
  } = options;

  const [feedbackState, setFeedbackState] = useState<FeedbackState>("idle");
  const [ripplePos, setRipplePos] = useState<{ x: number; y: number } | null>(null);
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const handleAction = useCallback(
    async (event?: React.MouseEvent) => {
      if (feedbackState !== "idle") return;

      // 涟漪坐标
      if (event) {
        const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
        setRipplePos({
          x: event.clientX - rect.left,
          y: event.clientY - rect.top,
        });
      }

      // 震动反馈
      if (haptic && typeof navigator !== "undefined" && "vibrate" in navigator) {
        navigator.vibrate(10);
      }

      const fn = action ?? (event ? (event.currentTarget as HTMLButtonElement).form?.requestSubmit : undefined);
      if (!fn) {
        setFeedbackState("idle");
        return;
      }

      setFeedbackState("loading");
      clearTimer();
      try {
        const result = await (typeof fn === "function" ? fn() : fn);
        if (!mountedRef.current) return;
        setFeedbackState("success");
        onSuccess?.(result);
        timerRef.current = setTimeout(() => {
          if (mountedRef.current) setFeedbackState("idle");
        }, successDuration);
      } catch (error) {
        if (!mountedRef.current) return;
        setFeedbackState("error");
        const err = error instanceof Error ? error : new Error(String(error));
        onError?.(err);
        clearTimer();
        timerRef.current = setTimeout(() => {
          if (mountedRef.current) setFeedbackState("idle");
        }, errorDuration);
      }
    },
    [action, feedbackState, haptic, onSuccess, onError, successDuration, errorDuration, clearTimer],
  );

  const feedbackStyles = {
    success: "border-green-300 bg-green-50 text-green-700 dark:border-green-700 dark:bg-green-950/30 dark:text-green-300",
    error: "border-red-300 bg-red-50 text-red-700 dark:border-red-700 dark:bg-red-950/30 dark:text-red-300",
    loading: "opacity-80",
  };

  return {
    ripplePos,
    feedbackState,
    handleAction,
    feedbackStyles,
    reset: useCallback(() => {
      setFeedbackState("idle");
      setRipplePos(null);
      clearTimer();
    }, [clearTimer]),
  };
}