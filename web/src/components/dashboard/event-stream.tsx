"use client";

import { useState, useMemo } from "react";
import { motion } from "motion/react";
import { AlertTriangle, Ban, CheckCircle, RefreshCw, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { DashboardEvent } from "@/lib/api";

const EVENT_ICONS: Record<string, typeof AlertTriangle> = {
  "account.invalid": X, "account.recovered": CheckCircle, "account.quota_exhausted": AlertTriangle,
  "circuit.open": Ban, "circuit.half_open": AlertTriangle, "circuit.closed": CheckCircle,
  "backup.failure": AlertTriangle, "provider.health_changed": RefreshCw,
};

const EVENT_COLORS: Record<string, string> = {
  "account.invalid": "text-red-600 bg-red-50 dark:bg-red-950/30",
  "account.recovered": "text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30",
  "account.quota_exhausted": "text-amber-600 bg-amber-50 dark:bg-amber-950/30",
  "circuit.open": "text-red-600 bg-red-50 dark:bg-red-950/30",
  "circuit.half_open": "text-amber-600 bg-amber-50 dark:bg-amber-950/30",
  "circuit.closed": "text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30",
  "backup.failure": "text-red-600 bg-red-50 dark:bg-red-950/30",
  "provider.health_changed": "text-blue-600 bg-blue-50 dark:bg-blue-950/30",
};

const EVENT_TYPE_OPTIONS = [
  { key: "all", label: "全部" }, { key: "account", label: "账号" },
  { key: "circuit", label: "熔断" }, { key: "backup", label: "备份" }, { key: "provider", label: "Provider" },
];

function formatEventTime(ts: number): string {
  const d = new Date(ts * 1000);
  const diff = Date.now() - d.getTime();
  if (diff < 60000) return "刚刚";
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`;
  return d.toLocaleDateString("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function getEventLabel(type: string): string {
  const map: Record<string, string> = {
    "account.invalid": "账号失效", "account.recovered": "账号恢复", "account.quota_exhausted": "配额耗尽",
    "circuit.open": "熔断开启", "circuit.half_open": "熔断半开", "circuit.closed": "熔断关闭",
    "backup.failure": "备份失败", "provider.health_changed": "Provider 状态变更",
  };
  return map[type] || type;
}

function getEventGroup(type: string): string {
  if (type.startsWith("account")) return "account";
  if (type.startsWith("circuit")) return "circuit";
  if (type.startsWith("backup")) return "backup";
  if (type.startsWith("provider")) return "provider";
  return "other";
}

export function EventStream({
  events: initialEvents,
  onRefresh,
}: {
  events: DashboardEvent[];
  onRefresh?: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [detailId, setDetailId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (filter === "all") return initialEvents;
    return initialEvents.filter((e) => getEventGroup(e.type) === filter);
  }, [initialEvents, filter]);

  return (
    <Card className="rounded-xl border-stone-200 bg-white">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-stone-800">实时事件流</CardTitle>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 rounded-lg border border-stone-200 p-0.5">
              {EVENT_TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.key} type="button"
                  className={`rounded-md px-2 py-0.5 text-xs transition ${filter === opt.key ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-900"}`}
                  onClick={() => setFilter(opt.key)}
                >{opt.label}</button>
              ))}
            </div>
            {onRefresh ? (
              <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onRefresh}>
                <RefreshCw className="h-3.5 w-3.5" />
              </Button>
            ) : null}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {filtered.length === 0 ? (
          <p className="py-4 text-center text-sm text-stone-400">暂无事件记录</p>
        ) : (
          <div className="max-h-80 space-y-1 overflow-y-auto">
            {filtered.slice(0, 50).map((event) => {
              const Icon = EVENT_ICONS[event.type] || AlertTriangle;
              const colorClass = EVENT_COLORS[event.type] || "text-stone-600 bg-stone-50";
              const isOpen = detailId === event.id;
              return (
                <motion.div key={event.id} initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
                  <button
                    type="button"
                    className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-xs transition hover:bg-stone-50 ${colorClass}`}
                    onClick={() => setDetailId(isOpen ? null : event.id)}
                  >
                    <Icon className="h-3.5 w-3.5 flex-shrink-0" />
                    <span className="flex-1 truncate">{getEventLabel(event.type)}</span>
                    <span className="flex-shrink-0 text-stone-400">{formatEventTime(event.timestamp)}</span>
                  </button>
                  {isOpen && event.data && Object.keys(event.data).length > 0 ? (
                    <div className="mx-3 mb-1 rounded-md bg-stone-50 p-2 text-[11px] text-stone-600 dark:bg-stone-800 dark:text-stone-400">
                      <pre className="whitespace-pre-wrap">{JSON.stringify(event.data, null, 2)}</pre>
                    </div>
                  ) : null}
                </motion.div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}