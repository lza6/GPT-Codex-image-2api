"use client";

import { useCallback, useEffect, useState } from "react";
import { Activity, Globe, Plus, RefreshCw, Trash2, Wifi } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { httpRequest } from "@/lib/request";
import { useAuthGuard } from "@/lib/use-auth-guard";

type ProxyEntry = {
  url: string;
  healthy: boolean;
  last_check: number;
  latency_ms: number;
  success_rate: number;
  weight: number;
  active_conns: number;
  total_requests: number;
  failed_requests: number;
  status: string;
  consecutive_failures: number;
};

type ProxyPoolData = {
  proxies: ProxyEntry[];
  stats: {
    total: number;
    healthy: number;
    isolated: number;
    unhealthy: number;
    strategy: string;
  };
};

type EgressIpResult = {
  ok: boolean;
  ip?: string;
  proxy?: string;
  error?: string;
};

function fetchProxyPool() {
  return httpRequest<ProxyPoolData>("/api/proxies");
}

function addProxy(url: string, weight: number) {
  return httpRequest<{ ok: boolean }>("/api/proxies", {
    method: "POST",
    body: { url, weight },
  });
}

function removeProxy(url: string) {
  return httpRequest<{ ok: boolean }>(`/api/proxies/${encodeURIComponent(url)}`, {
    method: "DELETE",
  });
}

function setStrategy(strategy: string) {
  return httpRequest<{ ok: boolean }>("/api/proxies/strategy", {
    method: "POST",
    body: { strategy },
  });
}

function probeEgressIp() {
  return httpRequest<EgressIpResult>("/api/proxies/egress-ip");
}

function formatTime(ts: number) {
  if (!ts) return "-";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

function ProxyPoolContent() {
  useAuthGuard(["admin"]);
  const [data, setData] = useState<ProxyPoolData | null>(null);
  const [loading, setLoading] = useState(true);
  const [newUrl, setNewUrl] = useState("");
  const [newWeight, setNewWeight] = useState("1");
  const [egressIp, setEgressIp] = useState<EgressIpResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [strategyValue, setStrategyValue] = useState("round_robin");

  const load = useCallback(async () => {
    try {
      const result = await fetchProxyPool();
      setData(result);
      setStrategyValue(result.stats.strategy);
    } catch (e) {
      // 后端挂掉时给出反馈，避免永久骨架屏 + 静默轮询 rejection
      toast.error(e instanceof Error ? e.message : "加载代理池失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), 10000);
    return () => clearInterval(timer);
  }, [load]);

  const handleAdd = async () => {
    if (!newUrl.trim()) {
      toast.error("请输入代理地址");
      return;
    }
    try {
      await addProxy(newUrl.trim(), Math.max(1, parseInt(newWeight) || 1));
      toast.success("代理已添加");
      setNewUrl("");
      setNewWeight("1");
      await load();
    } catch (e) {
      toast.error("添加失败: " + String(e));
    }
  };

  const handleRemove = async (url: string) => {
    try {
      await removeProxy(url);
      toast.success("已移除");
      await load();
    } catch (e) {
      toast.error("移除失败: " + String(e));
    }
  };

  const handleStrategyChange = async (value: string) => {
    setStrategyValue(value);
    try {
      await setStrategy(value);
      toast.success("调度策略已更新");
    } catch (e) {
      toast.error("设置失败: " + String(e));
    }
  };

  const handleProbe = async () => {
    setProbing(true);
    try {
      const result = await probeEgressIp();
      setEgressIp(result);
      if (result.ok) {
        toast.success(`出口 IP: ${result.ip}`);
      } else {
        toast.error("探测失败: " + (result.error || "unknown"));
      }
    } finally {
      setProbing(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-40 animate-pulse rounded-lg bg-stone-200 dark:bg-stone-700" />
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
          ))}
        </div>
        <div className="h-16 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
        <div className="h-64 animate-pulse rounded-xl bg-stone-100 dark:bg-stone-800" />
      </div>
    );
  }

  const stats = data?.stats;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-stone-900">IP 池管理</h1>
          <p className="text-sm text-stone-500">代理增删改查 · 权重调度 · 健康检查 · 出口 IP 探测</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-1 h-4 w-4" />
          刷新
        </Button>
      </div>

      {/* 出口 IP + 概览 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card className="rounded-xl border-stone-200 bg-white">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-stone-500">
              <Globe className="h-4 w-4" />
              <span className="text-xs font-medium">出口 IP</span>
            </div>
            <p className="mt-2 text-lg font-semibold text-stone-900">
              {egressIp?.ok ? egressIp.ip : "未探测"}
            </p>
            <Button size="sm" variant="outline" className="mt-2 h-7 text-xs" onClick={handleProbe} disabled={probing}>
              {probing ? "探测中..." : "探测出口 IP"}
            </Button>
          </CardContent>
        </Card>
        <Card className="rounded-xl border-stone-200 bg-white">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-stone-500">
              <Wifi className="h-4 w-4" />
              <span className="text-xs font-medium">代理总数</span>
            </div>
            <p className="mt-2 text-2xl font-semibold text-stone-900">{stats?.total ?? 0}</p>
            <p className="mt-1 text-xs text-stone-400">健康 {stats?.healthy ?? 0} · 隔离 {stats?.isolated ?? 0}</p>
          </CardContent>
        </Card>
        <Card className="rounded-xl border-stone-200 bg-white">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-stone-500">
              <Activity className="h-4 w-4" />
              <span className="text-xs font-medium">调度策略</span>
            </div>
            <Select value={strategyValue} onValueChange={handleStrategyChange}>
              <SelectTrigger className="mt-2 h-9 rounded-lg">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="round_robin">轮询</SelectItem>
                <SelectItem value="weighted">加权</SelectItem>
                <SelectItem value="least_connections">最少连接</SelectItem>
              </SelectContent>
            </Select>
          </CardContent>
        </Card>
        <Card className="rounded-xl border-stone-200 bg-white">
          <CardContent className="p-4">
            <div className="text-xs font-medium text-stone-500">不健康</div>
            <p className="mt-2 text-2xl font-semibold text-rose-600">{stats?.unhealthy ?? 0}</p>
            <p className="mt-1 text-xs text-stone-400">连续失败自动隔离</p>
          </CardContent>
        </Card>
      </div>

      {/* 添加代理 */}
      <Card className="rounded-xl border-stone-200 bg-white">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">添加代理</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="min-w-[280px] flex-1 space-y-1">
            <label className="text-xs text-stone-500">代理地址 (http://, socks5://, socks5h://)</label>
            <Input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="http://user:pass@host:port 或 socks5h://host:port"
              className="h-10 rounded-xl"
            />
          </div>
          <div className="w-28 space-y-1">
            <label className="text-xs text-stone-500">权重</label>
            <Input value={newWeight} onChange={(e) => setNewWeight(e.target.value)} className="h-10 rounded-xl" />
          </div>
          <Button onClick={handleAdd} className="h-10 rounded-xl bg-stone-950 text-white hover:bg-stone-800">
            <Plus className="mr-1 h-4 w-4" />
            添加
          </Button>
        </CardContent>
      </Card>

      {/* 代理列表 */}
      <Card className="rounded-xl border-stone-200 bg-white">
        <CardHeader className="pb-2">
          <CardTitle className="text-base">代理列表</CardTitle>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>代理地址</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">权重</TableHead>
                <TableHead className="text-right">延迟</TableHead>
                <TableHead className="text-right">成功率</TableHead>
                <TableHead className="text-right">请求</TableHead>
                <TableHead className="text-right">失败</TableHead>
                <TableHead className="text-right">最近检查</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {!data || data.proxies.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="py-8 text-center text-stone-400">
                    暂无代理，请在上方添加
                  </TableCell>
                </TableRow>
              ) : (
                data.proxies.map((proxy) => (
                  <TableRow key={proxy.url}>
                    <TableCell className="max-w-[260px] truncate font-mono text-xs">{proxy.url}</TableCell>
                    <TableCell>
                      {proxy.status === "healthy" ? (
                        <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300">健康</Badge>
                      ) : proxy.status === "isolated" ? (
                        <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">已隔离</Badge>
                      ) : (
                        <Badge className="bg-rose-100 text-rose-800 dark:bg-rose-950/40 dark:text-rose-300">不健康</Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-right">{proxy.weight}</TableCell>
                    <TableCell className="text-right">{proxy.latency_ms > 0 ? `${proxy.latency_ms.toFixed(0)}ms` : "-"}</TableCell>
                    <TableCell className="text-right">{(proxy.success_rate * 100).toFixed(0)}%</TableCell>
                    <TableCell className="text-right">{proxy.total_requests}</TableCell>
                    <TableCell className="text-right text-rose-600">{proxy.failed_requests}</TableCell>
                    <TableCell className="text-right text-xs text-stone-400">{formatTime(proxy.last_check)}</TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => void handleRemove(proxy.url)}>
                        <Trash2 className="h-4 w-4 text-rose-500" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

export default function ProxyPoolPage() {
  return <ProxyPoolContent />;
}
