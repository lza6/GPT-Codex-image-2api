"use client";

import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

/**
 * 操作撤销系统。
 *
 * 用法：
 * ```tsx
 * const undo = useUndo<string>((item) => {
 *   // 恢复操作
 *   restoreItem(item);
 * });
 *
 * // 执行删除
 * undo.execute(item, () => {
 *   // 执行后 toast 会显示撤销按钮
 *   deleteItem(item);
 * }, "已删除项目");
 * ```
 */

export interface UndoAction<T> {
  /** 执行操作（返回被操作的对象） */
  execute: (item: T, action: () => void, message?: string) => void;
  /** 撤销后的回调 */
  undo: () => void;
  /** 是否有待撤销的操作 */
  hasPending: boolean;
}

export function useUndo<T = unknown>(
  onRestore: (item: T) => void | Promise<void>,
  options?: { timeout?: number; toastMessage?: string },
): UndoAction<T> {
  const pendingRef = useRef<T | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [hasPending, setHasPending] = useState(false);

  const execute = useCallback(
    (item: T, action: () => void, message?: string) => {
      // 清除之前的待撤销
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      pendingRef.current = item;

      // 执行操作
      action();

      setHasPending(true);

      // 显示可撤销的 toast
      const toastId = toast(message ?? "操作完成", {
        action: {
          label: "撤销",
          onClick: () => {
            const saved = pendingRef.current;
            if (saved) {
              void onRestore(saved);
              pendingRef.current = null;
              setHasPending(false);
              toast.dismiss(toastId);
            }
          },
        },
        duration: options?.timeout ?? 5000,
      });

      // 超时后清除待撤销状态
      timerRef.current = setTimeout(() => {
        pendingRef.current = null;
        setHasPending(false);
      }, options?.timeout ?? 5000);
    },
    [onRestore, options?.timeout],
  );

  const undo = useCallback(() => {
    const saved = pendingRef.current;
    if (saved) {
      pendingRef.current = null;
      setHasPending(false);
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      void onRestore(saved);
    }
  }, [onRestore]);

  return { execute, undo, hasPending };
}