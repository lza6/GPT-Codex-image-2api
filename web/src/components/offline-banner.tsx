"use client";

import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * 离线状态横幅。
 * 当浏览器检测到网络断开时显示顶部横幅，恢复后自动隐藏。
 */
export function OfflineBanner() {
  const [isOffline, setIsOffline] = useState(
    typeof navigator !== "undefined" ? !navigator.onLine : false,
  );

  useEffect(() => {
    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (!isOffline) return null;

  return (
    <div
      className={cn(
        "fixed top-0 left-0 right-0 z-[100] flex items-center justify-center gap-2",
        "bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-lg",
        "animate-in slide-in-from-top",
      )}
    >
      <WifiOff className="size-4" />
      <span>网络连接已断开 — 部分功能可能不可用</span>
    </div>
  );
}