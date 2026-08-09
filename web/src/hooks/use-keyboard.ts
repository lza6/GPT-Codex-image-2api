"use client";

import { useCallback, useEffect } from "react";

type KeyHandler = (event: KeyboardEvent) => void;

type ShortcutDef = {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  shift?: boolean;
  alt?: boolean;
  handler: KeyHandler;
  /** 描述（用于显示快捷键列表） */
  description?: string;
  /** 当焦点在 input/textarea/select 时是否仍触发（默认 false） */
  allowInInput?: boolean;
};

const INPUT_SELECTORS = "input, textarea, select, [contenteditable]";

function isInputFocused(): boolean {
  const active = document.activeElement;
  if (!active) return false;
  return active.matches(INPUT_SELECTORS);
}

/**
 * 全局键盘快捷键系统。
 *
 * 用法：
 * ```tsx
 * useKeyboard([
 *   { key: "k", ctrl: true, handler: () => openSearch(), description: "打开搜索" },
 *   { key: "Escape", handler: () => closeDialog(), allowInInput: true },
 * ]);
 * ```
 */
export function useKeyboard(shortcuts: ShortcutDef[]) {
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      for (const shortcut of shortcuts) {
        const matchKey = event.key === shortcut.key || event.code === shortcut.key;
        const matchCtrl = Boolean(shortcut.ctrl) === (event.ctrlKey || event.metaKey);
        const matchMeta = Boolean(shortcut.meta) === event.metaKey;
        const matchShift = Boolean(shortcut.shift) === event.shiftKey;
        const matchAlt = Boolean(shortcut.alt) === event.altKey;

        if (!matchKey || !matchCtrl || !matchMeta || !matchShift || !matchAlt) {
          continue;
        }

        if (!shortcut.allowInInput && isInputFocused()) {
          continue;
        }

        event.preventDefault();
        event.stopPropagation();
        shortcut.handler(event);
        return;
      }
    },
    [shortcuts],
  );

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);
}

/**
 * 获取所有已注册的快捷键描述列表（用于设置页显示）。
 * 调用方需自行维护一个全局注册表，或组件内联声明。
 */
export type { ShortcutDef };