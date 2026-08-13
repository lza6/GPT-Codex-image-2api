"use client";

import { useEffect, useState } from "react";
import { LoaderCircle, Layers, ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { toastError } from "@/lib/toast-helper";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { fetchProviders, type ProviderInfo } from "@/lib/api";

/** 前端默认 Provider 的 localStorage key（账号列表/图片工作台初始选择复用）。 */
export const DEFAULT_PROVIDER_KEY = "chatgpt2api:default_provider";

export function readDefaultProvider(): string {
  if (typeof window === "undefined") {
    return "chatgpt";
  }
  try {
    const stored = window.localStorage.getItem(DEFAULT_PROVIDER_KEY);
    return stored && stored.trim() ? stored.trim() : "chatgpt";
  } catch {
    return "chatgpt";
  }
}

export function writeDefaultProvider(name: string) {
  try {
    window.localStorage.setItem(DEFAULT_PROVIDER_KEY, name);
  } catch {
    // 存储失败忽略
  }
}

export function ProvidersCard() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [defaultProvider, setDefaultProvider] = useState<string>(() => readDefaultProvider());

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchProviders();
        if (!cancelled) {
          setProviders(data.providers ?? []);
        }
      } catch (error) {
        if (!cancelled) {
          toastError(error, "加载 Provider 列表失败");
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const selected = providers.find((p) => p.name === defaultProvider) ?? null;
  const enabledProviders = providers.filter((p) => p.enabled);

  const handleChange = (value: string) => {
    setDefaultProvider(value);
    writeDefaultProvider(value);
    toast.success(`默认 Provider 已切换为 ${value}`);
  };

  return (
    <Card className="rounded-2xl border-white/80 bg-white/90 shadow-sm">
      <CardContent className="space-y-5 p-6">
        <div className="flex items-center gap-2">
          <Layers className="size-4 text-stone-500" />
          <h3 className="text-base font-semibold text-stone-900">多 Provider</h3>
          <span className="rounded-full bg-stone-100 px-2 py-0.5 text-xs font-medium text-stone-500">
            已接入 {enabledProviders.length}/{providers.length}
          </span>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <LoaderCircle className="size-5 animate-spin text-stone-400" />
          </div>
        ) : (
          <div className="space-y-4">
            {/* 默认 Provider 选择器 */}
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div className="text-sm text-stone-600">
                默认 Provider
                <span className="ml-2 text-xs text-stone-400">生图/账号列表等入口的初始选择</span>
              </div>
              <Select value={defaultProvider} onValueChange={handleChange}>
                <SelectTrigger className="h-10 w-full rounded-xl border-stone-200 bg-white sm:w-[180px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {providers.map((p) => (
                    <SelectItem key={p.name} value={p.name} disabled={!p.enabled}>
                      {p.display_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {/* Provider 列表 */}
            <div className="space-y-2">
              {providers.map((p) => (
                <div
                  key={p.name}
                  className="flex items-start justify-between gap-3 rounded-xl border border-stone-200/70 bg-white px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-stone-900">{p.display_name}</span>
                      <Badge variant={p.enabled ? "success" : "secondary"} className="rounded-md">
                        {p.enabled ? "已接入" : "未启用"}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-xs text-stone-500">{p.description}</p>
                    {(p.capabilities ?? []).length > 0 && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        <ShieldCheck className="size-3 text-stone-400" />
                        {(p.capabilities ?? []).map((cap) => (
                          <span
                            key={cap}
                            className="rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500"
                          >
                            {cap}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right">
                    <div className="text-xs font-medium text-stone-500">{p.models?.length ?? 0} 个模型</div>
                  </div>
                </div>
              ))}
            </div>

            {/* 所选 provider 模型详情 */}
            {selected && (selected.models?.length ?? 0) > 0 && (
              <div className="rounded-xl bg-stone-50 px-3 py-2.5">
                <div className="mb-1.5 text-xs font-medium text-stone-600">
                  {selected.display_name} 模型（{selected.models?.length ?? 0}）
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {(selected.models ?? []).map((model) => (
                    <span
                      key={model}
                      className="rounded-full border border-stone-200 bg-white px-2 py-0.5 text-[11px] text-stone-600"
                    >
                      {model}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-[11px] leading-4 text-stone-400">
                  fomimage 已接入（自动注册号池 + 积分用完即弃）。grok 真实出图需要外部上游凭据（xAI API 或 grok 官方账号），当前未接入时选择 grok 图片模型会返回明确错误。
                </p>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
