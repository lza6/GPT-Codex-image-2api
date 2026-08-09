"use client";

import { Activity, AlertCircle, Database, Globe, LoaderCircle, RefreshCw, Save, Spline, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  fetchKookeeyConfig,
  fetchKookeeyIpUsage,
  fetchKookeeyTraffic,
  probeKookeeyIps,
  updateKookeeyConfig,
  extractKookeey,
  type KookeeyConfig,
  type KookeeyIpUsageBoard,
  type KookeeyTraffic,
  type KookeeyExtractResult,
} from "@/lib/api";

function fmtMb(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return "—";
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb} MB`;
}

export function KookeeyCard() {
  const [config, setConfig] = useState<KookeeyConfig | null>(null);
  const [traffic, setTraffic] = useState<KookeeyTraffic | null>(null);
  const [board, setBoard] = useState<KookeeyIpUsageBoard | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isProbing, setIsProbing] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractResult, setExtractResult] = useState<KookeeyExtractResult | null>(null);
  // 表单字段
  const [developerToken, setDeveloperToken] = useState("");
  const [accessId, setAccessId] = useState("");
  const [extractUrl, setExtractUrl] = useState("");

  const loadAll = useCallback(async () => {
    try {
      const [cfg, trf, brd] = await Promise.allSettled([
        fetchKookeeyConfig(),
        fetchKookeeyTraffic(),
        fetchKookeeyIpUsage(),
      ]);
      const errors: string[] = [];
      if (cfg.status === "fulfilled") {
        setConfig(cfg.value);
        setDeveloperToken(cfg.value.developer_token ?? "");
        setAccessId(cfg.value.access_id ?? "");
        setExtractUrl(cfg.value.extract_url ?? "");
      } else {
        errors.push(cfg.reason?.message ?? "config");
      }
      if (trf.status === "fulfilled") setTraffic(trf.value);
      else errors.push(trf.reason?.message ?? "traffic");
      if (brd.status === "fulfilled") setBoard(brd.value);
      else errors.push(brd.reason?.message ?? "board");
      if (errors.length === 3) {
        setLoadError(errors.find(Boolean) ?? "加载 kookeey 数据失败");
      } else {
        setLoadError(null);
      }
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const data = await updateKookeeyConfig({
        enabled: config?.enabled ?? true,
        developer_token: developerToken.trim(),
        access_id: accessId.trim(),
        extract_url: extractUrl.trim(),
        default_country: config?.default_country ?? "US",
        default_count: config?.default_count ?? 10,
      });
      setConfig(data.config);
      toast.success("kookeey 配置已保存");
      void loadAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  const handleProbe = async () => {
    setIsProbing(true);
    try {
      const r = await probeKookeeyIps();
      toast.success(`探测完成：${r.ok}/${r.probed} 个号出口 IP 已刷新（${r.duration_s}s）`);
      void loadAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "探测失败");
    } finally {
      setIsProbing(false);
    }
  };

  const handleExtract = async () => {
    setIsExtracting(true);
    setExtractResult(null);
    try {
      const r = await extractKookeey();
      setExtractResult(r);
      toast.success(`提取完成：提取 ${r.extracted} 条，入池 ${r.imported} 条，去重 ${r.deduped} 条`);
      void loadAll();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "提取失败");
    } finally {
      setIsExtracting(false);
    }
  };

  if (isLoading) {
    return (
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  if (loadError) {
    return (
      <Card className="rounded-2xl border-red-200 bg-red-50/80 shadow-sm">
        <CardContent className="flex flex-col items-center gap-3 p-6 text-center">
          <AlertCircle className="size-8 text-red-400" />
          <div>
            <p className="text-sm font-medium text-red-700">加载 kookeey 数据失败</p>
            <p className="mt-1 text-xs text-red-500">{loadError}</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void loadAll()}
            className="h-8 rounded-lg border-red-200 bg-white text-red-600 hover:bg-red-50"
          >
            <RefreshCw className="size-3.5" />
            重试
          </Button>
        </CardContent>
      </Card>
    );
  }

  const pkg = traffic?.package;
  const needConfig = traffic?.need_config === true;

  return (
    <div className="space-y-4">
      {/* 开发者凭证设置 */}
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="space-y-4 p-5">
          <div className="flex items-center gap-2">
            <Globe className="size-4 text-stone-500" />
            <h3 className="text-sm font-semibold text-stone-800">kookeey 开发者凭证</h3>
          </div>
          <p className="text-xs text-stone-500">
            填开发者 token + access ID 后，可查流量余额/账户/明细（官方开发者 API）。
            在 kookeey 后台「账户中心」获取。
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-stone-600">Access ID（developer id）</label>
              <Input
                value={accessId}
                onChange={(e) => setAccessId(e.target.value)}
                placeholder="如 1023701"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-stone-600">开发者 Token（加密密钥）</label>
              <Input
                type="password"
                value={developerToken}
                onChange={(e) => setDeveloperToken(e.target.value)}
                placeholder="账户中心获取的 encryption key"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-stone-600">提取链接（当前已配置，用于拉取 IP 入池）</label>
            <div className="flex items-center gap-2">
              <Input
                value={extractUrl}
                onChange={(e) => setExtractUrl(e.target.value)}
                placeholder="https://kookeey.com/...?accessid=..&sign=..&n=10"
                className="h-10 flex-1 rounded-xl border-stone-200 bg-white font-mono text-xs"
              />
              <Button
                onClick={() => void handleExtract()}
                disabled={isExtracting || !extractUrl.trim()}
                className="h-10 shrink-0 rounded-xl bg-stone-900 px-4 text-white hover:bg-stone-800 disabled:opacity-50"
              >
                {isExtracting ? <LoaderCircle className="size-4 animate-spin" /> : <Spline className="size-4" />}
                提取到代理池
              </Button>
            </div>
            {extractResult && (
              <p className="text-xs text-emerald-600">
                提取 {extractResult.extracted} 条 · 入池 {extractResult.imported} 条 · 去重 {extractResult.deduped} 条
                {extractResult.skipped > 0 && ` · 跳过 ${extractResult.skipped} 条`}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button
              onClick={() => void handleSave()}
              disabled={isSaving}
              className="h-10 rounded-xl bg-stone-900 px-5 text-white hover:bg-stone-800"
            >
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
              保存
            </Button>
            <span className="text-xs text-stone-500">
              当前 access_id：{config?.access_id || "未配置"}
              {config?.developer_token ? " · token 已配置" : " · token 未配置"}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* 流量卡片 */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-stone-500">
              <Database className="size-3.5" /> 剩余流量
            </div>
            <div className="mt-2 text-2xl font-semibold text-stone-900">
              {needConfig ? "未配置" : fmtMb(traffic?.balance_mb)}
            </div>
            {pkg?.traffic_left_gb != null && (
              <div className="mt-1 text-xs text-stone-400">住宅包剩 {pkg.traffic_left_gb} GB</div>
            )}
          </CardContent>
        </Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-stone-500">
              <Activity className="size-3.5" /> 今日已用
            </div>
            <div className="mt-2 text-2xl font-semibold text-stone-900">
              {needConfig ? "—" : fmtMb(traffic?.today_use_mb)}
            </div>
          </CardContent>
        </Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-stone-500">
              <TrendingUp className="size-3.5" /> 近30天已用
            </div>
            <div className="mt-2 text-2xl font-semibold text-stone-900">
              {needConfig ? "—" : fmtMb(traffic?.month_use_mb)}
            </div>
            {pkg?.traffic_total_gb != null && (
              <div className="mt-1 text-xs text-stone-400">住宅包共 {pkg.traffic_total_gb} GB</div>
            )}
          </CardContent>
        </Card>
        <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 text-xs font-medium text-stone-500">
              <Globe className="size-3.5" /> 已使用 IP 数
            </div>
            <div className="mt-2 text-2xl font-semibold text-stone-900">{board?.used_ip_count ?? 0}</div>
            <div className="mt-1 text-xs text-stone-400">累计取出 {board?.total_extracted ?? 0} 条</div>
          </CardContent>
        </Card>
      </div>
      {needConfig && (
        <p className="text-xs text-amber-600">
          流量数据需在上方填开发者 token + access ID 后显示（/tinfo /package 官方接口）。
        </p>
      )}

      {/* 每 IP 使用排行榜 */}
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="p-5">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-stone-800">每账号 / IP 使用排行</h3>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void handleProbe()}
              disabled={isProbing}
              className="h-8 rounded-lg border-stone-200 bg-white text-stone-700"
            >
              {isProbing ? <LoaderCircle className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
              立即探测出口 IP
            </Button>
          </div>
          <p className="mb-3 text-xs text-stone-500">
            后台每 2 小时自动批量探测一次各账号出口 IP；点按钮立即刷新。请求数 = 该账号粘性 IP 的调用次数。流量 = 估算值（kookeey API 不提供单 IP 真实流量）。
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-stone-200 text-stone-500">
                  <th className="py-2 pr-3 font-medium">#</th>
                  <th className="py-2 pr-3 font-medium">账号</th>
                  <th className="py-2 pr-3 font-medium">出口 IP</th>
                  <th className="py-2 pr-3 font-medium">调用次数</th>
                  <th className="py-2 pr-3 font-medium">失败</th>
                  <th className="py-2 pr-3 font-medium">流量</th>
                  <th className="py-2 font-medium">最近使用</th>
                </tr>
              </thead>
              <tbody>
                {(board?.leaderboard ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-stone-400">
                      暂无使用记录（有调用后自动统计）
                    </td>
                  </tr>
                ) : (
                  (board?.leaderboard ?? []).map((row, i) => (
                    <tr key={row.session} className="border-b border-stone-100 last:border-0">
                      <td className="py-2 pr-3 text-stone-400">{i + 1}</td>
                      <td className="max-w-[180px] truncate py-2 pr-3 font-medium text-stone-700">{row.email}</td>
                      <td className="py-2 pr-3 font-mono text-stone-600">{row.last_ip || "未探测"}</td>
                      <td className="py-2 pr-3 text-stone-800">{row.requests}</td>
                      <td className="py-2 pr-3 text-stone-500">{row.fail}</td>
                      <td className="py-2 pr-3 text-stone-600">{row.estimated_mb ? `${row.estimated_mb} MB` : "—"}</td>
                      <td className="py-2 text-stone-400">{row.last_used_at || "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
