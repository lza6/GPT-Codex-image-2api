"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * useScrollMemory — 虚拟列表滚动位置记忆。
 *
 * 将返回的 ref 挂到虚拟滚动容器；卸载时把 scrollTop 写入 sessionStorage，
 * 重新挂载时写入 DOM 并暴露 getSavedOffset() 供页面在数据就绪后
 * 通过 virtualizer.scrollToOffset 精确归位。
 */
export function useScrollMemory<T extends HTMLElement>(storageKey: string) {
  const ref = useRef<T | null>(null);
  const savedOffsetRef = useRef(0);

  useEffect(() => {
    let saved = 0;
    try {
      saved = Number(sessionStorage.getItem(storageKey)) || 0;
    } catch {
      // ignore
    }
    savedOffsetRef.current = saved;
    const el = ref.current;
    if (el) el.scrollTop = saved;
  }, [storageKey]);

  const getSavedOffset = useCallback(() => savedOffsetRef.current, []);

  const save = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    try {
      sessionStorage.setItem(storageKey, String(el.scrollTop));
    } catch {
      // ignore
    }
  }, [storageKey]);

  // 卸载/路由切换时保存当前位置
  useEffect(() => {
    return () => {
      save();
    };
  }, [save]);

  return { ref, getSavedOffset, save };
}
