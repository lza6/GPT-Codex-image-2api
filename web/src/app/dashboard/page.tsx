"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Activity, Cpu, Database, HardDrive, RefreshCw, Server, Timer, Users } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  fetchLatencySummary,
  fetchMetricsSummary,
  fetchOpsOverview,
  fetchSchedulerDashboard,
  fetchUsageStats,
  type LatencySummary,
  type MetricsSummary,
  type OpsOverview,
  type SchedulerAccount,
  type SchedulerDashboard,
  type SchedulerTier,
  type UsageStats,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { getStoredAuthKey } from "@/store/auth";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";

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
  useAuthGuard();

  const [scheduler, setScheduler] = useState<SchedulerDashboard | null>(null);
  const [ops, setOps] = useState<OpsOverview | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [latency, setLatency] = useState<LatencySummary | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  const [isRefreshing, setIsRefreshing] = useState(false);
  const load = useCallback(async () => {
    setIsRefreshing(true);
    try {
      const [sched, opsData, usageData, latencyData, metricsData] = await Promise.all([
        fetchSchedulerDashboard(),
        fetchOpsOverview(),
        fetchUsageStats(),
        fetchLatencySummary(),
        fetchMetricsSummary(),
      ]);
      setScheduler(sched);
      setOps(opsData);
      setUsage(usageData);
      setLatency(latencyData);
      setMetrics(metricsData);
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
    const connect = async () => {
      if (source || cancelled) return;
      const token = await getStoredAuthKey();
      if (!token || cancelled) return;
      source = new EventSource(`/api/dashboard/stream?token=${encodeURIComponent(token)}`);
      attachHandlers(source);
    };
    const disconnect = () => {
      source?.close();
      source = null;
    };
    const onVisibility = () => {
      if (document.hidden) {
        disconnect();
      } else {
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
      src.onerror = () => {
        // 断连（含 token 失效 401）时主动关闭并允许重连逻辑再次建立；
        // 轮询兜底独立运行，看板不会因流通道故障而停更（第七轮 F4）
        source?.close();
        source = null;
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
    return [...scheduler.accounts].sort((a, b) => b.score - a.score).slice(0, 10);
  }, [scheduler]);

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

  if (loading && !scheduler) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-stone-200 dark:bg-stone-700" />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
          ))}
        </div>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
          ))}
        </div>
        <div className="h-64 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
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
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={isRefreshing}>
          <RefreshCw className={`mr-1 h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
          {isRefreshing ? "刷新中" : "刷新"}
        </Button>
      </div>

      {/* 账号池总览 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard icon={Users} label="账号总数" value={String(health?.total ?? 0)} sub={`总配额 ${health?.total_quota ?? 0}`} />
        <StatCard icon={Activity} label="健康账号" value={String(health?.tiers?.healthy ?? 0)} sub={`温存 ${health?.tiers?.warm ?? 0} · 风险 ${health?.tiers?.risky ?? 0}`} />
        <StatCard icon={Timer} label="在途图片" value={String(health?.total_inflight ?? 0)} sub={`并发上限 ${ops?.image_account_concurrency ?? "-"}`} />
        <StatCard icon={Activity} label="近24h调用" value={String(usage?.total_24h ?? 0)} sub={`成功 ${usage?.success_24h ?? 0} · 失败 ${usage?.failed_24h ?? 0}`} />
      </div>

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
          <CardTitle className="text-base">调度排行榜（健康档位 + 调度分）</CardTitle>
          <p className="text-xs text-stone-400">模式: {ops?.scheduler_mode ?? "-"} · 每30秒自动刷新</p>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>邮箱</TableHead>
                <TableHead>类型</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>档位</TableHead>
                <TableHead className="text-right">配额</TableHead>
                <TableHead className="text-right">调度分</TableHead>
                <TableHead className="text-right">在途</TableHead>
                <TableHead className="text-right">成功/失败</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {topAccounts.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="py-8 text-center text-stone-400">
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
