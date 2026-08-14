"use client";

import { useEffect, useState } from "react";
import { Fingerprint, Globe, LoaderCircle, RefreshCcw, UserPlus, Zap } from "lucide-react";
import { toast } from "sonner";
import { toastError } from "@/lib/toast-helper";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { fetchFomimageRegistrationStatus, triggerFomimageRegistration, type FomimageRegistrationStatus } from "@/lib/api";

/** v2.36.0：fomimage 自动注册管理卡片（批量注册 + 号池健康 + 指纹/IP/邮箱源策略 + 状态）。 */
export function FomimageRegistrationCard() {
  const [status, setStatus] = useState<FomimageRegistrationStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRegistering, setIsRegistering] = useState(false);
  const [registerCount, setRegisterCount] = useState<number>(1);

  const load = async () => {
    try {
      const data = await fetchFomimageRegistrationStatus();
      setStatus(data);
      if (registerCount <= 0) {
        setRegisterCount(data?.config?.register_batch ?? 1);
      }
    } catch (error) {
      toastError(error, "加载 fomimage 注册状态失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRegister = async () => {
    if (isRegistering) return;
    const n = Math.max(1, Math.min(500, Number(registerCount) || 1));
    setIsRegistering(true);
    try {
      const result = await triggerFomimageRegistration(n);
      if (result?.ok === false) {
        toast.error(result.error ?? "fomimage 注册未执行");
      } else {
        toast.success(`注册完成：成功 ${result?.success ?? 0}，失败 ${result?.failed ?? 0}，入池 ${result?.pool_added ?? 0}`);
      }
      await load();
    } catch (error) {
      toastError(error, "fomimage 注册触发失败");
    } finally {
      setIsRegistering(false);
    }
  };

  const pool = status?.fomimage_pool;
  const stats = status?.stats;
  const lastRun = stats?.last_run_result;
  const cfg = status?.config;
  const emailSources = (cfg?.email_sources ?? ["temp-mail"]).join(" + ");
  const workers = cfg?.register_workers ?? 1;
  const proxyMode = cfg?.proxy_mode ?? "auto";

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex items-center gap-2">
          <UserPlus className="size-4 text-stone-500" />
          <h3 className="text-base font-semibold text-stone-900">fomimage 自动注册</h3>
          <Badge variant={status?.enabled ? "success" : "secondary"} className="rounded-md">
            {status?.enabled ? "已启用" : "未启用"}
          </Badge>
        </div>
        <p className="text-xs leading-5 text-stone-500">
          一号一 IP + 一号一指纹批量注册 fomimage 账号，注册送 50 积分，号池按积分用完即弃，低于阈值自动补号。
          在 <code className="rounded bg-stone-100 px-1">config.json → registration.fomimage.enabled=true</code> 启用。
        </p>

        {isLoading ? (
          <div className="flex items-center justify-center py-6">
            <LoaderCircle className="size-5 animate-spin text-stone-400" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* 号池健康 */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-xl bg-stone-50 px-3 py-2.5">
                <div className="text-[11px] font-medium text-stone-500">可用号数</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums text-stone-900">{pool?.available ?? 0}</div>
              </div>
              <div className="rounded-xl bg-stone-50 px-3 py-2.5">
                <div className="text-[11px] font-medium text-stone-500">补号阈值</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums text-stone-900">{pool?.min_accounts ?? 0}</div>
              </div>
              <div className="rounded-xl bg-stone-50 px-3 py-2.5">
                <div className="text-[11px] font-medium text-stone-500">累计注册</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums text-stone-900">
                  {((stats?.total_registered ?? 0) + (stats?.total_failed ?? 0)) || 0}
                </div>
              </div>
              <div className="rounded-xl bg-stone-50 px-3 py-2.5">
                <div className="text-[11px] font-medium text-stone-500">状态</div>
                <div className="mt-1 text-sm font-medium">
                  {pool?.need_replenish ? (
                    <span className="text-amber-600">需要补号</span>
                  ) : status?.enabled ? (
                    <span className="text-emerald-600">健康</span>
                  ) : (
                    <span className="text-stone-400">未启用</span>
                  )}
                </div>
              </div>
            </div>

            {/* 注册策略（指纹 / IP / 邮箱源） */}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <div className="flex items-center gap-2 rounded-xl border border-stone-200/70 bg-white px-3 py-2">
                <Fingerprint className="size-3.5 shrink-0 text-stone-400" />
                <div className="text-[11px] text-stone-600">
                  指纹策略
                  <span className="block font-medium text-stone-800">一号一指纹（随机 impersonate）</span>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-stone-200/70 bg-white px-3 py-2">
                <Globe className="size-3.5 shrink-0 text-stone-400" />
                <div className="text-[11px] text-stone-600">
                  IP 策略
                  <span className="block font-medium text-stone-800">
                    {proxyMode === "off" ? "直连" : "一号一 IP（代理池粘性）"}
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-stone-200/70 bg-white px-3 py-2">
                <Zap className="size-3.5 shrink-0 text-stone-400" />
                <div className="text-[11px] text-stone-600">
                  邮箱源 / 并发
                  <span className="block font-medium text-stone-800">
                    {emailSources} × {workers} 路
                  </span>
                </div>
              </div>
            </div>

            {/* 最近一次执行 */}
            {lastRun && (
              <div className="rounded-xl border border-stone-200/70 bg-white px-3 py-2.5 text-xs text-stone-600">
                最近一次：成功 {lastRun.success} · 失败 {lastRun.failed} · 入池 {lastRun.pool_added}
                <span className="ml-2 text-stone-400">
                  累计 {stats?.total_registered ?? 0} 成功 / {stats?.total_failed ?? 0} 失败
                </span>
                <span className="ml-2 text-stone-400">池额 {cfg?.pool_quota ?? 50} 积分/号</span>
                {cfg?.luckmail_api_key_configured === false && (cfg?.email_sources ?? []).includes("luckmail") && (
                  <span className="ml-2 text-amber-600">luckmail 未配 key，邮箱源将跳过</span>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <Input
                type="number"
                min={1}
                max={500}
                value={registerCount}
                onChange={(e) => setRegisterCount(Number(e.target.value) || 1)}
                className="h-9 w-24 rounded-xl"
                aria-label="注册数量"
              />
              <Button variant="default" size="sm" onClick={handleRegister} disabled={isRegistering}>
                {isRegistering ? (
                  <LoaderCircle className="mr-1.5 size-4 animate-spin" />
                ) : (
                  <Zap className="mr-1.5 size-4" />
                )}
                开始批量注册
              </Button>
              <Button variant="outline" size="sm" onClick={() => void load()}>
                <RefreshCcw className="mr-1.5 size-3.5" />
                刷新状态
              </Button>
              {status?.watcher_running && (
                <span className="text-[11px] text-stone-400">自动补号线程运行中</span>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
