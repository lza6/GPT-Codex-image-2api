"use client";

import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";

/**
 * 离线状态横幅。
 * 当浏览器检测到网络断开时显示顶部横幅，恢复后自动隐藏。
 * 使用 mounted 状态避免 SSR 渲染（防止"网络已断开"横幅在页面加载时闪现）。
 */
export function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    setIsOffline(typeof navigator !== "undefined" ? !navigator.onLine : false);

    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);

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
    </div>
  );
}