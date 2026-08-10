"use client";

import { useMemo, useState } from "react";
import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar, Tooltip,
  LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Legend,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SchedulerDashboard } from "@/lib/api";

export function ProviderRadarChart({ scheduler }: { scheduler: SchedulerDashboard | null }) {
  const [view, setView] = useState<"radar" | "trend">("radar");

  const radarData = useMemo(() => {
    if (!scheduler?.provider_stats) return [];
    return scheduler.provider_stats
      .filter((ps) => ps.enabled && ps.total_accounts > 0)
      .map((ps) => {
        const total = ps.total_accounts;
        const available = ps.available_accounts;
        const successRate = total > 0 ? Math.round((available / total) * 100) : 0;
        const quotaRemaining = ps.quota_remaining === -1 ? 100 : Math.min(100, Math.round(((ps.quota_remaining ?? 0) / 60) * 100));
        const riskyRate = total > 0 ? Math.round(((ps.tiers?.risky ?? 0) / total) * 100) : 0;
        const load = Math.min(100, riskyRate + (ps.breaker_state === "open" ? 50 : 0));
        return { provider: ps.display_name || ps.name, 成功率: successRate, 延迟: 50, 配额余量: quotaRemaining, 负载: load };
      });
  }, [scheduler]);

  const trendData = useMemo(() => {
    if (!scheduler?.provider_stats) return [];
    return scheduler.provider_stats
      .filter((ps) => ps.enabled && ps.total_accounts > 0)
      .map((ps) => {
        const total = ps.total_accounts;
        return {
          name: ps.display_name || ps.name,
          可用率: total > 0 ? Math.round((ps.available_accounts / total) * 100) : 0,
          活跃占比: total > 0 ? Math.round(((total - (ps.tiers?.risky ?? 0)) / total) * 100) : 0,
        };
      });
  }, [scheduler]);

  if (!scheduler?.provider_stats?.length) return null;

  return (
    <Card className="rounded-xl border-stone-200 bg-white">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold text-stone-800">Provider 多维对比</CardTitle>
          <div className="flex items-center gap-1 rounded-lg border border-stone-200 p-0.5">
            <button type="button" className={`rounded-md px-2 py-0.5 text-xs transition ${view === "radar" ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-900"}`} onClick={() => setView("radar")}>雷达图</button>
            <button type="button" className={`rounded-md px-2 py-0.5 text-xs transition ${view === "trend" ? "bg-stone-900 text-white" : "text-stone-500 hover:text-stone-900"}`} onClick={() => setView("trend")}>趋势</button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {view === "radar" ? (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData} cx="50%" cy="50%" outerRadius="65%">
                <PolarGrid stroke="#e5e7eb" />
                <PolarAngleAxis dataKey="provider" tick={{ fontSize: 11 }} />
                <PolarRadiusAxis angle={30} domain={[0, 100]} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Radar name="成功率" dataKey="成功率" stroke="#059669" fill="#059669" fillOpacity={0.15} />
                <Radar name="延迟" dataKey="延迟" stroke="#d97706" fill="#d97706" fillOpacity={0.1} />
                <Radar name="配额余量" dataKey="配额余量" stroke="#2563eb" fill="#2563eb" fillOpacity={0.1} />
                <Radar name="负载" dataKey="负载" stroke="#dc2626" fill="#dc2626" fillOpacity={0.1} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10 }} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="可用率" stroke="#059669" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="活跃占比" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}