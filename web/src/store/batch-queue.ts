"use client";

import { useCallback, useEffect, useState } from "react";

// ─── Types ─────────────────────────────────────────────────────────

export type BatchAction = "refresh" | "relogin" | "evict" | "label" | "delete" | "export";
export type BatchItemStatus = "queued" | "running" | "completed" | "failed" | "cancelled";

export type BatchQueueItem = {
  id: string;
  action: BatchAction;
  label: string;
  tokens: string[];
  status: BatchItemStatus;
  progress: number;
  results: Record<string, { success: boolean; error?: string }>;
  createdAt: string;
  completedAt?: string;
  /** 自增序号：同一毫秒创建的多个任务按此稳定排序（createdAt 相同则 seq 大的在前）。 */
  seq?: number;
};

// ─── Module-level state ────────────────────────────────────────────
// 注意：禁止在模块顶层访问 localStorage —— Next.js SSR 首屏会执行模块，
// 此时 `window`/`localStorage` 未定义会直接崩溃。历史读写统一走
// readHistory/writeHistory（含惰性加载 + typeof window 守卫）。

const queue = new Map<string, BatchQueueItem>();
const abortControllers = new Map<string, AbortController>();
const listeners = new Set<() => void>();

const STORAGE_KEY = "batch-queue-history";
const MAX_HISTORY = 50;

/** 全局自增序号：保证同一毫秒多个任务的排序稳定。 */
let seqCounter = 0;

function notify() {
  for (const fn of listeners) {
    try {
      fn();
    } catch {
      /* noop */
    }
  }
}

function readHistory(): BatchQueueItem[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as BatchQueueItem[]) : [];
  } catch {
    return [];
  }
}

function writeHistory(items: BatchQueueItem[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
  } catch {
    /* quota exceeded */
  }
}

// ─── Public API ────────────────────────────────────────────────────

export function enqueue(
  item: Omit<BatchQueueItem, "id" | "status" | "progress" | "results" | "createdAt" | "completedAt" | "seq"> & {
    id?: string;
  },
): string {
  seqCounter += 1;
  const id = item.id ?? `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  queue.set(id, {
    ...item,
    id,
    status: "queued",
    progress: 0,
    results: {},
    createdAt: new Date().toISOString(),
    seq: seqCounter,
  });
  abortControllers.set(id, new AbortController());
  notify();
  return id;
}

export function cancel(id: string) {
  const controller = abortControllers.get(id);
  if (controller) {
    controller.abort();
    abortControllers.delete(id);
  }

  const item = queue.get(id);
  if (!item) return;
  if (item.status === "completed" || item.status === "failed" || item.status === "cancelled") return;

  const done: BatchQueueItem = {
    ...item,
    status: "cancelled",
    completedAt: new Date().toISOString(),
  };
  queue.delete(id);
  writeHistory([done, ...readHistory()]);
  notify();
}

export function resume(id: string, failedTokens: string[]): string | null {
  if (failedTokens.length === 0) return null;

  const history = readHistory();
  const original = history.find((h) => h.id === id) ?? [...queue.values()].find((h) => h.id === id);
  if (!original) return null;

  return enqueue({
    action: original.action,
    label: `${original.label}（重试）`,
    tokens: failedTokens,
  });
}

/** 按 createdAt 倒序；同一毫秒（createdAt 相同）按 seq 大的在前。 */
function byNewestFirst(a: BatchQueueItem, b: BatchQueueItem): number {
  const cmp = b.createdAt.localeCompare(a.createdAt);
  if (cmp !== 0) return cmp;
  return (b.seq ?? 0) - (a.seq ?? 0);
}

export function getQueue(): BatchQueueItem[] {
  return [...queue.values()].sort(byNewestFirst);
}

export function getHistory(): BatchQueueItem[] {
  return readHistory();
}

export function clearHistory() {
  writeHistory([]);
  notify();
}

export function getAllHistory(): BatchQueueItem[] {
  const seen = new Map<string, BatchQueueItem>();
  for (const item of queue.values()) {
    seen.set(item.id, item);
  }
  for (const item of readHistory()) {
    if (!seen.has(item.id)) {
      seen.set(item.id, item);
    }
  }
  return [...seen.values()].sort(byNewestFirst);
}

// ─── Internal helpers for progress & result updates ────────────────

export function updateItemProgress(id: string, progress: number) {
  const item = queue.get(id);
  if (!item) return;
  queue.set(id, { ...item, progress });
  notify();
}

export function updateItemResult(id: string, token: string, success: boolean, error?: string) {
  const item = queue.get(id);
  if (!item) return;

  const results = { ...item.results, [token]: { success, error } };
  const done = Object.keys(results).length >= item.tokens.length;
  const hasFailures = Object.values(results).some((r) => !r.success);
  const nextStatus: BatchItemStatus = done ? (hasFailures ? "failed" : "completed") : "running";

  const updated: BatchQueueItem = {
    ...item,
    results,
    status: nextStatus,
    progress: done ? 100 : Math.round((Object.keys(results).length / item.tokens.length) * 100),
    completedAt: done ? new Date().toISOString() : undefined,
  };
  queue.set(id, updated);

  if (done) {
    queue.delete(id);
    writeHistory([updated, ...readHistory()]);
  }

  notify();
}

export function getAbortController(id: string): AbortController | undefined {
  return abortControllers.get(id);
}

// ─── React hook ────────────────────────────────────────────────────

export function useBatchQueue() {
  const [, tick] = useState(0);

  useEffect(() => {
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  const queue = useCallback(() => getQueue(), []);
  const history = useCallback(() => getHistory(), []);
  const allHistory = useCallback(() => getAllHistory(), []);

  return { queue, history, allHistory };
}