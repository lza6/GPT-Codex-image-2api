"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, AlertTriangle, Cpu, Database, HardDrive, RefreshCw, Server, Timer, TrendingDown, Users } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { AsyncButton } from "@/components/ui/async-button";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  fetchLatencySummary,
  fetchMetricsSummary,
  fetchOpsOverview,
  fetchSchedulerDashboard,
  fetchUsageForecast,
  fetchUsageStats,
  type LatencySummary,
  type MetricsSummary,
  type OpsOverview,
  type SchedulerAccount,
  type SchedulerDashboard,
  type SchedulerTier,
  type UsageForecast,
  type UsageStats,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { Skeleton, SkeletonCards } from "@/components/ui/skeleton";
import { getStoredAuthKey } from "@/store/auth";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";

const TIER_LABELS: Record<SchedulerTier, string> = {
  healthy: "健康",
  warm: "温存",
  risky: "风险",
  banned: "禁用",
};

const TIER_COLORS: Record<SchedulerTier, string> = {
  healthy: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  warm: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  risky: "bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-300",
  banned: "bg-stone-200 text-stone-600 dark:bg-stone-700 dark:text-stone-300",
};

// 3.7.2：调度排行榜档位筛选（风险账号可见性）
type TierFilter = "all" | "warm_risk" | "risk";
const TIER_FILTER_OPTIONS: { key: TierFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "warm_risk", label: "风险+温存" },
  { key: "risk", label: "仅风险" },
];

function formatUptime(seconds: number) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}天 ${hours}小时`;
  if (hours > 0) return `${hours}小时 ${mins}分`;
  return `${mins}分`;
}

function StatCard({ icon: Icon, label, value, sub }: { icon: typeof Cpu; label: string; value: string; sub?: string }) {
  return (
    <Card className="rounded-xl border-stone-200 bg-white">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-stone-500">
          <Icon className="h-4 w-4" />
          <span className="text-xs font-medium">{label}</span>
        </div>
        <p className="mt-2 text-2xl font-semibold text-stone-900">{value}</p>
        {sub ? <p className="mt-1 text-xs text-stone-400">{sub}</p> : null}
      </CardContent>
    </Card>
  );
}

function DashboardContent() {
  useAuthGuard(["admin"]);

  const [scheduler, setScheduler] = useState<SchedulerDashboard | null>(null);
  const [ops, setOps] = useState<OpsOverview | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [forecast, setForecast] = useState<UsageForecast | null>(null);
  const [latency, setLatency] = useState<LatencySummary | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [tierFilter, setTierFilter] = useState<TierFilter>("all");

  const [isRefreshing, setIsRefreshing] = useState(false);
  const load = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [sched, opsData, usageData, latencyData, metricsData, forecastData] = await Promise.all([
        fetchSchedulerDashboard(),
        fetchOpsOverview(),
        fetchUsageStats(),
        fetchLatencySummary(),
        fetchMetricsSummary(),
        fetchUsageForecast(),
      ]);
      setScheduler(sched);
      setOps(opsData);
      setUsage(usageData);
      setLatency(latencyData);
      setMetrics(metricsData);
      setForecast(forecastData);
    } catch (error) {
      // 网络层失败（拦截器未覆盖）也给出反馈，避免永久骨架屏 + 静默轮询 rejection
      toast.error(error instanceof Error ? error.message : "加载看板失败");
    } finally {
      setLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();

    // SSE 实时推送：订阅后端 dashboard 流，每 3 秒更新一次
    // token 存在 localforage（IndexedDB），不是 localStorage——第七轮 F2 修复：
    // 此前从 localStorage 读取恒为 null，SSE 通道静默失效只剩 30s 轮询兜底
    let cancelled = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let retryDelay = 1000; // 指数退避起点 1s，上限 30s
    let reconnect = false;

    const scheduleReconnect = () => {
      if (cancelled || reconnect) return;
      reconnect = true;
      reconnectTimer = setTimeout(() => {
        reconnect = false;
        if (!cancelled && !document.hidden) {
          void connect();
        }
      }, retryDelay);
      retryDelay = Math.min(retryDelay * 2, 30000);
    };

    const connect = async () => {
      if (source || cancelled) return;
      const token = await getStoredAuthKey();
      if (!token || cancelled) return;
      try {
        source = new EventSource(`/api/dashboard/stream?token=${encodeURIComponent(token)}`);
        attachHandlers(source);
      } catch {
        // 同步构造失败（极少见）也走重连
        source = null;
        scheduleReconnect();
      }
    };
    const disconnect = () => {
      reconnect = false;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      source?.close();
      source = null;
    };
    const onVisibility = () => {
      if (document.hidden) {
        disconnect();
      } else {
        retryDelay = 1000; // 回到前台重置退避
        void load();
        connect();
      }
    };

    const attachHandlers = (src: EventSource) => {
      src.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data);
          if (payload.type === "dashboard") {
            if (payload.latency) {
              setLatency(payload.latency);
            }
            // 完整看板数据：ops/usage/metrics_summary 经 SSE 实时更新（资源/用量/指标卡片）
            if (payload.ops) {
              setOps(payload.ops);
            }
            if (payload.usage) {
              setUsage(payload.usage);
            }
            if (payload.metrics_summary) {
              setMetrics(payload.metrics_summary);
            }
            // health 数据触发完整刷新以同步调度分等
            setScheduler((prev) =>
              prev
                ? {
                    ...prev,
                    health: payload.health,
                  }
                : prev,
            );
          }
        } catch {
          // 忽略解析错误
        }
      };
      src.onopen = () => {
        // P1-1：连接成功重置退避起点，避免偶发抖动后长退避
        retryDelay = 1000;
      };
      src.onerror = () => {
        // P1-1：断连（含 token 失效 401）时关闭并指数退避自动重连——
        // 原实现只 close 不重连，SSE 从"实时"静默退化为 30s 轮询（假降级）
        source?.close();
        source = null;
        scheduleReconnect();
      };
    };

    void connect();
    document.addEventListener("visibilitychange", onVisibility);

    // 兜底轮询：SSE 不可用时 30s 轮询（页面隐藏时跳过，避免后台积压）
    const timer = setInterval(() => {
      if (!document.hidden) {
        void load();
      }
    }, 30000);

    return () => {
      cancelled = true;
      disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      clearInterval(timer);
    };
  }, [load]);

  const topAccounts = useMemo(() => {
    if (!scheduler) return [];
    let accounts = [...scheduler.accounts];
    if (tierFilter === "risk") accounts = accounts.filter((a) => a.tier === "risky");
    if (tierFilter === "warm_risk") accounts = accounts.filter((a) => a.tier === "risky" || a.tier === "warm");
    accounts.sort((a, b) => b.score - a.score);
    // 3.7.2：默认视图截断前 10（保持原行为）；风险筛选中显示该档位全部，
    // 保证风险档账号无论排位都能一屏定位，不被 slice(0,10) 截断在榜单外。
    return tierFilter === "all" ? accounts.slice(0, 10) : accounts;
  }, [scheduler, tierFilter]);

  // 连接池并发：当前正在使用的账号（image_inflight > 0）
  const inUseAccounts = useMemo(() => {
    if (!scheduler) return [];
    return scheduler.accounts.filter((a) => a.image_inflight > 0);
  }, [scheduler]);

  // 今日用完：配额为 0 的账号
  const exhaustedAccounts = useMemo(() => {
    if (!scheduler) return [];
    return scheduler.accounts.filter((a) => a.quota <= 0 && a.status !== "禁用" && a.status !== "异常");
  }, [scheduler]);

  // 5.1：濒危账号（寿命预测 high/critical）
  const criticalAccounts = useMemo(() => {
    if (!scheduler) return [];
    return scheduler.accounts.filter((a) => a.lifetime_risk === "high" || a.lifetime_risk === "critical");
  }, [scheduler]);

  const LIFETIME_LABELS: Record<string, string> = {
    low: "健康",
    medium: "关注",
    high: "偏高",
    critical: "濒危",
  };
  const LIFETIME_COLORS: Record<string, string> = {
    low: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
    medium: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
    high: "bg-orange-100 text-orange-800 dark:bg-orange-950/40 dark:text-orange-300",
    critical: "bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
  };

  if (loading && !scheduler) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-40" />
        <SkeletonCards count={4} />
        <SkeletonCards count={4} />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  const health = scheduler?.health;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-stone-900">运维看板</h1>
          <p className="text-sm text-stone-500">调度健康度 · 资源占用 · 用量统计</p>
        </div>
        <AsyncButton variant="outline" size="sm" onClick={() => load()} isLoading={isRefreshing} icon={<RefreshCw className="h-4 w-4" />}>
          {isRefreshing ? "刷新中" : "刷新"}
        </AsyncButton>
      </div>

      {/* 用量预测告警（F2/A2）：临近配额耗尽提前预警 */}
      {forecast && forecast.status === "ok" && (
        <div className={`rounded-2xl border p-4 ${forecast.should_alert ? "border-amber-300 bg-amber-50" : "border-stone-200 bg-white"}`}>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <div className="flex items-center gap-2">
              {forecast.should_alert ? (
                <AlertTriangle className="h-5 w-5 text-amber-600" />
              ) : (
                <TrendingDown className="h-5 w-5 text-emerald-600" />
              )}
              <span className={`text-sm font-medium ${forecast.should_alert ? "text-amber-800" : "text-stone-700"}`}>
                {forecast.should_alert
                  ? `配额预计 ${forecast.days_until_depletion} 天后耗尽（${forecast.estimated_depletion_date}）`
                  : `按当前速率约 ${forecast.days_until_depletion ?? "∞"} 天后耗尽配额`}
              </span>
            </div>
            <span className="text-xs text-stone-500">
              近{forecast.window_days}天日均消耗 {forecast.daily_avg_consumption} · 剩余配额 {forecast.total_remaining_quota}（{forecast.quota_accounts} 个账号）
            </span>
            <span className="text-xs text-stone-400">阈值 {forecast.alert_threshold_days} 天</span>
          </div>
          {forecast.daily_series.length > 0 && (
            <div className="mt-3 h-20">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={forecast.daily_series} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
                  <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                  <Tooltip />
                  <Line type="monotone" dataKey="calls" stroke={forecast.should_alert ? "#d97706" : "#059669"} strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
      {forecast && (forecast.status === "unlimited" || forecast.status === "insufficient_data" || forecast.status === "exhausted") && (
        <div className={`rounded-2xl border p-4 text-sm ${forecast.status === "exhausted" ? "border-rose-200 bg-rose-50 text-rose-700" : "border-stone-200 bg-white text-stone-500"}`}>
          {forecast.status === "unlimited" && "号池全部为无限配额账号，无需耗尽预测。"}
          {forecast.status === "exhausted" && "号池无正向配额账号（配额已耗尽或为空），请检查号池状态。"}
          {forecast.status === "insufficient_data" && "用量数据不足，暂无法预测配额耗尽时间。"}
        </div>
      )}

      {/* 账号池总览 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard icon={Users} label="账号总数" value={String(health?.total ?? 0)} sub={`总配额 ${health?.total_quota ?? 0}`} />
        <StatCard icon={Activity} label="健康账号" value={String(health?.tiers?.healthy ?? 0)} sub={`温存 ${health?.tiers?.warm ?? 0} · 风险 ${health?.tiers?.risky ?? 0}`} />
        <StatCard icon={Timer} label="在途图片" value={String(health?.total_inflight ?? 0)} sub={`并发上限 ${ops?.image_account_concurrency ?? "-"}`} />
        <StatCard icon={Activity} label="近24h调用" value={String(usage?.total_24h ?? 0)} sub={`成功 ${usage?.success_24h ?? 0} · 失败 ${usage?.failed_24h ?? 0}`} />
      </div>

      {/* 5.1：濒危账号预警（寿命预测 high/critical） */}
      {criticalAccounts.length > 0 && (
        <div className="rounded-2xl border border-rose-200 bg-rose-50/70 p-4 dark:border-rose-800 dark:bg-rose-950/30">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-rose-600" />
            <span className="text-sm font-semibold text-rose-800 dark:text-rose-300">
              濒危账号预警（{criticalAccounts.length} 个）
            </span>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {criticalAccounts.map((account) => (
              <Badge
                key={account.email ?? account.score}
                className="bg-white text-rose-700 ring-1 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-300"
              >
                {account.email ?? "-"}
                {account.lifetime_eta_days != null ? ` · 约 ${account.lifetime_eta_days} 天` : ""}
              </Badge>
            ))}
          </div>
          <p className="mt-2 text-xs text-rose-500">基于失败率趋势 + 连续失效窗口预测，建议提前处理或补号。</p>
        </div>
      )}

      {/* 资源占用 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard icon={Cpu} label="CPU" value={`${ops?.cpu_percent ?? 0}%`} />
        <StatCard
          icon={Database}
          label="内存"
          value={ops?.memory_used_mb != null ? `${ops.memory_used_mb} MB` : "-"}
          sub={ops?.memory_total_mb != null ? `总 ${ops.memory_total_mb} MB` : undefined}
        />
        <StatCard icon={HardDrive} label="磁盘剩余" value={`${ops?.disk_free_mb ?? 0} MB`} sub={`总 ${ops?.disk_total_mb ?? 0} MB`} />
        <StatCard icon={Server} label="运行时长" value={ops ? formatUptime(ops.uptime_seconds) : "-"} sub={`${ops?.platform ?? ""}`} />
        <StatCard
          icon={Database}
          label="备份状态"
          value={
            !ops?.backup?.configured
              ? "未配置"
              : ops.backup.running
                ? "执行中"
                : ops.backup.last_status === "success"
                  ? "成功"
                  : ops.backup.last_status === "error"
                    ? "失败"
                    : "空闲"
          }
          sub={ops?.backup?.last_finished_at ? `最近 ${ops.backup.last_finished_at}` : undefined}
        />
      </div>
      {ops?.backup?.last_status === "error" && ops.backup.last_error ? (
        <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-2 text-xs text-rose-700">
          备份失败：{ops.backup.last_error}
        </div>
      ) : null}

      {/* 请求延迟与连接池并发 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard icon={Timer} label="总请求数" value={String(latency?.total_requests ?? 0)} sub={`错误 ${latency?.total_errors ?? 0}`} />
        <StatCard icon={Activity} label="平均延迟" value={`${latency?.avg_latency_ms ?? 0} ms`} sub={`错误率 ${((latency?.error_rate ?? 0) * 100).toFixed(2)}%`} />
        <StatCard icon={Users} label="使用中账号" value={String(inUseAccounts.length)} sub={`并发在途 ${inUseAccounts.reduce((s, a) => s + a.image_inflight, 0)}`} />
        <StatCard icon={Activity} label="配额用完" value={String(exhaustedAccounts.length)} sub="今日额度已耗尽" />
      </div>

      {/* 请求速率 / 错误率 / P95 */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard icon={Activity} label="请求速率" value={`${metrics?.request_rate ?? 0} req/s`} sub={`总请求 ${metrics?.total_requests ?? 0}`} />
        <StatCard icon={Activity} label="错误率" value={`${((metrics?.error_rate ?? 0) * 100).toFixed(2)}%`} sub={`总错误 ${metrics?.total_errors ?? 0}`} />
        <StatCard icon={Timer} label="P95 延迟" value={`${metrics?.p95_latency_ms ?? 0} ms`} sub={`平均 ${metrics?.avg_latency_ms ?? 0} ms`} />
      </div>

      {/* 使用中账号实时列表 */}
      {inUseAccounts.length > 0 && (
        <Card className="rounded-xl border-emerald-200 bg-emerald-50/50 dark:border-emerald-800 dark:bg-emerald-950/30">
          <CardHeader className="pb-2">
            <CardTitle className="text-base text-emerald-900 dark:text-emerald-300">正在使用的账号（实时）</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {inUseAccounts.map((account) => (
                <Badge key={account.email} className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">
                  {account.email ?? "-"} · 在途 {account.image_inflight}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 延迟按路径分布 */}
      {latency && Object.keys(latency.by_path).length > 0 && (
        <Card className="rounded-xl border-stone-200 bg-white">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">请求延迟分布（按路径）</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>路径</TableHead>
                  <TableHead className="text-right">请求数</TableHead>
                  <TableHead className="text-right">错误</TableHead>
                  <TableHead className="text-right">平均延迟</TableHead>
                  <TableHead className="text-right">错误率</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(latency.by_path).map(([path, agg]) => (
                  <TableRow key={path}>
                    <TableCell className="font-mono text-xs">{path}</TableCell>
                    <TableCell className="text-right">{agg.count}</TableCell>
                    <TableCell className="text-right text-rose-600">{agg.errors}</TableCell>
                    <TableCell className="text-right">{agg.avg_latency_ms} ms</TableCell>
                    <TableCell className="text-right">{(agg.error_rate * 100).toFixed(2)}%</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {/* 调度排行榜 */}
      <Card className="rounded-xl border-stone-200 bg-white">
        <CardHeader className="pb-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-base">调度排行榜（健康档位 + 调度分）</CardTitle>
            <div className="flex items-center gap-1 rounded-lg border border-stone-200 p-1">
              {TIER_FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  className={`rounded-md px-2.5 py-1 text-xs transition ${
                    tierFilter === opt.key
                      ? "bg-stone-900 text-white"
                      : "text-stone-500 hover:bg-stone-100 hover:text-stone-900"
                  }`}
                  onClick={() => setTierFilter(opt.key)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
          <p className="text-xs text-stone-400">模式: {ops?.scheduler_mode ?? "-"} · 每30秒自动刷新</p>
        </CardHeader>
        <CardContent>
          {/* 6.5：窄屏横向滚动，防表格溢出 */}
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>邮箱</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>档位</TableHead>
                  <TableHead>寿命</TableHead>
                  <TableHead className="text-right">配额</TableHead>
                  <TableHead className="text-right">调度分</TableHead>
                  <TableHead className="text-right">在途</TableHead>
                  <TableHead className="text-right">成功/失败</TableHead>
                </TableRow>
              </TableHeader>
            <TableBody>
              {topAccounts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-stone-400">
                    暂无可用账号
                  </TableCell>
                </TableRow>
              ) : (
                topAccounts.map((account, index) => (
                  <TableRow key={`${account.email ?? index}`}>
                    <TableCell className="max-w-[200px] truncate font-medium">{account.email ?? "-"}</TableCell>
                    <TableCell>{account.type ?? "-"}</TableCell>
                    <TableCell>{account.status ?? "-"}</TableCell>
                    <TableCell>
                      <Badge className={TIER_COLORS[account.tier]}>{TIER_LABELS[account.tier]}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={LIFETIME_COLORS[account.lifetime_risk ?? "low"]}>
                        {LIFETIME_LABELS[account.lifetime_risk ?? "low"]}
                        {account.lifetime_eta_days != null ? ` · ${account.lifetime_eta_days}d` : ""}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">{account.quota}</TableCell>
                    <TableCell className="text-right font-semibold">{account.score.toFixed(1)}</TableCell>
                    <TableCell className="text-right">{account.image_inflight}</TableCell>
                    <TableCell className="text-right text-xs">
                      {account.success}/{account.fail}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* 用量分布 */}
      <Card className="rounded-xl border-stone-200 bg-white">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">近24h 调用分布</CardTitle>
        </CardHeader>
        <CardContent>
          {usage ? (
            <>
              <div className="mb-4 h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={Object.entries(usage.by_summary).map(([name, count]) => ({ name, count }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                    <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} />
                    <Tooltip />
                    <Legend />
                    <Bar dataKey="count" name="调用次数" fill="#1e293b" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="flex flex-wrap gap-2">
                <Badge variant="secondary" className="rounded-full">成功 {usage.success_24h} 次</Badge>
                <Badge variant="secondary" className="rounded-full text-red-600">失败 {usage.failed_24h} 次</Badge>
                <Badge variant="secondary" className="rounded-full">合计 {usage.total_24h} 次</Badge>
              </div>
            </>
          ) : (
            <p className="py-4 text-center text-sm text-stone-400">近24h暂无调用记录</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

export default function DashboardPage() {
  return <DashboardContent />;
}
