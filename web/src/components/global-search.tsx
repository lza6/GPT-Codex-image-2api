"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "cmdk";
import {
  ImageIcon,
  LayoutDashboard,
  Search,
  Server,
  Settings,
  UserRound,
  Database,
  Logs,
  Bug,
  Wrench,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { fetchAccounts, type Account } from "@/lib/api";

const NAV_ITEMS = [
  { href: "/dashboard", label: "运维看板", icon: LayoutDashboard },
  { href: "/image", label: "生图", icon: ImageIcon },
  { href: "/accounts", label: "号池管理", icon: UserRound },
  { href: "/proxy-pool", label: "IP 池", icon: Server },
  { href: "/image-manager", label: "图片管理", icon: Database },
  { href: "/logs", label: "日志管理", icon: Logs },
  { href: "/debug", label: "调试", icon: Bug },
  { href: "/settings", label: "设置", icon: Wrench },
];

const SETTINGS_ITEMS = [
  { id: "proxy", label: "上游代理" },
  { id: "base_url", label: "Base URL" },
  { id: "global_system_prompt", label: "全局系统提示词" },
  { id: "default_upstream_model_name", label: "默认模型" },
  { id: "scheduler_mode", label: "调度模式" },
  { id: "rate_limit_rpm", label: "速率限制" },
  { id: "backup", label: "备份设置" },
  { id: "image_storage", label: "图片存储" },
  { id: "proxy_runtime", label: "代理运行时" },
  { id: "alert_webhook_url", label: "告警 Webhook" },
  { id: "ai_review", label: "AI 审查" },
  { id: "sensitive_words", label: "敏感词" },
  { id: "trusted_proxies", label: "可信代理" },
  { id: "image_retention_days", label: "图片保留天数" },
  { id: "refresh_account_interval_minute", label: "账号刷新间隔" },
];

export function GlobalSearch() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loadingAccounts, setLoadingAccounts] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Cmd+K 快捷键
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  // 打开时加载账号列表用于搜索
  useEffect(() => {
    if (!open) {
      setQuery("");
      return;
    }
    if (accounts.length === 0 && !loadingAccounts) {
      setLoadingAccounts(true);
      fetchAccounts()
        .then((data) => setAccounts(data.items ?? []))
        .catch(() => { /* 静默失败 */ })
        .finally(() => setLoadingAccounts(false));
    }
  }, [open, accounts.length, loadingAccounts]);

  const handleSelect = useCallback(
    (value: string) => {
      setOpen(false);
      router.push(value);
    },
    [router],
  );

  const filteredAccounts = useMemo(() => {
    if (!query.trim() || accounts.length === 0) return [];
    const q = query.toLowerCase();
    return accounts.filter(
      (a) =>
        (a.email && a.email.toLowerCase().includes(q)) ||
        (a.access_token && a.access_token.toLowerCase().includes(q)),
    );
  }, [query, accounts]);

  const filteredSettings = useMemo(() => {
    if (!query.trim()) return [];
    const q = query.toLowerCase();
    return SETTINGS_ITEMS.filter(
      (item) =>
        item.label.toLowerCase().includes(q) ||
        item.id.toLowerCase().includes(q),
    );
  }, [query]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-start justify-center pt-[15vh]"
      onClick={() => setOpen(false)}
    >
      {/* 遮罩 */}
      <div className="fixed inset-0 bg-black/20 backdrop-blur-sm" />

      {/* 搜索面板 */}
      <div
        className="relative z-10 w-[min(92vw,640px)]"
        onClick={(e) => e.stopPropagation()}
      >
        <Command
          className="overflow-hidden rounded-2xl border border-white/80 bg-white/95 shadow-[0_36px_120px_-45px_rgba(16,24,40,0.4)] backdrop-blur-lg dark:border-white/10 dark:bg-stone-900/95 dark:shadow-[0_36px_120px_-45px_rgba(0,0,0,0.6)]"
          shouldFilter={false}
        >
          <div className="flex items-center border-b border-stone-100 px-4 dark:border-stone-800">
            <Search className="mr-3 size-4 shrink-0 text-stone-400" />
            <CommandInput
              ref={inputRef}
              placeholder="搜索页面、账号、设置..."
              value={query}
              onValueChange={setQuery}
              className="flex h-12 w-full bg-transparent text-sm text-stone-900 outline-none placeholder:text-stone-400 dark:text-stone-100 dark:placeholder:text-stone-500"
            />
            <kbd className="hidden shrink-0 rounded-md border border-stone-200 bg-stone-50 px-1.5 py-0.5 text-[11px] font-medium text-stone-400 sm:inline-block dark:border-stone-700 dark:bg-stone-800 dark:text-stone-500">
              ESC
            </kbd>
          </div>

          <CommandList className="max-h-[360px] overflow-y-auto p-2">
            <CommandEmpty className="py-8 text-center text-sm text-stone-400 dark:text-stone-500">
              未找到匹配结果
            </CommandEmpty>

            {/* 页面导航 */}
            <CommandGroup heading="页面导航">
              {NAV_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <CommandItem
                    key={item.href}
                    value={item.href}
                    onSelect={handleSelect}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-stone-700 transition-colors aria-selected:bg-stone-100 aria-selected:text-stone-900 dark:text-stone-300 dark:aria-selected:bg-stone-800 dark:aria-selected:text-white"
                  >
                    <Icon className="size-4 text-stone-400 dark:text-stone-500" />
                    <span>{item.label}</span>
                  </CommandItem>
                );
              })}
            </CommandGroup>

            {/* 设置项 */}
            {filteredSettings.length > 0 && (
              <CommandGroup heading="设置项">
                {filteredSettings.map((item) => (
                  <CommandItem
                    key={`setting-${item.id}`}
                    value={`/settings#${item.id}`}
                    onSelect={() => handleSelect("/settings")}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-stone-700 transition-colors aria-selected:bg-stone-100 aria-selected:text-stone-900 dark:text-stone-300 dark:aria-selected:bg-stone-800 dark:aria-selected:text-white"
                  >
                    <Settings className="size-4 text-stone-400 dark:text-stone-500" />
                    <span>{item.label}</span>
                    <span className="ml-auto text-[11px] text-stone-400 dark:text-stone-500">
                      设置
                    </span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}

            {/* 账号匹配 */}
            {filteredAccounts.length > 0 && (
              <CommandGroup heading="账号">
                {filteredAccounts.slice(0, 10).map((account) => (
                  <CommandItem
                    key={`account-${account.access_token}`}
                    value={`/accounts`}
                    onSelect={() => handleSelect("/accounts")}
                    className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-stone-700 transition-colors aria-selected:bg-stone-100 aria-selected:text-stone-900 dark:text-stone-300 dark:aria-selected:bg-stone-800 dark:aria-selected:text-white"
                  >
                    <UserRound className="size-4 text-stone-400 dark:text-stone-500" />
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <span className="truncate">
                        {account.email || account.access_token.slice(0, 16) + "..."}
                      </span>
                      <span className="shrink-0 rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-500 dark:bg-stone-800 dark:text-stone-400">
                        {account.status}
                      </span>
                    </div>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </div>
    </div>
  );
}