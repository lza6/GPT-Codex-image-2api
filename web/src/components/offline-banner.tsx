"use client";

import { useEffect, useState } from "react";
import { Database, WifiOff } from "lucide-react";

import { hasCache } from "@/lib/offline-cache";

/**
 * 离线状态横幅。
 * 当浏览器检测到网络断开时显示顶部横幅，恢复后自动隐藏。
 * 如有缓存数据，额外提示"正在使用缓存数据"。
 * 重连后自动触发页面刷新（如用户确认）。
 */
export function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [hasCached, setHasCached] = useState(false);

  useEffect(() => {
    setMounted(true);
    const online = typeof navigator !== "undefined" ? navigator.onLine : true;
    setIsOffline(!online);
    if (!online) {
      // 检查是否有缓存数据
      setHasCached(hasCache("accounts") || hasCache("dashboard"));
    }

    const handleOnline = () => {
      setIsOffline(false);
      // 重连后自动刷新
      if (typeof window !== "undefined") {
        window.location.reload();
      }
    };
    const handleOffline = () => {
      setIsOffline(true);
      setHasCached(hasCache("accounts") || hasCache("dashboard"));
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!mounted) return null;
  if (!isOffline) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[100] flex items-center justify-center gap-2 bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-lg">
      <WifiOff className="size-4" />
      <span>网络连接已断开 — 部分功能可能不可用</span>
      {hasCached && (
        <span className="inline-flex items-center gap-1 ml-2 rounded-md bg-white/20 px-2 py-0.5 text-xs">
          <Database className="size-3" />
          正在使用缓存数据
        </span>
      )}
    </div>
  );
}