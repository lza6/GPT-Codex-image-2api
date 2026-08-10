"use client";

import { useState } from "react";
import { useMotionValueEvent, useSpring } from "motion/react";
import { Activity, Shield, TrendingUp, Users, Zap } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

export interface KpiBarProps {
  totalAccounts: number;
  availableAccounts: number;
  breakerCount: number;
  todayRequests: number;
  successRate: number; // 0-100
  avgLatency: number; // ms
}

interface AnimatedNumberProps {
  value: number;
  format?: (v: number) => string;
}

/** 用 motion useSpring 驱动的数字滚动动画。 */
function AnimatedNumber({ value, format }: AnimatedNumberProps) {
  const spring = useSpring(value, { stiffness: 90, damping: 18, restDelta: 0.5 });
  const [display, setDisplay] = useState(value);
  useMotionValueEvent(spring, "change", (v) => setDisplay(v));
  return <span>{format ? format(display) : Math.round(display).toString()}</span>;
}

export function KpiBar({
  totalAccounts,
  availableAccounts,
  breakerCount,
  todayRequests,
  successRate,
  avgLatency,
}: KpiBarProps) {
  const kpis = [
    {
      icon: Users,
      label: "总账号",
      value: <AnimatedNumber value={totalAccounts} />,
      sub: `可用 ${availableAccounts}`,
      accent: "text-emerald-600",
    },
    {
      icon: Shield,
      label: "熔断数",
      value: <AnimatedNumber value={breakerCount} />,
      sub: breakerCount > 0 ? "需关注" : "全部正常",
      accent: breakerCount > 0 ? "text-rose-600" : "text-stone-500",
    },
    {
      icon: TrendingUp,
      label: "今日请求",
      value: <AnimatedNumber value={todayRequests} />,
      sub: "次调用",
      accent: "text-blue-600",
    },
    {
      icon: Activity,
      label: "成功率",
      value: <AnimatedNumber value={successRate} format={(v) => `${v.toFixed(1)}%`} />,
      sub: successRate >= 95 ? "优秀" : successRate >= 80 ? "正常" : "偏低",
      accent: successRate >= 95 ? "text-emerald-600" : successRate >= 80 ? "text-amber-600" : "text-rose-600",
    },
    {
      icon: Zap,
      label: "平均延迟",
      value: <AnimatedNumber value={avgLatency} format={(v) => `${Math.round(v)}ms`} />,
      sub: avgLatency <= 1500 ? "流畅" : "偏慢",
      accent: avgLatency <= 1500 ? "text-emerald-600" : "text-amber-600",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-5">
      {kpis.map((kpi, index) => (
        <Card key={index} className="overflow-hidden border-stone-200 bg-white dark:border-stone-800 dark:bg-stone-950">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-stone-500 dark:text-stone-400">
              <kpi.icon className={`h-4 w-4 ${kpi.accent}`} />
              <span className="text-xs font-medium">{kpi.label}</span>
            </div>
            <p className="mt-2 text-2xl font-semibold text-stone-900 dark:text-stone-100">{kpi.value}</p>
            <p className="mt-1 text-xs text-stone-400 dark:text-stone-500">{kpi.sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

export default KpiBar;
