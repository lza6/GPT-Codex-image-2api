"use client";

import { motion } from "motion/react";
import { useMemo } from "react";
import { Activity, AlertTriangle, Ban, Timer, TrendingUp, Users } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import type { MetricsSummary, OpsOverview, SchedulerDashboard, UsageForecast, UsageStats } from "@/lib/api";

function AnimatedNumber({ value, duration = 0.5 }: { value: number; duration?: number }) {
  const display = useMemo(() => {
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
    return String(value);
  }, [value]);

  return (
    <motion.span
      key={value}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration, ease: [0.16, 1, 0.3, 1] }}
      className="tabular-nums"
    >
      {display}
    </motion.span>
  );
}

type KpiItem = {
  icon: typeof Users;
  label: string;
  value: number;
  sub?: string;
  color: string;
};

export function KpiBar({
  scheduler,
  usage,
  forecast,
}: {
  scheduler: SchedulerDashboard | null;
  ops: OpsOverview | null;
  usage: UsageStats | null;
  metrics: MetricsSummary | null;
  forecast: UsageForecast | null;
}) {
  const items: KpiItem[] = useMemo(() => {
    const health = scheduler?.health;
    return [
      { icon: Users, label: "总账号", value: health?.total ?? 0, sub: `可用 ${health?.tiers?.healthy ?? 0}`, color: "text-stone-900" },
      { icon: Activity, label: "健康", value: health?.tiers?.healthy ?? 0, sub: `温存 ${health?.tiers?.warm ?? 0}`, color: "text-emerald-600" },
      { icon: Ban, label: "熔断", value: 0, color: "text-red-600" },
      { icon: Timer, label: "今日请求", value: usage?.total_24h ?? 0, sub: `成功 ${usage?.success_24h ?? 0}`, color: "text-blue-600" },
      { icon: TrendingUp, label: "成功率", value: usage?.total_24h ? Math.round((usage.success_24h / usage.total_24h) * 100) : 100, sub: "%", color: "text-emerald-600" },
      { icon: AlertTriangle, label: "配额耗尽", value: forecast?.days_until_depletion ?? 0, sub: forecast?.status === "ok" ? "天" : "N/A", color: forecast?.should_alert ? "text-amber-600" : "text-stone-600" },
    ];
  }, [scheduler, usage, forecast]);

  return (
    <div className="flex gap-3 overflow-x-auto pb-2 hide-scrollbar">
      {items.map((item) => (
        <Card key={item.label} className="min-w-[140px] flex-shrink-0 rounded-xl border-stone-200 bg-white/80 backdrop-blur-sm">
          <CardContent className="p-3">
            <div className="flex items-center gap-1.5 text-stone-500">
              <item.icon className="h-3.5 w-3.5" />
              <span className="text-xs font-medium">{item.label}</span>
            </div>
            <p className={`mt-1 text-xl font-semibold ${item.color}`}>
              <AnimatedNumber value={item.value} />
            </p>
            {item.sub ? <p className="mt-0.5 text-[11px] text-stone-400">{item.sub}</p> : null}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}