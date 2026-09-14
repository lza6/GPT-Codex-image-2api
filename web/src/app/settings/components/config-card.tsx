"use client";

import { Cloud, LoaderCircle, PlugZap, RefreshCw, Save } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { toastError, toastSuccess } from "@/lib/toast-helper";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { ImageStorageMode } from "@/lib/api";
import { sendTestAlert, testProxy, type ProxyTestResult } from "@/lib/api";

import { useSettingsStore } from "../store";

export function ConfigCard() {
  const [isTestingProxy, setIsTestingProxy] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState<ProxyTestResult | null>(null);
  const [isTestingAlert, setIsTestingAlert] = useState(false);
  const [alertTestResults, setAlertTestResults] = useState<{ channel: string; ok: boolean; error: string }[]>([]);
  const logLevelOptions = ["debug", "info", "warning", "error"];
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setRefreshAccountIntervalMinute = useSettingsStore((state) => state.setRefreshAccountIntervalMinute);
  const setImageRetentionDays = useSettingsStore((state) => state.setImageRetentionDays);
  const setImagePollTimeoutSecs = useSettingsStore((state) => state.setImagePollTimeoutSecs);
  const setImageAccountConcurrency = useSettingsStore((state) => state.setImageAccountConcurrency);
  const setImageSettleEnabled = useSettingsStore((state) => state.setImageSettleEnabled);
  const setImageRemoveConversationAfterResult = useSettingsStore((state) => state.setImageRemoveConversationAfterResult);
  const setImageRemoveConversationAlways = useSettingsStore((state) => state.setImageRemoveConversationAlways);
  const setImagePassthroughEnabled = useSettingsStore((state) => state.setImagePassthroughEnabled);
  const setImageSettleSecs = useSettingsStore((state) => state.setImageSettleSecs);
  const setImageTimeoutRetrySecs = useSettingsStore((state) => state.setImageTimeoutRetrySecs);
  const setAutoRemoveInvalidAccounts = useSettingsStore((state) => state.setAutoRemoveInvalidAccounts);
  const setAutoRemoveRateLimitedAccounts = useSettingsStore((state) => state.setAutoRemoveRateLimitedAccounts);
  const setAutoReloginAfterRefresh = useSettingsStore((state) => state.setAutoReloginAfterRefresh);
  const setSchedulerMode = useSettingsStore((state) => state.setSchedulerMode);
const setSchedulerAdaptiveEnabled = useSettingsStore((state) => state.setSchedulerAdaptiveEnabled);
const setSchedulerAdaptiveIntervalSeconds = useSettingsStore((state) => state.setSchedulerAdaptiveIntervalSeconds);
  const setProactiveProbeEnabled = useSettingsStore((state) => state.setProactiveProbeEnabled);
  const setProactiveProbeIntervalMinute = useSettingsStore((state) => state.setProactiveProbeIntervalMinute);
  const setRateLimitRpm = useSettingsStore((state) => state.setRateLimitRpm);
  const setRateLimitPerIpRpm = useSettingsStore((state) => state.setRateLimitPerIpRpm);
  const setWorkers = useSettingsStore((state) => state.setWorkers);
  const setSqliteWalMode = useSettingsStore((state) => state.setSqliteWalMode);
  const setStorageAsyncEnabled = useSettingsStore((state) => state.setStorageAsyncEnabled);
  const setSqliteBusyTimeoutMs = useSettingsStore((state) => state.setSqliteBusyTimeoutMs);
  const setProgressTtlSeconds = useSettingsStore((state) => state.setProgressTtlSeconds);
  const setSsrfAllowPrivateIps = useSettingsStore((state) => state.setSsrfAllowPrivateIps);
  const setTrustedProxiesText = useSettingsStore((state) => state.setTrustedProxiesText);
  const setAlertWebhookUrl = useSettingsStore((state) => state.setAlertWebhookUrl);
  const setAlertWebhookTimeout = useSettingsStore((state) => state.setAlertWebhookTimeout);
  const toggleAlertEvent = useSettingsStore((state) => state.toggleAlertEvent);
  const setAlertChannelField = useSettingsStore((state) => state.setAlertChannelField);
  const setLogLevel = useSettingsStore((state) => state.setLogLevel);
  const setProxy = useSettingsStore((state) => state.setProxy);
  const setBaseUrl = useSettingsStore((state) => state.setBaseUrl);
  const setGlobalSystemPrompt = useSettingsStore((state) => state.setGlobalSystemPrompt);
  const setDefaultUpstreamModelName = useSettingsStore((state) => state.setDefaultUpstreamModelName);
  const setDefaultThinkingEffort = useSettingsStore((state) => state.setDefaultThinkingEffort);
  const setSensitiveWordsText = useSettingsStore((state) => state.setSensitiveWordsText);
  const setAIReviewField = useSettingsStore((state) => state.setAIReviewField);
  const setImageStorageField = useSettingsStore((state) => state.setImageStorageField);
  const testImageStorage = useSettingsStore((state) => state.testImageStorage);
  const syncImagesToWebDAV = useSettingsStore((state) => state.syncImagesToWebDAV);
  const isTestingImageStorage = useSettingsStore((state) => state.isTestingImageStorage);
  const isSyncingImageStorage = useSettingsStore((state) => state.isSyncingImageStorage);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const storageMode: ImageStorageMode = config?.image_storage?.enabled
    ? (config.image_storage.mode as ImageStorageMode)
    : "local";
  const alertChannel = (name: string) => config?.alert_channels?.[name] || {};
  const isWebdavMode = storageMode === "webdav" || storageMode === "both";
  const isR2Mode = storageMode === "r2" || storageMode === "r2_local";
  const STORAGE_MODE_LABEL: Record<ImageStorageMode, string> = {
    local: "仅本机",
    webdav: "仅 WebDAV",
    both: "本机 + WebDAV",
    r2: "仅 R2",
    r2_local: "本机 + R2",
  };

  const handleTestProxy = async () => {
    const candidate = String(config?.proxy || "").trim();
    if (!candidate) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTestingProxy(true);
    setProxyTestResult(null);
    try {
      const data = await testProxy(candidate);
      setProxyTestResult(data.result);
      if (data.result.ok) {
        toast.success(`代理可用（${data.result.latency_ms} ms，HTTP ${data.result.status}）`);
      } else {
        toast.error(`代理不可用：${data.result.error ?? "未知错误"}`);
      }
    } catch (error) {
      toastError(error, "测试代理失败");
    } finally {
      setIsTestingProxy(false);
    }
  };

  // 告警通道状态判定（G1：接线引导）——通道启用且关键字段齐全视为"可发送"
  const alertChannelReady = (name: string): boolean => {
    const cfg = config?.alert_channels?.[name] || {};
    const type = String(cfg.type || name);
    if (!cfg.enabled) {
      return false;
    }
    if (type === "telegram") {
      return Boolean(String(cfg.bot_token || "").trim()) && Boolean(String(cfg.chat_id || "").trim());
    }
    if (type === "email") {
      return (
        Boolean(String(cfg.smtp_host || "").trim()) &&
        Boolean(String(cfg.from_addr || "").trim()) &&
        Array.isArray(cfg.to_addrs) &&
        cfg.to_addrs.length > 0
      );
    }
    return Boolean(String(cfg.webhook_url || "").trim());
  };

  const anyAlertChannelReady =
    alertChannelReady("telegram_ops") ||
    alertChannelReady("wecom_ops") ||
    alertChannelReady("dingtalk_ops") ||
    alertChannelReady("email_ops") ||
    Boolean(String(config?.alert_webhook_url || "").trim());

  const handleSendTestAlert = async () => {
    if (!anyAlertChannelReady) {
      toast.error("请先配置至少一个告警通道");
      return;
    }
    setIsTestingAlert(true);
    setAlertTestResults([]);
    try {
      const data = await sendTestAlert();
      if (data.reason === "no_channel") {
        toast.error("请先配置至少一个告警通道");
        return;
      }
      setAlertTestResults(data.results || []);
      const okCount = (data.results || []).filter((item) => item.ok).length;
      if (okCount > 0) {
        toast.success(`测试告警已发送：${okCount} 个通道成功`);
      } else {
        toast.error("测试告警发送失败：所有通道均未成功");
      }
    } catch (error) {
      toastError(error, "发送测试告警失败");
    } finally {
      setIsTestingAlert(false);
    }
  };

  if (isLoadingConfig) {
    return (
      <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-4 p-6">
        <div className="rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 text-sm leading-6 text-stone-600">
          管理员登录密钥继续从部署配置读取，不再在此页面展示；如需分发给其他人，请在下方创建普通用户密钥。
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-2">
            <label className="text-sm text-stone-700">账号刷新间隔</label>
            <Input
              value={String(config?.refresh_account_interval_minute || "")}
              onChange={(event) => setRefreshAccountIntervalMinute(event.target.value)}
              placeholder="分钟"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单位分钟，控制账号自动刷新频率。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">全局代理</label>
            <Input
              value={String(config?.proxy || "")}
              onChange={(event) => {
                setProxy(event.target.value);
                setProxyTestResult(null);
              }}
              placeholder="http://127.0.0.1:7890"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs leading-5 text-stone-500">
              留空表示不使用代理。支持协议://账号:密码@主机:端口，也可直接粘贴代理商的 主机:端口:账号:密码；示例 http://user:pass@127.0.0.1:7890、127.0.0.1:7890:user:pass。账号密码含 @/: 等特殊字符时需 URL 编码。
            </p>
            {proxyTestResult ? (
              <div
                className={`rounded-xl border px-3 py-2 text-xs leading-6 ${
                  proxyTestResult.ok
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-rose-200 bg-rose-50 text-rose-800"
                }`}
              >
                {proxyTestResult.ok
                  ? `代理可用：HTTP ${proxyTestResult.status}，用时 ${proxyTestResult.latency_ms} ms`
                  : `代理不可用：${proxyTestResult.error ?? "未知错误"}（用时 ${proxyTestResult.latency_ms} ms）`}
              </div>
            ) : null}
            <div className="flex justify-end">
              <Button
                type="button"
                variant="outline"
                className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                onClick={() => void handleTestProxy()}
                disabled={isTestingProxy}
              >
                {isTestingProxy ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                测试代理
              </Button>
            </div>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">图片访问地址</label>
            <Input
              value={String(config?.base_url || "")}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://example.com"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">用于生成图片结果的访问前缀地址。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">默认请求上游模型名称</label>
            <Input
              value={String(config?.default_upstream_model_name || "")}
              onChange={(event) => setDefaultUpstreamModelName(event.target.value)}
              placeholder="gpt-5-5"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">gpt-image-2 发起图片请求时使用的上游模型名称，默认 gpt-5-5。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">默认思考强度</label>
            <Select
              value={String(config?.default_thinking_effort || "auto")}
              onValueChange={(value) => setDefaultThinkingEffort(value as "auto" | "standard" | "extended" | "max")}
            >
              <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">Auto（不传递）</SelectItem>
                <SelectItem value="standard">Standard</SelectItem>
                <SelectItem value="extended">Extended</SelectItem>
                <SelectItem value="max">Max</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-stone-500">模型名称以 -standard、-extended 或 -max 结尾时，模型后缀优先。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">图片自动清理</label>
            <Input
              value={String(config?.image_retention_days || "")}
              onChange={(event) => setImageRetentionDays(event.target.value)}
              placeholder="30"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">自动删除多少天前的本地图片。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">图片轮询超时</label>
            <Input
              value={String(config?.image_poll_timeout_secs || "")}
              onChange={(event) => setImagePollTimeoutSecs(event.target.value)}
              placeholder="120"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单位秒，等待上游图片结果的最长时间。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">单账号图片并发</label>
            <Input
              value={String(config?.image_account_concurrency || "")}
              onChange={(event) => setImageAccountConcurrency(event.target.value)}
              placeholder="1"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">限制每个账号同时处理的图片请求数量，默认 3。</p>
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
              <Checkbox
                checked={Boolean(config?.auto_remove_invalid_accounts)}
                onCheckedChange={(checked) => setAutoRemoveInvalidAccounts(Boolean(checked))}
              />
              自动移除异常账号
            </label>
            <p className="text-xs text-stone-500">刷新时检测并移除</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">调度模式</label>
            <Select value={config?.scheduler_mode || "round_robin"} onValueChange={(v) => setSchedulerMode(v as "round_robin" | "remaining_quota" | "weighted_random" | "least_load" | "least_used" | "predictive" | "affinity")}>
              <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="round_robin">轮询（round_robin）</SelectItem>
                <SelectItem value="remaining_quota">按剩余配额（remaining_quota）</SelectItem>
                <SelectItem value="weighted_random">加权随机（weighted_random）</SelectItem>
                <SelectItem value="least_load">最少并发（least_load）</SelectItem>
                <SelectItem value="least_used">雨露均沾（least_used）</SelectItem>
                <SelectItem value="predictive">预测配额（predictive）</SelectItem>
                <SelectItem value="affinity">模型亲和（affinity）</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-stone-500">账号调度策略：轮询 / 按剩余配额 / 加权随机（摊平磨损）/ 最少并发 / 雨露均沾（选最久未用，避免集中突刺单号）/ 预测配额 / 模型亲和。</p>
          </div>
          <div className="space-y-2">
            <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
              <Checkbox
                checked={Boolean(config?.scheduler_adaptive_enabled)}
                onCheckedChange={(checked) => setSchedulerAdaptiveEnabled(Boolean(checked))}
              />
              自适应调度器
            </label>
            <p className="text-xs text-stone-500">基于运行指标（并发/成功率/模型多样性）自动切换最优调度模式，默认关闭。</p>
          </div>
          {config?.scheduler_adaptive_enabled && (
            <div className="space-y-2">
              <label className="text-sm text-stone-700">自适应检查间隔（秒）</label>
              <Input
                value={String(config?.scheduler_adaptive_interval_seconds ?? 30)}
                onChange={(event) => setSchedulerAdaptiveIntervalSeconds(event.target.value)}
                placeholder="30"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">收集指标并判断是否切换模式的间隔，最小 5 秒。</p>
            </div>
          )}
          <div className="space-y-2">
            <label className="text-sm text-stone-700">全局限流 (RPM)</label>
            <Input
              value={String(config?.rate_limit_rpm ?? "")}
              onChange={(event) => setRateLimitRpm(event.target.value)}
              placeholder="0"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">全局限流，每分钟请求数上限。0 = 不限流。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">单 IP 限流 (RPM)</label>
            <Input
              value={String(config?.rate_limit_per_ip_rpm ?? "")}
              onChange={(event) => setRateLimitPerIpRpm(event.target.value)}
              placeholder="0"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单 IP 每分钟请求数上限。0 = 不限流。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">Worker 进程数</label>
            <Input
              value={String(config?.workers ?? "")}
              onChange={(event) => setWorkers(event.target.value)}
              placeholder="1"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">多 Worker 并发处理请求，利用多核 CPU。建议设为 CPU 核心数，重启后生效。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.sqlite_wal_mode !== false)}
                onCheckedChange={(checked) => setSqliteWalMode(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">SQLite WAL 模式</span>
            </div>
            <p className="text-xs text-stone-500">多 Worker 并发写安全，建议保持开启；仅 SQLite 存储后端生效，重启后生效。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.storage_async_enabled)}
                onCheckedChange={(checked) => setStorageAsyncEnabled(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">异步存储后端</span>
            </div>
            <p className="text-xs text-stone-500">启用后数据库操作使用 sqlalchemy.ext.asyncio 非阻塞异步驱动，提升并发吞吐。仅数据库存储后端生效，需安装 aiosqlite/asyncpg 驱动，重启后生效。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.proactive_probe_enabled)}
                onCheckedChange={(checked) => setProactiveProbeEnabled(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">低频主动探活</span>
            </div>
            <p className="text-xs text-stone-500">周期性刷新全部账号，把哑死账号（限流/失效）提前剔除，避免首次请求才踩坑；默认关闭以省配额。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">主动探活间隔（分钟）</label>
            <Input
              value={String(config?.proactive_probe_interval_minute ?? 30)}
              onChange={(event) => setProactiveProbeIntervalMinute(event.target.value)}
              placeholder="30"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">最小 5 分钟；过短会消耗上游配额。仅探活开启时生效，重启后生效。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">SQLite 锁等待超时</label>
            <Input
              value={String(config?.sqlite_busy_timeout_ms ?? "")}
              onChange={(event) => setSqliteBusyTimeoutMs(event.target.value)}
              placeholder="5000"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单位毫秒，写锁冲突时等待时长。0 = 立即报错。仅 SQLite 存储后端生效，重启后生效。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">进度记录保留时长</label>
            <Input
              value={String(config?.progress_ttl_seconds ?? "")}
              onChange={(event) => setProgressTtlSeconds(event.target.value)}
              placeholder="3600"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单位秒，批量刷新/重登进度在内存中的保留时长，超时自动清理防内存膨胀。重启后生效。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.ssrf_allow_private_ips)}
                onCheckedChange={(checked) => setSsrfAllowPrivateIps(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">允许抓取内网图片</span>
            </div>
            <p className="text-xs text-stone-500">默认拒绝抓取内网/回环地址的图片（SSRF 防护）。仅当图床在内网时才开启，开启有安全风险。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">可信反向代理 IP</label>
            <Textarea
              value={(config?.trusted_proxies || []).join("\n")}
              onChange={(event) => setTrustedProxiesText(event.target.value)}
              placeholder={"127.0.0.1\n::1"}
              className="min-h-20 rounded-xl border-stone-200 bg-white font-mono text-xs shadow-none"
            />
            <p className="text-xs text-stone-500">一行一个 IP。仅这些来源的 X-Forwarded-For 头被信任（防伪造绕过限流）。默认仅回环，反向代理部署时填代理 IP。</p>
          </div>
          <div className="space-y-4 rounded-xl border border-stone-200 bg-white px-4 py-3 md:col-span-2">
            <div>
              <label className="text-sm text-stone-700">告警 Webhook</label>
              <p className="mt-1 text-xs text-stone-500">熔断开启/备份失败/账号失效/配额耗尽时向该地址 POST JSON。留空 = 关闭告警。同一事件 5 分钟内只发一次。</p>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2 md:col-span-2">
                <label className="text-sm text-stone-700">Webhook URL</label>
                <Input
                  value={String(config?.alert_webhook_url || "")}
                  onChange={(event) => setAlertWebhookUrl(event.target.value)}
                  placeholder="https://hooks.slack.com/… 或 https://webhook.site/…"
                  className="h-10 rounded-xl border-stone-200 bg-white"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">超时（秒）</label>
                <Input
                  value={String(config?.alert_webhook_timeout ?? "")}
                  onChange={(event) => setAlertWebhookTimeout(event.target.value)}
                  placeholder="10"
                  className="h-10 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
              {[
                ["circuit_breaker_open", "熔断开启"],
                ["circuit_breaker_closed", "熔断恢复"],
                ["backup_failure", "备份失败"],
                ["account_invalid", "账号失效"],
                ["account_recovered", "账号恢复"],
                ["quota_exhausted", "配额耗尽"],
                ["quota_forecast_depletion", "配额将耗尽"],
              ].map(([eventKey, label]) => (
                <label key={eventKey} className="flex items-center gap-2 text-sm text-stone-700">
                  <Checkbox
                    checked={Boolean(config?.alert_events?.includes(eventKey))}
                    onCheckedChange={(checked) => toggleAlertEvent(eventKey, Boolean(checked))}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
          <div className="space-y-4 rounded-xl border border-stone-200 bg-white px-4 py-3 md:col-span-2">
            <div className="flex items-start justify-between gap-4">
              <div>
                <label className="text-sm text-stone-700">告警多通道</label>
                <p className="mt-1 text-xs text-stone-500">
                  可多通道并存，同一事件分发到所有启用通道；任一通道失败不影响其他通道。开关打开后需填写对应参数，参数不全的通道自动跳过。
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleSendTestAlert()}
                disabled={isTestingAlert}
                className="shrink-0"
              >
                {isTestingAlert ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                {isTestingAlert ? "发送中…" : "发送测试告警"}
              </Button>
            </div>
            {!anyAlertChannelReady && (
              <div className="space-y-2 rounded-lg border border-dashed border-stone-300 bg-stone-50 px-4 py-3">
                <p className="text-sm font-medium text-stone-700">尚未配置任何告警通道</p>
                <p className="text-xs text-stone-500">
                  账号封禁 / 配额耗尽 / 熔断时将无法通知你。最低配置：
                  <span className="font-mono">在「告警 Webhook」区块填任意普通机器人 webhook（企微 / 钉钉 / Slack 兼容），或启用下方任一通道并保存。</span>
                </p>
                <details className="text-xs text-stone-500">
                  <summary className="cursor-pointer text-stone-600">查看示例配置（Telegram）</summary>
                  <pre className="mt-2 overflow-x-auto rounded-lg bg-stone-100 p-3 font-mono text-[11px] leading-relaxed text-stone-700">{`{
  "alert_channels": {
    "telegram_ops": {
      "type": "telegram",
      "enabled": true,
      "bot_token": "123456:ABC-DEF...",
      "chat_id": "-1001234567890"
    }
  }
}`}</pre>
                  <p className="mt-2">
                    或用环境变量覆盖（重启生效）：<span className="font-mono">CHATGPT2API_ALERT_TELEGRAM_BOT_TOKEN</span> /{" "}
                    <span className="font-mono">CHATGPT2API_ALERT_TELEGRAM_CHAT_ID</span>
                  </p>
                </details>
              </div>
            )}
            {alertTestResults.length > 0 && (
              <div className="space-y-1 rounded-lg border border-stone-100 bg-stone-50 p-3">
                <p className="text-xs font-medium text-stone-600">测试结果（最近一次）</p>
                {alertTestResults.map((item) => (
                  <div key={item.channel} className="flex items-center gap-2 text-xs text-stone-600">
                    <span className={item.ok ? "size-2 rounded-full bg-emerald-500" : "size-2 rounded-full bg-red-400"} />
                    <span className="font-mono">{item.channel}</span>
                    <span className={item.ok ? "text-emerald-600" : "text-red-500"}>
                      {item.ok ? "发送成功" : `失败：${item.error ? String(item.error).slice(0, 80) : "未知错误"}`}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <div className="space-y-2 rounded-lg border border-stone-100 bg-stone-50 p-3">
              <label className="flex items-center gap-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(alertChannel("telegram_ops").enabled)}
                  onCheckedChange={(checked) => setAlertChannelField("telegram_ops", "enabled", Boolean(checked))}
                />
                Telegram Bot
                <span
                  className={`ml-auto inline-block h-2 w-2 rounded-full ${alertChannelReady("telegram_ops") ? "bg-emerald-500" : "bg-stone-300"}`}
                  title={alertChannelReady("telegram_ops") ? "已启用且参数齐全" : "未启用或参数不全"}
                />
              </label>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">Bot Token</label>
                  <Input
                    type="password"
                    value={String(alertChannel("telegram_ops").bot_token || "")}
                    onChange={(event) => setAlertChannelField("telegram_ops", "bot_token", event.target.value)}
                    placeholder="123456:ABC-DEF..."
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">Chat ID</label>
                  <Input
                    value={String(alertChannel("telegram_ops").chat_id || "")}
                    onChange={(event) => setAlertChannelField("telegram_ops", "chat_id", event.target.value)}
                    placeholder="@channel 或 -100xxxxxxxxxx"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
              </div>
            </div>
            <div className="space-y-2 rounded-lg border border-stone-100 bg-stone-50 p-3">
              <label className="flex items-center gap-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(alertChannel("wecom_ops").enabled)}
                  onCheckedChange={(checked) => setAlertChannelField("wecom_ops", "enabled", Boolean(checked))}
                />
                企业微信机器人
              </label>
              <div className="space-y-1">
                <label className="text-xs text-stone-500">Webhook URL</label>
                <Input
                  value={String(alertChannel("wecom_ops").webhook_url || "")}
                  onChange={(event) => setAlertChannelField("wecom_ops", "webhook_url", event.target.value)}
                  placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
                  className="h-10 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
            <div className="space-y-2 rounded-lg border border-stone-100 bg-stone-50 p-3">
              <label className="flex items-center gap-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(alertChannel("dingtalk_ops").enabled)}
                  onCheckedChange={(checked) => setAlertChannelField("dingtalk_ops", "enabled", Boolean(checked))}
                />
                钉钉机器人
              </label>
              <div className="space-y-1">
                <label className="text-xs text-stone-500">Webhook URL</label>
                <Input
                  value={String(alertChannel("dingtalk_ops").webhook_url || "")}
                  onChange={(event) => setAlertChannelField("dingtalk_ops", "webhook_url", event.target.value)}
                  placeholder="https://oapi.dingtalk.com/robot/send?access_token=..."
                  className="h-10 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
            <div className="space-y-2 rounded-lg border border-stone-100 bg-stone-50 p-3">
              <label className="flex items-center gap-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(alertChannel("email_ops").enabled)}
                  onCheckedChange={(checked) => setAlertChannelField("email_ops", "enabled", Boolean(checked))}
                />
                SMTP 邮件
              </label>
              <div className="grid gap-3 md:grid-cols-3">
                <div className="space-y-1 md:col-span-2">
                  <label className="text-xs text-stone-500">SMTP 主机</label>
                  <Input
                    value={String(alertChannel("email_ops").smtp_host || "")}
                    onChange={(event) => setAlertChannelField("email_ops", "smtp_host", event.target.value)}
                    placeholder="smtp.example.com"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">端口</label>
                  <Input
                    value={String(alertChannel("email_ops").smtp_port ?? 465)}
                    onChange={(event) => setAlertChannelField("email_ops", "smtp_port", event.target.value)}
                    placeholder="465"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">用户名</label>
                  <Input
                    value={String(alertChannel("email_ops").smtp_user || "")}
                    onChange={(event) => setAlertChannelField("email_ops", "smtp_user", event.target.value)}
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">密码</label>
                  <Input
                    type="password"
                    value={String(alertChannel("email_ops").smtp_password || "")}
                    onChange={(event) => setAlertChannelField("email_ops", "smtp_password", event.target.value)}
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs text-stone-500">发件人地址</label>
                  <Input
                    value={String(alertChannel("email_ops").from_addr || "")}
                    onChange={(event) => setAlertChannelField("email_ops", "from_addr", event.target.value)}
                    placeholder="留空时使用用户名"
                    className="h-10 rounded-xl border-stone-200 bg-white"
                  />
                </div>
                <div className="flex items-end pb-1">
                  <label className="flex items-center gap-2 text-sm text-stone-700">
                    <Checkbox
                      checked={Boolean(alertChannel("email_ops").use_tls !== false)}
                      onCheckedChange={(checked) => setAlertChannelField("email_ops", "use_tls", Boolean(checked))}
                    />
                    SSL / TLS
                  </label>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-stone-500">收件人（逗号分隔，支持多个）</label>
                <Input
                  value={(alertChannel("email_ops").to_addrs || []).join(",")}
                  onChange={(event) =>
                    setAlertChannelField(
                      "email_ops",
                      "to_addrs",
                      event.target.value.split(",").map((item) => item.trim()),
                    )
                  }
                  placeholder="ops@example.com,admin@example.com"
                  className="h-10 rounded-xl border-stone-200 bg-white"
                />
              </div>
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.image_settle_enabled !== false)}
                onCheckedChange={(checked) => setImageSettleEnabled(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">图片二次确认机制</span>
            </div>
            <p className="text-xs text-stone-500">打开后能稍微提升获取图片的成功率。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.image_remove_conversation_after_result)}
                onCheckedChange={(checked) => setImageRemoveConversationAfterResult(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">出图后移除本地对话</span>
            </div>
            <p className="text-xs text-stone-500">成功拿到图片后，异步隐藏 ChatGPT 侧对应的本地对话记录。</p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.image_passthrough_enabled)}
                onCheckedChange={(checked) => setImagePassthroughEnabled(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">图片透传上游直链（省流量）</span>
            </div>
            <p className="text-xs text-stone-500">
              开：生图响应直接返回上游签名 URL，服务器不下行、不重托管，省上下行流量与带宽；
              直链有有效期（约 1 小时），过期后需重新生成。关：服务端下载入库，图片长期可访问。
            </p>
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <Checkbox
                checked={Boolean(config?.image_remove_conversation_always)}
                onCheckedChange={(checked) => setImageRemoveConversationAlways(Boolean(checked))}
              />
              <span className="text-sm text-stone-700">没出图也移除本地对话</span>
            </div>
            <p className="text-xs text-stone-500">失败、超时或只返回文本时也一并隐藏对话记录（打开后包含出图成功的情况）。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">图片超时继续等待时间</label>
            <Input
              value={String(config?.image_timeout_retry_secs || "30")}
              onChange={(event) => setImageTimeoutRetrySecs(event.target.value)}
              placeholder="30"
              className="h-10 rounded-xl border-stone-200 bg-white"
            />
            <p className="text-xs text-stone-500">单位秒，超时后点击"继续等待"额外等待的时间。</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm text-stone-700">图片二次确认等待时间</label>
            <Input
              value={String(config?.image_settle_secs || "2.0")}
              onChange={(event) => setImageSettleSecs(event.target.value)}
              placeholder="2.0"
              className="h-10 rounded-xl border-stone-200 bg-white disabled:cursor-not-allowed disabled:opacity-50"
              disabled={!config?.image_settle_enabled}
            />
            <p className="text-xs text-stone-500">单位秒，找到图片后等待多久再次确认。需配合图片二次确认机制使用。</p>
          </div>
          <div className="flex gap-4 md:col-span-2">
            <div className="flex-1 space-y-2">
              <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(config?.auto_relogin_after_refresh)}
                  onCheckedChange={(checked) => setAutoReloginAfterRefresh(Boolean(checked))}
                />
                刷新后自动尝试移除异常状态
              </label>
              <p className="text-xs text-stone-500">开启后刷新时自动尝试密码登录恢复账号。</p>
            </div>
            <div className="flex-1" aria-hidden="true" />
          </div>
          <label className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white px-4 py-3 text-sm text-stone-700">
            <Checkbox
              checked={Boolean(config?.auto_remove_rate_limited_accounts)}
              onCheckedChange={(checked) => setAutoRemoveRateLimitedAccounts(Boolean(checked))}
            />
            自动移除限流账号
          </label>
          <div className="space-y-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
            <div>
              <label className="text-sm text-stone-700">控制台日志级别</label>
              <p className="mt-1 text-xs text-stone-500">不选择时使用默认 info / warning / error。</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {logLevelOptions.map((level) => (
                <label key={level} className="flex items-center gap-2 text-sm capitalize text-stone-700">
                  <Checkbox
                    checked={Boolean(config?.log_levels?.includes(level))}
                    onCheckedChange={(checked) => setLogLevel(level, Boolean(checked))}
                  />
                  {level}
                </label>
              ))}
            </div>
          </div>
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm text-stone-700">全局附加指令</label>
            <Textarea
              value={String(config?.global_system_prompt || "")}
              onChange={(event) => setGlobalSystemPrompt(event.target.value)}
              placeholder="例如：先判断用户提示词是否合规；遇到违法、色情、暴力、仇恨等请求时拒绝回答。"
              className="min-h-28 rounded-xl border-stone-200 bg-white font-mono text-xs shadow-none"
            />
            <p className="text-xs text-stone-500">每次请求都会作为 system 消息注入，可用于审核用户提示词、避免违规内容、统一约束模型行为或固定角色设定。</p>
          </div>
          <div className="space-y-2 md:col-span-2">
            <label className="text-sm text-stone-700">敏感词</label>
            <Textarea
              value={(config?.sensitive_words || []).join("\n")}
              onChange={(event) => setSensitiveWordsText(event.target.value)}
              placeholder="一行一个，命中即拒绝"
              className="min-h-28 rounded-xl border-stone-200 bg-white font-mono text-xs shadow-none"
            />
            <p className="text-xs text-stone-500">只要用户请求包含任意敏感词，就直接返回拒绝。</p>
          </div>
          <div className="space-y-4 rounded-xl border border-stone-200 bg-white px-4 py-3 md:col-span-2">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <label className="flex items-center gap-3 text-sm text-stone-700">
                <Checkbox
                  checked={Boolean(config?.image_storage?.enabled)}
                  onCheckedChange={(checked) => setImageStorageField("enabled", Boolean(checked))}
                />
                启用远端图片存储（WebDAV / R2）
              </label>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={() => void testImageStorage()}
                  disabled={isTestingImageStorage || !config?.image_storage?.enabled}
                >
                  {isTestingImageStorage ? <LoaderCircle className="size-4 animate-spin" /> : <Cloud className="size-4" />}
                  {isR2Mode ? "测试 R2" : "测试 WebDAV"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={() => void syncImagesToWebDAV()}
                  disabled={isSyncingImageStorage || !config?.image_storage?.enabled || storageMode === "local"}
                >
                  {isSyncingImageStorage ? <LoaderCircle className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                  全量同步
                </Button>
              </div>
            </div>
            <p className="text-xs leading-6 text-stone-500">
              生成时只处理本次新图片；全量同步用于把已有本地图片补传到远端存储（WebDAV / R2）。
            </p>
            <div className="rounded-lg border border-stone-100 bg-stone-50 px-3 py-2 text-xs text-stone-600">
              当前待保存模式：
              <span className="ml-1 font-medium text-stone-900">{STORAGE_MODE_LABEL[storageMode]}</span>
              <span className="ml-2 text-stone-400">修改后需要点保存，或通过测试/同步按钮自动保存。</span>
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm text-stone-700">保存模式</label>
                <Select
                  value={String(config?.image_storage?.mode || "local")}
                  onValueChange={(value) => setImageStorageField("mode", value as ImageStorageMode)}
                  disabled={!config?.image_storage?.enabled}
                >
                  <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="local">仅本机</SelectItem>
                    <SelectItem value="webdav">仅 WebDAV</SelectItem>
                    <SelectItem value="both">本机 + WebDAV</SelectItem>
                    <SelectItem value="r2">仅 R2</SelectItem>
                    <SelectItem value="r2_local">本机 + R2</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {isWebdavMode ? (
                <>
                  <div className="space-y-2 md:col-span-2">
                    <label className="text-sm text-stone-700">WebDAV URL</label>
                    <Input
                      value={String(config?.image_storage?.webdav_url || "")}
                      onChange={(event) => setImageStorageField("webdav_url", event.target.value)}
                      placeholder="https://example.com/dav"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm text-stone-700">用户名</label>
                    <Input
                      value={String(config?.image_storage?.webdav_username || "")}
                      onChange={(event) => setImageStorageField("webdav_username", event.target.value)}
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm text-stone-700">密码</label>
                    <Input
                      type="password"
                      value={String(config?.image_storage?.webdav_password || "")}
                      onChange={(event) => setImageStorageField("webdav_password", event.target.value)}
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm text-stone-700">远端目录</label>
                    <Input
                      value={String(config?.image_storage?.webdav_root_path || "")}
                      onChange={(event) => setImageStorageField("webdav_root_path", event.target.value)}
                      placeholder="chatgpt2api/images"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                </>
              ) : isR2Mode ? (
                <>
                  <div className="space-y-2 md:col-span-3">
                    <label className="text-sm text-stone-700">R2 Account ID</label>
                    <Input
                      value={String(config?.image_storage?.r2_account_id || "")}
                      onChange={(event) => setImageStorageField("r2_account_id", event.target.value)}
                      placeholder="Cloudflare 账号 ID（endpoint 域名前缀）"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2 md:col-span-3">
                    <label className="text-sm text-stone-700">Access Key ID</label>
                    <Input
                      value={String(config?.image_storage?.r2_access_key_id || "")}
                      onChange={(event) => setImageStorageField("r2_access_key_id", event.target.value)}
                      placeholder="R2 API Token Access Key ID"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2 md:col-span-3">
                    <label className="text-sm text-stone-700">Secret Access Key</label>
                    <Input
                      type="password"
                      value={String(config?.image_storage?.r2_secret_access_key || "")}
                      onChange={(event) => setImageStorageField("r2_secret_access_key", event.target.value)}
                      placeholder="R2 API Token Secret Access Key"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm text-stone-700">Bucket</label>
                    <Input
                      value={String(config?.image_storage?.r2_bucket || "")}
                      onChange={(event) => setImageStorageField("r2_bucket", event.target.value)}
                      placeholder="bucket 名"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                  </div>
                  <div className="space-y-2 md:col-span-2">
                    <label className="text-sm text-stone-700">对象前缀</label>
                    <Input
                      value={String(config?.image_storage?.r2_prefix || "images")}
                      onChange={(event) => setImageStorageField("r2_prefix", event.target.value)}
                      placeholder="images"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                      disabled={!config?.image_storage?.enabled}
                    />
                    <p className="text-xs text-stone-500">对象键前缀，与公开直链路径一致（public_base_url 后拼接）。</p>
                  </div>
                </>
              ) : null}
              <div className="space-y-2 md:col-span-3">
                <label className="text-sm text-stone-700">公开访问前缀</label>
                <Input
                  value={String(config?.image_storage?.public_base_url || "")}
                  onChange={(event) => setImageStorageField("public_base_url", event.target.value)}
                  placeholder="https://cdn.example.com/chatgpt2api/images"
                  className="h-10 rounded-xl border-stone-200 bg-white"
                  disabled={!config?.image_storage?.enabled}
                />
                <p className="text-xs text-stone-500">
                  留空时返回本应用 /images/... 代理地址；填入后直接返回公开图片地址（R2 模式下自动拼接对象前缀）。
                </p>
              </div>
            </div>
          </div>
          <div className="space-y-4 rounded-xl border border-stone-200 bg-white px-4 py-3 md:col-span-2">
            <label className="flex items-center gap-3 text-sm text-stone-700">
              <Checkbox
                checked={Boolean(config?.ai_review?.enabled)}
                onCheckedChange={(checked) => setAIReviewField("enabled", Boolean(checked))}
              />
              启用 AI 审核
            </label>
            <p className="text-xs leading-6 text-stone-500">
              开启后会在请求进入生图账号前先调用审核模型，审核不通过会直接拒绝，减少违规提示词触达账号造成风控或封号的风险。
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-2">
                <label className="text-sm text-stone-700">Base URL</label>
                <Input value={String(config?.ai_review?.base_url || "")} onChange={(event) => setAIReviewField("base_url", event.target.value)} placeholder="https://api.openai.com" className="h-10 rounded-xl border-stone-200 bg-white" />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">API Key</label>
                <Input value={String(config?.ai_review?.api_key || "")} onChange={(event) => setAIReviewField("api_key", event.target.value)} placeholder="sk-..." className="h-10 rounded-xl border-stone-200 bg-white" />
              </div>
              <div className="space-y-2">
                <label className="text-sm text-stone-700">Model</label>
                <Input value={String(config?.ai_review?.model || "")} onChange={(event) => setAIReviewField("model", event.target.value)} placeholder="gpt-5.4-mini" className="h-10 rounded-xl border-stone-200 bg-white" />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">审核提示词</label>
              <Textarea value={String(config?.ai_review?.prompt || "")} onChange={(event) => setAIReviewField("prompt", event.target.value)} placeholder="判断用户请求是否允许。只回答 ALLOW 或 REJECT。" className="min-h-24 rounded-xl border-stone-200 bg-white text-xs shadow-none" />
            </div>
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
            onClick={() => void saveConfig()}
            disabled={isSavingConfig}
          >
            {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
