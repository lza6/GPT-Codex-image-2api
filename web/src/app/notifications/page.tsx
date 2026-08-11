"use client";

import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  CheckCheck,
  CheckCircle2,
  Info,
  LoaderCircle,
  Search,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState } from "@/components/empty-state";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import {
  clearAll,
  getNotifications,
  markAllAsRead,
  markAsRead,
  setPreference,
  getAllPreferences,
  useNotifications,
  type Notification,
  type NotificationPreferences,
  type NotificationType,
} from "@/store/notifications";

type TypeFilter = "all" | NotificationType;

const TYPE_META: Record<NotificationType, { label: string; icon: typeof Info; color: string }> = {
  system: { label: "系统通知", icon: Info, color: "text-sky-500 bg-sky-50 dark:bg-sky-950/30" },
  alert: { label: "告警通知", icon: AlertTriangle, color: "text-amber-500 bg-amber-50 dark:bg-amber-950/30" },
  operation: { label: "操作结果", icon: CheckCircle2, color: "text-emerald-500 bg-emerald-50 dark:bg-emerald-950/30" },
};

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  return `${days} 天前`;
}

function NotificationsPageContent() {
  const { list } = useNotifications();
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [readFilter, setReadFilter] = useState<"all" | "read" | "unread">("all");
  const [keyword, setKeyword] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [prefs, setPrefs] = useState<Record<NotificationType, NotificationPreferences>>(getAllPreferences());

  const all = list();
  const filtered = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return all.filter((n) => {
      if (typeFilter !== "all" && n.type !== typeFilter) return false;
      if (readFilter === "read" && !n.read) return false;
      if (readFilter === "unread" && n.read) return false;
      if (kw) {
        const haystack = `${n.title} ${n.message}`.toLowerCase();
        if (!haystack.includes(kw)) return false;
      }
      return true;
    });
  }, [all, typeFilter, readFilter, keyword]);

  const unreadCount = all.filter((n) => !n.read).length;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (prev.size === filtered.length && filtered.length > 0) return new Set();
      return new Set(filtered.map((n) => n.id));
    });
  };

  const handleBatchMarkRead = () => {
    for (const id of selected) markAsRead(id);
    const count = selected.size;
    setSelected(new Set());
    toast.success(`已将 ${count} 条通知标记为已读`);
  };

  const handleClearAll = () => {
    if (all.length === 0) {
      toast.info("暂无通知");
      return;
    }
    clearAll();
    setSelected(new Set());
    toast.success("已清空全部通知");
  };

  const handleTogglePref = (type: NotificationType, key: "toast" | "notify") => {
    const current = prefs[type] ?? { toast: true, notify: true };
    const next = { ...current, [key]: !current[key] };
    setPreference(type, { [key]: next[key] });
    setPrefs(getAllPreferences());
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-stone-500 uppercase">
            Notifications
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">通知中心</h1>
          <p className="text-sm text-stone-400">
            共 {all.length} 条通知，{unreadCount} 条未读
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-stone-700 hover:bg-white"
            onClick={() => { markAllAsRead(); toast.success("已全部标记为已读"); }}
            disabled={unreadCount === 0}
          >
            <CheckCheck className="size-4" />
            全部已读
          </Button>
          <Button
            variant="outline"
            className="h-10 rounded-xl border-stone-200 bg-white/80 px-4 text-rose-600 hover:bg-rose-50"
            onClick={handleClearAll}
            disabled={all.length === 0}
          >
            <Trash2 className="size-4" />
            清空
          </Button>
        </div>
      </div>

      {/* 通知偏好设置（5.2.3 任务5） */}
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-4">
          <div className="mb-3 text-sm font-medium text-stone-700">通知偏好设置</div>
          <div className="grid gap-2 sm:grid-cols-3">
            {(Object.keys(TYPE_META) as NotificationType[]).map((type) => {
              const meta = TYPE_META[type];
              const pref = prefs[type] ?? { toast: true, notify: true };
              return (
                <div key={type} className="rounded-xl border border-stone-200 bg-stone-50/50 p-3">
                  <div className="mb-2 flex items-center gap-2 text-sm font-medium text-stone-700">
                    <span className={cn("flex size-6 items-center justify-center rounded-full", meta.color)}>
                      <meta.icon className="size-3.5" />
                    </span>
                    {meta.label}
                  </div>
                  <div className="space-y-1.5">
                    <label className="flex cursor-pointer items-center gap-2 text-xs text-stone-600">
                      <Checkbox
                        checked={pref.toast}
                        onCheckedChange={() => handleTogglePref(type, "toast")}
                      />
                      弹 Toast
                    </label>
                    <label className="flex cursor-pointer items-center gap-2 text-xs text-stone-600">
                      <Checkbox
                        checked={pref.notify}
                        onCheckedChange={() => handleTogglePref(type, "notify")}
                      />
                      进通知中心
                    </label>
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* 筛选与列表 */}
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-0">
          <div className="flex flex-col gap-3 border-b border-stone-100 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <Tabs value={typeFilter} onValueChange={(v) => setTypeFilter(v as TypeFilter)}>
                <TabsList className="rounded-lg bg-stone-100">
                  <TabsTrigger value="all">全部</TabsTrigger>
                  <TabsTrigger value="system">系统</TabsTrigger>
                  <TabsTrigger value="alert">告警</TabsTrigger>
                  <TabsTrigger value="operation">操作结果</TabsTrigger>
                </TabsList>
              </Tabs>
              <Select value={readFilter} onValueChange={(v) => setReadFilter(v as typeof readFilter)}>
                <SelectTrigger className="h-9 w-[130px] rounded-lg border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部状态</SelectItem>
                  <SelectItem value="unread">未读</SelectItem>
                  <SelectItem value="read">已读</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="relative min-w-[220px]">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-stone-400" />
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="搜索标题/内容关键词"
                className="h-9 rounded-xl border-stone-200 bg-white/85 pl-9"
              />
            </div>
          </div>

          {filtered.length > 0 && (
            <div className="flex items-center gap-3 border-b border-stone-100 px-4 py-2 text-xs text-stone-500">
              <Checkbox
                checked={filtered.length > 0 && selected.size === filtered.length}
                onCheckedChange={toggleSelectAll}
              />
              <span>
                已选 {selected.size} 条
              </span>
              {selected.size > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-xs text-stone-500 hover:text-sky-600"
                  onClick={handleBatchMarkRead}
                >
                  <CheckCheck className="size-3.5" />
                  标记已读
                </Button>
              )}
            </div>
          )}

          {filtered.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={<Bell className="size-6" />}
                title={all.length === 0 ? "暂无通知" : "没有匹配的通知"}
                description={
                  keyword || typeFilter !== "all" || readFilter !== "all"
                    ? "调整筛选条件后重试。"
                    : "新的系统通知、告警和操作结果会显示在这里。"
                }
                action={
                  keyword || typeFilter !== "all" || readFilter !== "all"
                    ? {
                        label: "清除筛选",
                        onClick: () => {
                          setKeyword("");
                          setTypeFilter("all");
                          setReadFilter("all");
                        },
                      }
                    : undefined
                }
              />
            </div>
          ) : (
            <div className="divide-y divide-stone-50">
              {filtered.map((n) => {
                const meta = TYPE_META[n.type] ?? TYPE_META.system;
                return (
                  <div
                    key={n.id}
                    className={cn(
                      "flex items-start gap-3 px-4 py-3 transition",
                      !n.read && "bg-stone-50/60",
                    )}
                  >
                    <Checkbox
                      checked={selected.has(n.id)}
                      onCheckedChange={() => toggleSelect(n.id)}
                      className="mt-1"
                    />
                    <span className={cn("mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full", meta.color)}>
                      <meta.icon className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-2">
                        <span className={cn("text-sm", n.read ? "text-stone-600" : "font-medium text-stone-900")}>
                          {n.title}
                        </span>
                        <div className="flex shrink-0 items-center gap-2">
                          <Badge variant="secondary" className="rounded-md">{meta.label}</Badge>
                          {!n.read && <span className="size-1.5 rounded-full bg-sky-500" />}
                        </div>
                      </div>
                      {n.message && (
                        <p className="mt-0.5 break-words text-xs text-stone-400">{n.message}</p>
                      )}
                      {n.type === "operation" && (n.metadata as { successCount?: number; failCount?: number } | undefined) && (
                        <div className="mt-1 flex items-center gap-3 text-xs">
                          <span className="text-emerald-600">
                            成功 {(n.metadata as { successCount?: number }).successCount ?? 0}
                          </span>
                          <span className="text-rose-600">
                            失败 {(n.metadata as { failCount?: number }).failCount ?? 0}
                          </span>
                        </div>
                      )}
                      <span className="mt-1 block text-[10px] text-stone-300">
                        {formatTime(n.timestamp)} · {formatRelative(n.timestamp)}
                      </span>
                    </div>
                    {!n.read && (
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-7 shrink-0 text-stone-400 hover:text-stone-700"
                        title="标记已读"
                        onClick={() => { markAsRead(n.id); }}
                      >
                        <CheckCheck className="size-3.5" />
                      </Button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function NotificationsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <NotificationsPageContent />;
}
