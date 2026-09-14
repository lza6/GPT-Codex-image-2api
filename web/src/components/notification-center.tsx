"use client";

import { useEffect, useState } from "react";
import {
  Bell,
  CheckCheck,
  Trash2,
  Info,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { eventHref } from "@/lib/event-notifications";
import {
  markAsRead,
  markAllAsRead,
  clearAll,
  registerToastHandler,
  setPreference,
  getAllPreferences,
  type Notification,
  type NotificationPreferences,
  type NotificationType,
  useNotifications,
} from "@/store/notifications";

// ─── Constants ─────────────────────────────────────────────────────────

type TabValue = "all" | NotificationType | "prefs";

const TAB_CONFIG: { value: TabValue; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "system", label: "系统通知" },
  { value: "alert", label: "告警通知" },
  { value: "operation", label: "操作结果" },
  { value: "prefs", label: "偏好" },
];

const TYPE_ICON_MAP: Record<NotificationType, typeof Info> = {
  system: Info,
  alert: AlertTriangle,
  operation: CheckCircle2,
};

const TYPE_COLOR_MAP: Record<NotificationType, string> = {
  system: "text-sky-500 bg-sky-50 dark:bg-sky-950/30",
  alert: "text-amber-500 bg-amber-50 dark:bg-amber-950/30",
  operation: "text-emerald-500 bg-emerald-50 dark:bg-emerald-950/30",
};

const TYPE_LABEL: Record<NotificationType, string> = {
  system: "系统通知",
  alert: "告警通知",
  operation: "操作结果",
};

// ─── Helpers ────────────────────────────────────────────────────────────

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return new Date(iso).toLocaleDateString("zh-CN");
}

/** 根据通知类型触发对应样式的 sonner Toast。 */
function showToastForNotification(n: Notification) {
  if (n.type === "alert") {
    toast.error(n.title, { description: n.message });
  } else if (n.type === "operation") {
    const meta = n.metadata as { successCount?: number; failCount?: number } | undefined;
    const failCount = meta?.failCount ?? 0;
    if (failCount > 0) {
      toast.warning(n.title, { description: n.message });
    } else {
      toast.success(n.title, { description: n.message });
    }
  } else {
    toast.info(n.title, { description: n.message });
  }
}

// ─── Component ──────────────────────────────────────────────────────────

export function NotificationCenter() {
  const [open, setOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<TabValue>("all");
  const [prefs, setPrefs] = useState<Record<NotificationType, NotificationPreferences>>(() =>
    getAllPreferences(),
  );
  const { list, unreadCount } = useNotifications();

  const unread = unreadCount();
  const allNotifications = list();
  const filtered =
    activeTab === "all" || activeTab === "prefs"
      ? allNotifications
      : allNotifications.filter((n) => n.type === activeTab);

  // 注册 toast 处理器：store.addNotification 弹 Toast 时走这里（偏好 toast=true 时）
  useEffect(() => {
    registerToastHandler((n) => showToastForNotification(n));
    return () => registerToastHandler(null);
  }, []);

  const handleMarkAllRead = () => {
    markAllAsRead();
  };

  const handleClearAll = () => {
    clearAll();
  };

  const handleTogglePref = (type: NotificationType, key: keyof NotificationPreferences) => {
    const current = prefs[type] ?? { toast: true, notify: true };
    setPreference(type, { [key]: !current[key] });
    setPrefs(getAllPreferences());
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          className="relative inline-flex size-8 items-center justify-center rounded-lg text-stone-400 transition hover:bg-stone-100 hover:text-stone-700 dark:hover:bg-white/10 dark:hover:text-stone-300"
          aria-label="通知"
        >
          <Bell className="size-4" />
          {unread > 0 && (
            <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold leading-4 text-white ring-2 ring-white dark:ring-stone-950">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-[380px] p-0 sm:w-[420px]"
      >
        {/* ── Header ─────────────────────────────────────────────── */}
        <div className="flex items-center justify-between border-b border-stone-100 px-4 py-3 dark:border-white/10">
          <h3 className="text-sm font-semibold text-stone-900 dark:text-stone-100">
            通知
          </h3>
          <div className="flex items-center gap-1">
            <button
              type="button"
              className="inline-flex size-7 items-center justify-center rounded-md text-stone-400 transition hover:bg-stone-100 hover:text-stone-700 disabled:opacity-30 dark:hover:bg-white/10 dark:hover:text-stone-300"
              onClick={handleMarkAllRead}
              title="全部标为已读"
              disabled={unread === 0}
            >
              <CheckCheck className="size-3.5" />
            </button>
            <button
              type="button"
              className="inline-flex size-7 items-center justify-center rounded-md text-stone-400 transition hover:bg-stone-100 hover:text-stone-700 disabled:opacity-30 dark:hover:bg-white/10 dark:hover:text-stone-300"
              onClick={handleClearAll}
              title="清空所有通知"
              disabled={allNotifications.length === 0}
            >
              <Trash2 className="size-3.5" />
            </button>
          </div>
        </div>

        {/* ── Tabs ───────────────────────────────────────────────── */}
        <div className="flex gap-0 border-b border-stone-100 px-3 dark:border-white/10">
          {TAB_CONFIG.map((tab) => (
            <button
              key={tab.value}
              type="button"
              className={cn(
                "relative px-3 py-2 text-xs font-medium transition",
                activeTab === tab.value
                  ? "text-stone-900 dark:text-white"
                  : "text-stone-400 hover:text-stone-600 dark:hover:text-stone-300",
              )}
              onClick={() => setActiveTab(tab.value)}
            >
              {tab.label}
              {activeTab === tab.value && (
                <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-stone-900 dark:bg-white" />
              )}
            </button>
          ))}
        </div>

        {/* ── Prefs Panel ─────────────────────────────────────── */}
        {activeTab === "prefs" ? (
          <div className="max-h-[340px] space-y-2 overflow-y-auto p-4">
            {(Object.keys(TYPE_LABEL) as NotificationType[]).map((type) => {
              const pref = prefs[type] ?? { toast: true, notify: true };
              const TypeIcon = TYPE_ICON_MAP[type];
              return (
                <div
                  key={type}
                  className="rounded-xl border border-stone-100 bg-stone-50/60 p-3 dark:border-white/10 dark:bg-white/5"
                >
                  <div className="mb-2 flex items-center gap-2 text-xs font-medium text-stone-700 dark:text-stone-200">
                    <span
                      className={cn(
                        "flex size-6 items-center justify-center rounded-full",
                        TYPE_COLOR_MAP[type],
                      )}
                    >
                      <TypeIcon className="size-3" />
                    </span>
                    {TYPE_LABEL[type]}
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-stone-500 dark:text-stone-400">
                      <input
                        type="checkbox"
                        checked={pref.toast}
                        onChange={() => handleTogglePref(type, "toast")}
                        className="accent-stone-900 dark:accent-white"
                      />
                      弹 Toast
                    </label>
                    <label className="flex cursor-pointer items-center gap-1.5 text-xs text-stone-500 dark:text-stone-400">
                      <input
                        type="checkbox"
                        checked={pref.notify}
                        onChange={() => handleTogglePref(type, "notify")}
                        className="accent-stone-900 dark:accent-white"
                      />
                      进通知中心
                    </label>
                  </div>
                </div>
              );
            })}
            <p className="pt-1 text-[10px] leading-4 text-stone-400 dark:text-stone-500">
              弹 Toast：该类型新通知会即时弹出提示；关闭后仅进入通知中心。
              <br />
              进通知中心：关闭后该类型通知将被忽略，不记录。
            </p>
          </div>
        ) : (
          <>
            {/* ── Notification List ──────────────────────────────── */}
            <div className="max-h-[340px] overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-14 text-center">
                  <Bell className="mb-2 size-8 text-stone-200 dark:text-stone-700" />
                  <p className="text-sm text-stone-400 dark:text-stone-500">
                    暂无通知
                  </p>
                </div>
              ) : (
                <div className="divide-y divide-stone-50 dark:divide-white/5">
                  {filtered.map((notification) => {
                    const TypeIcon = TYPE_ICON_MAP[notification.type];
                    return (
                      <button
                        key={notification.id}
                        type="button"
                        className={cn(
                          "flex w-full gap-3 px-4 py-3 text-left transition hover:bg-stone-50 dark:hover:bg-white/5",
                          !notification.read &&
                            "bg-stone-50/50 dark:bg-white/[0.02]",
                        )}
                        onClick={() => {
                          if (!notification.read) {
                            markAsRead(notification.id);
                          }
                          // v2.40.0 G4：系统告警通知点击跳转对应页面（事件链路，metadata.href）
                          const meta = notification.metadata as { href?: string } | undefined;
                          const href = meta?.href;
                          if (href && typeof window !== "undefined") {
                            window.location.href = href;
                          }
                        }}
                      >
                        {/* Type icon */}
                        <span
                          className={cn(
                            "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full",
                            TYPE_COLOR_MAP[notification.type],
                          )}
                        >
                          <TypeIcon className="size-3.5" />
                        </span>

                        {/* Content */}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-start justify-between gap-2">
                            <span
                              className={cn(
                                "text-sm",
                                notification.read
                                  ? "text-stone-600 dark:text-stone-400"
                                  : "font-medium text-stone-900 dark:text-stone-100",
                              )}
                            >
                              {notification.title}
                            </span>
                            {!notification.read && (
                              <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-sky-500" />
                            )}
                          </div>
                          <p className="mt-0.5 line-clamp-2 text-xs text-stone-400 dark:text-stone-500">
                            {notification.message}
                          </p>
                          <span className="mt-1 block text-[10px] text-stone-300 dark:text-stone-600">
                            {formatRelativeTime(notification.timestamp)}
                          </span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}

        {/* ── Footer ─────────────────────────────────────────────── */}
        <div className="border-t border-stone-100 px-4 py-2.5 dark:border-white/10">
          <a
            href="/notifications"
            className="block text-center text-xs text-stone-400 transition hover:text-stone-700 dark:hover:text-stone-300"
          >
            查看全部历史
          </a>
        </div>
      </PopoverContent>
    </Popover>
  );
}