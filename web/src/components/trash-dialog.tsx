"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { LoaderCircle, Trash2, RotateCcw } from "lucide-react";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { clearTrash, fetchTrash, restoreTrash, type TrashItem, type TrashStats } from "@/lib/api";
import { toastError, toastSuccess } from "@/lib/toast-helper";

/** 上游原因展示：截断过长描述。 */
function truncate(value: string, n = 60) {
  const s = String(value || "");
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white/70 px-3 py-2.5">
      <div className="text-[11px] text-stone-500">{label}</div>
      <div className="mt-0.5 text-base font-semibold text-stone-900">{value}</div>
    </div>
  );
}

export function TrashDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const [items, setItems] = useState<TrashItem[]>([]);
  const [stats, setStats] = useState<TrashStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedEmails, setSelectedEmails] = useState<Set<string>>(new Set());
  const [isClearing, setIsClearing] = useState(false);

  /** 原因 Top N 分布（新后端直接取 by_reason_top，旧后端回退到 by_reason 切片）。 */
  const reasonData = useMemo(() => {
    if (stats?.by_reason_top) return stats.by_reason_top;
    return Object.entries(stats?.by_reason ?? {})
      .slice(0, 8)
      .map(([reason, count]) => ({ reason, count }));
  }, [stats]);

  /** 按天趋势（新后端直接取 trend，旧后端回退到 by_day 升序）。 */
  const trendData = useMemo(() => {
    if (stats?.trend && stats.trend.length > 0) return stats.trend;
    return Object.entries(stats?.by_day ?? {})
      .map(([day, count]) => ({ day, count }))
      .sort((a, b) => a.day.localeCompare(b.day));
  }, [stats]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTrash(200);
      setItems(data.items);
      setStats(data.stats);
    } catch (error) {
      toastError(error, "加载回收站失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  const handleClear = async () => {
    if (!window.confirm(`确认清空回收站（${items.length} 条记录）？此操作不可恢复。`)) return;
    setIsClearing(true);
    try {
      const res = await clearTrash();
      toastSuccess(`已清空 ${res.cleared} 条回收记录`);
      setItems([]);
      setStats(null);
      setSelectedEmails(new Set());
    } catch (error) {
      toastError(error, "清空回收站失败");
    } finally {
      setIsClearing(false);
    }
  };

  const handleRestore = async () => {
    if (selectedEmails.size === 0) {
      toast.error("请先勾选要恢复的账号");
      return;
    }
    try {
      const emails = Array.from(selectedEmails);
      const res = await restoreTrash(emails);
      toastSuccess(`已从回收站移除 ${res.restored} 条记录（实际恢复需重新导入号池）`);
      await load();
    } catch (error) {
      toastError(error, "恢复失败");
    }
  };

  const toggle = (email: string) => {
    setSelectedEmails((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(94vw,760px)] rounded-2xl">
        <DialogHeader>
          <DialogTitle>回收站</DialogTitle>
          <DialogDescription>被自动剔除/手动删除的账号记录，含剔除时间与上游返回原因。</DialogDescription>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <LoaderCircle className="size-5 animate-spin text-stone-400" />
          </div>
        ) : (
          <>
            {/* 统计卡片 */}
            {stats ? (
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatCard label="累计剔除" value={stats.total} />
                <StatCard label="异常" value={stats.by_status?.["异常"] ?? 0} />
                <StatCard label="禁用" value={stats.by_status?.["禁用"] ?? 0} />
                <StatCard label="其他" value={(stats.total ?? 0) - (stats.by_status?.["异常"] ?? 0) - (stats.by_status?.["禁用"] ?? 0)} />
              </div>
            ) : null}

            {/* 原因 Top N 分布 */}
            {reasonData.length > 0 ? (
              <div>
                <div className="mb-1 text-xs font-medium text-stone-500">剔除原因分布（Top {reasonData.length}）</div>
                <div className="h-40 rounded-xl border border-stone-200 bg-white/70 p-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart layout="vertical" data={reasonData} margin={{ left: 8, right: 16 }}>
                      <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e7e5e4" />
                      <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                      <YAxis
                        type="category"
                        dataKey="reason"
                        width={140}
                        tick={{ fontSize: 11 }}
                        tickFormatter={(v: string) => truncate(v, 16)}
                      />
                      <Tooltip />
                      <Bar dataKey="count" name="剔除数" fill="#d97706" radius={[0, 4, 4, 0]} barSize={10} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : null}

            {/* 按天剔除趋势 */}
            {trendData.length > 0 ? (
              <div>
                <div className="mb-1 text-xs font-medium text-stone-500">按天剔除趋势</div>
                <div className="h-32 rounded-xl border border-stone-200 bg-white/70 p-2">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={trendData} margin={{ left: -12, right: 16 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e7e5e4" />
                      <XAxis dataKey="day" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
                      <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                      <Tooltip />
                      <Line type="monotone" dataKey="count" name="剔除数" stroke="#1e293b" strokeWidth={2} dot={{ r: 2 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            ) : null}

            {/* 列表 */}
            {items.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-1 py-12 text-sm text-stone-400">
                <Trash2 className="size-6" />
                <span>回收站为空</span>
              </div>
            ) : (
              <div className="max-h-[46vh] space-y-1.5 overflow-y-auto pr-1">
                {items.map((item) => {
                  const email = item.email || item.access_token || "—";
                  const selected = selectedEmails.has(email);
                  return (
                    <div
                      key={item.removed_at + email}
                      className="flex items-start gap-2 rounded-xl border border-stone-200 bg-white/70 px-3 py-2"
                    >
                      <input
                        type="checkbox"
                        className="mt-1 size-3.5 shrink-0 accent-stone-900"
                        checked={selected}
                        onChange={() => toggle(email)}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="truncate text-sm font-medium text-stone-900">{email}</span>
                          <Badge
                            variant={item.status === "禁用" ? "danger" : item.status === "异常" ? "warning" : "outline"}
                            className="rounded-lg"
                          >
                            {item.status || "未知"}
                          </Badge>
                          <span className="text-[11px] text-stone-400">{item.source || ""}</span>
                        </div>
                        {item.reason ? (
                          <div className="mt-0.5 text-xs text-stone-600" title={item.reason}>
                            原因：{truncate(item.reason, 80)}
                          </div>
                        ) : null}
                        <div className="mt-0.5 text-[11px] text-stone-400">剔除时间：{item.removed_at || "—"}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        <DialogFooter className="flex items-center gap-2 sm:justify-between">
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void handleRestore()} disabled={selectedEmails.size === 0}>
              <RotateCcw className="size-3.5" />
              恢复所选
            </Button>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              刷新
            </Button>
          </div>
          <Button variant="destructive" size="sm" onClick={() => void handleClear()} disabled={isClearing || items.length === 0}>
            <Trash2 className="size-3.5" />
            {isClearing ? "清空中…" : "清空回收站"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
