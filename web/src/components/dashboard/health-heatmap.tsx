"use client";

import { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SchedulerDashboard } from "@/lib/api";

const HEALTH_COLORS: Record<string, string> = {
  healthy: "bg-emerald-400",
  warm: "bg-amber-400",
  risky: "bg-red-400",
  banned: "bg-stone-300",
  unknown: "bg-stone-200",
};

const HEALTH_LABELS: Record<string, string> = {
  healthy: "健康", warm: "温存", risky: "风险", banned: "禁用/异常", unknown: "未知",
};

export function AccountHealthHeatmap({ scheduler }: { scheduler: SchedulerDashboard | null }) {
  const groups = useMemo(() => {
    if (!scheduler?.accounts?.length) return [];
    const map = new Map<string, typeof scheduler.accounts>();
    for (const acc of scheduler.accounts) {
      const provider = (acc as unknown as { provider?: string }).provider || "default";
      if (!map.has(provider)) map.set(provider, []);
      map.get(provider)!.push(acc);
    }
    return Array.from(map.entries()).map(([provider, accounts]) => ({
      provider,
      accounts: accounts.map((a) => ({ email: a.email ?? "-", tier: a.tier || "unknown", score: a.score })),
    }));
  }, [scheduler]);

  if (!scheduler?.accounts?.length) return null;

  const total = scheduler.accounts.length;
  const healthyCount = scheduler.accounts.filter((a) => a.tier === "healthy").length;
  const warmCount = scheduler.accounts.filter((a) => a.tier === "warm").length;
  const riskyCount = scheduler.accounts.filter((a) => a.tier === "risky").length;

  return (
    <Card className="rounded-xl border-stone-200 bg-white">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-semibold text-stone-800">账号健康热力图</CardTitle>
        <div className="flex items-center gap-3 text-xs text-stone-500">
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-emerald-400" /> 健康 {healthyCount}</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-amber-400" /> 温存 {warmCount}</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-red-400" /> 风险 {riskyCount}</span>
          <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-2.5 rounded-sm bg-stone-300" /> 禁用 {total - healthyCount - warmCount - riskyCount}</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {groups.map((group) => (
            <div key={group.provider}>
              <p className="mb-1 text-xs font-medium text-stone-500">{group.provider === "default" ? "未分组" : group.provider}</p>
              <div className="flex flex-wrap gap-1">
                {group.accounts.map((acc) => (
                  <div
                    key={acc.email}
                    className={`h-4 w-4 rounded-sm ${HEALTH_COLORS[acc.tier] || HEALTH_COLORS.unknown} cursor-default`}
                    title={`${acc.email} · ${HEALTH_LABELS[acc.tier] || "未知"} · 调度分 ${acc.score?.toFixed(1) ?? "-"}`}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}