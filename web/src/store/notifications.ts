"use client";

import { useCallback, useEffect, useState } from "react";

// ─── Types ─────────────────────────────────────────────────────────

export type NotificationType = "system" | "alert" | "operation";

export type Notification = {
  id: string;
  type: NotificationType;
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  metadata?: Record<string, unknown>;
};

export type NotificationFilters = {
  type?: NotificationType | NotificationType[];
  since?: string; // ISO date string, inclusive
  until?: string; // ISO date string, inclusive
  read?: boolean;
};

/**
 * 通知偏好设置（5.2.3 任务5）。
 * - `toast`: 该类型是否弹 Toast（true=弹，false=只进通知中心）
 * - `notify`: 该类型是否记录到通知中心（false=完全忽略）
 */
export type NotificationPreferences = {
  toast: boolean;
  notify: boolean;
};

// ─── Module-level state ────────────────────────────────────────────
// 注意：禁止在模块顶层访问 localStorage —— Next.js SSR 首屏会执行模块，
// 此时 `window`/`localStorage` 未定义会直接崩溃。必须惰性加载（首次访问时读）。

let notifications: Notification[] = [];
let storageLoaded = false;
const listeners = new Set<() => void>();

const STORAGE_KEY = "notifications";
const PREF_STORAGE_KEY = "notifications-preferences";
const MAX_HISTORY = 200;

/** 默认偏好：全部弹 Toast + 进通知中心。 */
const DEFAULT_PREFERENCES: Record<NotificationType, NotificationPreferences> = {
  system: { toast: true, notify: true },
  alert: { toast: true, notify: true },
  operation: { toast: true, notify: true },
};

let preferences: Record<NotificationType, NotificationPreferences> = { ...DEFAULT_PREFERENCES };

/** UI 层注册的 toast 处理器（避免 store 依赖 sonner，保持纯净）。 */
let toastHandler: ((n: Notification) => void) | null = null;

/**
 * 注册/注销 toast 处理器（由浏览器端挂载的组件调用）。
 * @returns 注销函数
 */
export function registerToastHandler(handler: ((n: Notification) => void) | null): void {
  toastHandler = handler;
}

function notify() {
  for (const fn of listeners) {
    try {
      fn();
    } catch {
      /* noop */
    }
  }
}

function ensureStorageLoaded() {
  if (storageLoaded) return;
  storageLoaded = true;
  try {
    if (typeof localStorage !== "undefined") {
      const raw = localStorage.getItem(STORAGE_KEY);
      notifications = raw ? (JSON.parse(raw) as Notification[]) : [];
    }
  } catch {
    notifications = [];
  }
  try {
    if (typeof localStorage !== "undefined") {
      const rawPref = localStorage.getItem(PREF_STORAGE_KEY);
      const parsed = rawPref ? (JSON.parse(rawPref) as Partial<Record<NotificationType, Partial<NotificationPreferences>>>) : {};
      preferences = {
        system: { ...DEFAULT_PREFERENCES.system, ...parsed.system },
        alert: { ...DEFAULT_PREFERENCES.alert, ...parsed.alert },
        operation: { ...DEFAULT_PREFERENCES.operation, ...parsed.operation },
      };
    }
  } catch {
    preferences = { ...DEFAULT_PREFERENCES };
  }
}

function readStorage(): Notification[] {
  ensureStorageLoaded();
  return notifications;
}

function writeStorage(items: Notification[]) {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, MAX_HISTORY)));
  } catch {
    /* quota exceeded */
  }
}

// ─── Helpers ───────────────────────────────────────────────────────

function genId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

// ─── Public API ────────────────────────────────────────────────────

export function addNotification(n: Omit<Notification, "id" | "timestamp" | "read"> & { id?: string }): string {
  ensureStorageLoaded();
  const id = n.id ?? genId();
  const item: Notification = {
    ...n,
    id,
    timestamp: new Date().toISOString(),
    read: false,
  };

  const pref = preferences[n.type] ?? DEFAULT_PREFERENCES[n.type];

  // 偏好：完全忽略该类型
  if (pref.notify === false && pref.toast === false) {
    return id;
  }

  // 偏好：记录到通知中心
  if (pref.notify !== false) {
    notifications = [item, ...notifications];
    writeStorage(notifications);
    notify();
  }

  // 偏好：弹 Toast（交给 UI 层注册的处理器，浏览器环境才触发）
  if (pref.toast !== false) {
    try {
      toastHandler?.(item);
    } catch {
      // toast 处理器异常不阻断
    }
  }

  return id;
}

/** 获取某类型的通知偏好。 */
export function getPreference(type: NotificationType): NotificationPreferences {
  ensureStorageLoaded();
  return preferences[type] ?? DEFAULT_PREFERENCES[type];
}

/** 获取全部通知偏好。 */
export function getAllPreferences(): Record<NotificationType, NotificationPreferences> {
  ensureStorageLoaded();
  return preferences;
}

/** 更新某类型的通知偏好。 */
export function setPreference(
  type: NotificationType,
  patch: Partial<NotificationPreferences>,
): void {
  ensureStorageLoaded();
  preferences = {
    ...preferences,
    [type]: { ...(preferences[type] ?? DEFAULT_PREFERENCES[type]), ...patch },
  };
  if (typeof localStorage !== "undefined") {
    try {
      localStorage.setItem(PREF_STORAGE_KEY, JSON.stringify(preferences));
    } catch {
      /* quota exceeded */
    }
  }
  notify();
}

export function addOperationResult(
  title: string,
  message: string,
  successCount: number,
  failCount: number,
): string {
  return addNotification({
    type: "operation",
    title,
    message,
    metadata: { successCount, failCount },
  });
}

export function markAsRead(id: string) {
  ensureStorageLoaded();
  let changed = false;
  notifications = notifications.map((n) => {
    if (n.id === id && !n.read) {
      changed = true;
      return { ...n, read: true };
    }
    return n;
  });
  if (changed) {
    writeStorage(notifications);
    notify();
  }
}

export function markAllAsRead() {
  ensureStorageLoaded();
  const hasUnread = notifications.some((n) => !n.read);
  if (!hasUnread) return;
  notifications = notifications.map((n) => (n.read ? n : { ...n, read: true }));
  writeStorage(notifications);
  notify();
}

export function clearAll() {
  ensureStorageLoaded();
  if (notifications.length === 0) return;
  notifications = [];
  writeStorage([]);
  notify();
}

export function getNotifications(filters?: NotificationFilters): Notification[] {
  ensureStorageLoaded();
  let result = notifications;

  if (filters) {
    if (filters.type) {
      const types = Array.isArray(filters.type) ? filters.type : [filters.type];
      result = result.filter((n) => types.includes(n.type));
    }
    if (filters.since) {
      result = result.filter((n) => n.timestamp >= filters.since!);
    }
    if (filters.until) {
      result = result.filter((n) => n.timestamp <= filters.until!);
    }
    if (filters.read !== undefined) {
      result = result.filter((n) => n.read === filters.read!);
    }
  }

  return result;
}

export function getUnreadCount(): number {
  ensureStorageLoaded();
  return notifications.filter((n) => !n.read).length;
}

// ─── React hook ────────────────────────────────────────────────────

export function useNotifications() {
  const [, tick] = useState(0);

  useEffect(() => {
    ensureStorageLoaded();
    const fn = () => tick((n) => n + 1);
    listeners.add(fn);
    return () => {
      listeners.delete(fn);
    };
  }, []);

  const list = useCallback(
    (filters?: NotificationFilters) => getNotifications(filters),
    [],
  );
  const unreadCount = useCallback(() => getUnreadCount(), []);
  const preferences = useCallback(() => getAllPreferences(), []);

  return { list, unreadCount, preferences };
}